"""Request-first dynamic Roblox architecture with conservative source reuse.

Authoritative features come from the user+persisted RAG; a model can propose
architecture but cannot certify existing code, source rights, or gameplay execution.
Only known and exactly matching built-in templates may be reused.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any

from .spec import ModuleKind, RobloxModuleSpec, RobloxService
from .model_router import ModelRouter
from .request_contract import implementation_facets

_VALID_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{2,58}$")
_VALID_REMOTE = re.compile(r"^[A-Z][A-Za-z0-9]{2,55}$")
_ALLOWED_SERVICES = {
    "server": (ModuleKind.SERVER_SCRIPT, RobloxService.SERVER_SCRIPT_SERVICE,
               "src/server/{name}.server.luau"),
    "client": (ModuleKind.CLIENT_SCRIPT, RobloxService.STARTER_PLAYER_SCRIPTS,
               "src/client/{name}.client.luau"),
    "shared": (ModuleKind.SHARED_MODULE, RobloxService.REPLICATED_STORAGE,
               "src/shared/{name}.luau"),
}
_ALLOWED_OBJECTS = {"Part", "SpawnLocation"}
# Validate source ownership, Roblox class semantics and collisions instead of
# arbitrary 16-module/16-remote quotas. Complex user games may legitimately
# require more, and the old quota discarded complete small-model designs.

# These are inspected first-party *code templates*, not third-party libraries.
# A candidate can be reused only when its behavior is an exact request match.
_BUILTIN_CONTRACTS = {
    "coin_pickup": ("Coins", {"Touched", "Coins", "GetPlayerFromCharacter"}),
    "obby_checkpoint": ("ObbyService", {"Touched", "Stage"}),
    "shop_purchase": ("ShopService", {"OnServerInvoke", "Coins", "EconomyRules"}),
    "combat_hit": ("CombatSystem", {"OnServerEvent", "TakeDamage", "MAX_REACH"}),
}

class DynamicDesignError(ValueError):
    pass


def dynamic_design_enabled() -> bool:
    choice = os.environ.get("RMM_ENABLE_DYNAMIC_DESIGN", "auto").lower()
    return choice == "1" or (choice == "auto" and bool(os.environ.get("ROBLOX_LLAMA_SERVER_URL")
                     or os.environ.get("RMM_MODEL_BASE_URL")))


def _normalize_requirements(ledger: dict[str, Any]) -> set[str]:
    return {str(x["id"]) for x in ledger.get("requirements", [])
            if isinstance(x, dict) and x.get("id")}


def choose_reuse(name: str, requirements: list[str], source: str,
                 *, license_confirmed: bool = False) -> dict[str, Any]:
    """Only allow exact-first-party matches; never let model choose a dependency by name."""
    if name not in _BUILTIN_CONTRACTS:
        return {"reuse": False, "reason": "No inspected first-party template for this behavior"}
    expected, markers = _BUILTIN_CONTRACTS[name]
    if not requirements or not all(isinstance(x, str) and x.strip() for x in requirements):
        return {"reuse": False, "reason": "No explicit authored behavior to match"}
    if not source or not markers.issubset(set(marker for marker in markers if marker in source)):
        return {"reuse": False, "reason": "Source does not implement the required behavior markers"}
    if not license_confirmed:
        return {"reuse": False, "reason": "No confirmed reuse rights"}
    return {"reuse": True, "source_template": expected,
            "reason": "First-party template, source inspected and exact behavior verified"}



def _remote_kind(raw: Any) -> str | None:
    """Normalize representation, not protocol semantics.

    'Remote', 'signal', or 'method' alone do not reveal whether a response is
    required. Those remain unresolved until the model explicitly classifies
    the remote, so the host never quietly turns an InvokeServer into FireServer.
    """
    if not isinstance(raw, str):
        return None
    value = re.sub(r"[\s_\-\.]", "", raw).casefold()
    events = {"remoteevent", "event", "fireandforget", "oneway", "fireserver",
              "fireclient", "fireallclients"}
    functions = {"remotefunction", "function", "requestresponse", "rpc",
                 "invokeserver", "invokeclient"}
    if value in events:
        return "RemoteEvent"
    if value in functions:
        return "RemoteFunction"
    return None


def _normalize_remote_rows(raw: Any) -> tuple[list[dict[str, str]], list[str]]:
    """Canonicalize benign LLM JSON variants; return unresolved names intact.

    Accept both [{name,type}] and {name:type} shapes; accept known synonyms
    only. Preserve remote identity and reject conflicting duplicate kinds.
    """
    if isinstance(raw, dict):
        rows: list[Any] = [
            {"name": key, "type": value.get("type", value.get("className",
              value.get("$className"))) if isinstance(value, dict) else value}
            for key, value in raw.items()
        ]
    elif isinstance(raw, list):
        rows = raw
    else:
        raise DynamicDesignError("Invalid remote declarations: expected array or name:type map")
    result: list[dict[str, str]] = []
    unresolved: list[str] = []
    seen: dict[str, str] = {}
    for item in rows:
        if isinstance(item, str):
            m = re.fullmatch(r"\s*([A-Z][A-Za-z0-9]{2,55})\s*[:=]\s*(\w+)\s*", item)
            if not m:
                raise DynamicDesignError("Invalid remote string declaration: " + item[:100])
            name, raw_type = m.groups()
        elif isinstance(item, dict):
            name = item.get("name", item.get("Name", item.get("remote_name")))
            raw_type = item.get(
                "type", item.get("Type", item.get("remote_type",
                item.get("class", item.get("className", item.get("$className",
                item.get("kind"))))))
            )
        else:
            raise DynamicDesignError("Invalid remote declaration entry")
        if not isinstance(name, str) or not _VALID_REMOTE.fullmatch(name):
            raise DynamicDesignError("Remote name collision/invalid name: " + str(name)[:80])
        canonical = _remote_kind(raw_type)
        if name in seen:
            raise DynamicDesignError("Duplicate remote name: " + name)
        seen[name] = canonical or ""
        if canonical is None:
            unresolved.append(name)
            result.append({"name": name, "type": ""})
        else:
            result.append({"name": name, "type": canonical})
    return result, unresolved


def _clean_model_json(response: dict[str, Any], ledger: dict[str, Any],
                      existing_names: set[str]) -> dict[str, Any]:
    if not isinstance(response, dict): raise DynamicDesignError("Architecture must be JSON object")
    required_ids = _normalize_requirements(ledger)
    if not required_ids: raise DynamicDesignError("No original user requirements recorded")
    records = response.get("modules")
    if not isinstance(records, list) or not records:
        raise DynamicDesignError("At least one implementable Luau module required")
    # Source-anchored atomic intents represent the user's gameplay.
    # Genre keyword matches for the same source (e.g. shop) are search hints,
    # not additional independent requests. Keep all unmatched facets mandatory.
    required_facets = {str(f["id"]) for f in implementation_facets(ledger)
                       if f.get("id")}
    all_declared_facets = {str(f["id"]) for f in ledger.get("facets", [])
                           if isinstance(f, dict) and f.get("id")}
    modules: list[RobloxModuleSpec] = []
    chosen: set[str] = set(existing_names)
    assignment: dict[str, list[str]] = {}
    facet_assignment: dict[str, list[str]] = {}
    purposes: dict[str, str] = {}
    for i, row in enumerate(records):
        if not isinstance(row, dict): raise DynamicDesignError("Invalid module")
        name, role = row.get("name"), row.get("role")
        if not isinstance(name, str) or not _VALID_NAME.fullmatch(name):
            raise DynamicDesignError("Illegal Luau name")
        if role not in _ALLOWED_SERVICES: raise DynamicDesignError("Unknown module role")
        if name in chosen: raise DynamicDesignError("Module name collision")
        chosen.add(name)
        ids = row.get("requirement_ids")
        purpose = row.get("behavior")
        if not isinstance(ids, list) or not ids or any(x not in required_ids for x in ids):
            raise DynamicDesignError("Module must reference actual requirement IDs")
        facets = row.get("facet_ids", [])
        if not isinstance(facets, list) or (
                required_facets and (not facets or any(x not in all_declared_facets for x in facets))):
            raise DynamicDesignError("Module must cover actual requested gameplay facets")
        if not isinstance(purpose, str) or len(purpose.strip()) < 24:
            raise DynamicDesignError("Provide substantive behavior and authority contract")
        if re.search(r"\b(?:todo|placeholder|stub|implement later)\b", purpose, re.I):
            raise DynamicDesignError("Nonfunctional design is rejected")
        kind, service, path = _ALLOWED_SERVICES[role]
        module_id = "dyn_" + hashlib.sha256((name + purpose).encode("utf-8")).hexdigest()[:12]
        modules.append(RobloxModuleSpec(module_id=module_id,name=name,kind=kind,
           file_path=path.format(name=name),roblox_service=service,
           description=purpose,depends_on=["mod_network_bridge"] if role != "shared" else []))
        assignment[module_id] = list(dict.fromkeys(ids))
        # Accept an optional generic tag (e.g. 'shop') for compatibility
        # with existing model JSON, but do not count it as a second independent
        # gameplay obligation when its exact source is already atom-owned.
        facet_assignment[module_id] = list(dict.fromkeys(
            facet for facet in facets if facet in required_facets))
        purposes[module_id] = purpose
    covered = {req for refs in assignment.values() for req in refs}
    # Require EVERY authored clause, not just the names the model chose to support.
    if covered != required_ids:
        raise DynamicDesignError("Uncovered original requirements: " + ", ".join(sorted(required_ids - covered)))
    assigned_facets = {facet for refs in facet_assignment.values() for facet in refs}
    if required_facets and assigned_facets != required_facets:
        raise DynamicDesignError("Unimplemented gameplay facets: " +
                                 ", ".join(sorted(required_facets - assigned_facets)))

    # IDs alone do not prove a requirement is implemented. In the actual
    # uploaded space plan, "외게인과 싸움" was marked fully covered by a
    # HostileMineral module and a FightMineral remote: the model had changed
    # fighting aliens into fighting rocks. Validate the independently named
    # combat target directly against the untouched original user request.
    original_request = str(ledger.get("original_prompt", ""))
    explicitly_alien_combat = bool(
        re.search(r"외[계게]인|\\balien(?:s)?\\b|\\bextraterrestrial", original_request, re.I)
        and re.search(r"싸움|싸우|전투|\\bfight|\\bcombat|\\bbattle", original_request, re.I)
    )
    if explicitly_alien_combat:
        found_alien_enemy = any(
            re.search(r"외[계게]인|\\balien(?:s)?\\b|\\bextraterrestrial|\\bNPC\\b|\\benem(?:y|ies)\\b",
                      (m.name + " " + m.description), re.I)
            and re.search(r"싸움|싸우|전투|\\bcombat|\\bfight|\\bdamage|\\battack|\\bhealth|\\bdefeat",
                          (m.name + " " + m.description), re.I)
            for m in modules
        )
        if not found_alien_enemy:
            raise DynamicDesignError(
                "Original user explicitly requested combat with ALIEN ENEMIES "
                "(외계인/외게인), NOT hostile minerals. Keep the separate "
                "special-mineral extraction mechanic and add a real alien NPC "
                "combat server subsystem, corresponding input/Remote behavior "
                "and player-visible acceptance without removing other mechanics."
            )

    remote_rows, unresolved_remotes = _normalize_remote_rows(response.get("remotes", []))
    if unresolved_remotes:
        raise DynamicDesignError(
            "Remote needs explicit RemoteEvent or RemoteFunction: " +
            ", ".join(unresolved_remotes)
        )
    remotes: dict[str, str] = {
        item["name"]: item["type"] for item in remote_rows
    }
    # A RemoteEvent/RemoteFunction is a client<->server transport. A model
    # which declares remotes but proposes only server scripts cannot possibly
    # satisfy the static connectivity gate, even when its JSON is well formed.
    # Catch the impossible architecture HERE and ask the model to add the
    # missing role, before spending GPU time writing eleven unusable scripts.
    if remotes:
        roles = {m.kind for m in modules}
        if ModuleKind.CLIENT_SCRIPT not in roles:
            raise DynamicDesignError(
                "Declared " + str(len(remotes)) +
                " client/server Remotes but no client Luau controller. "
                "Add one or more real client modules that own UI/input and "
                "use each remote consistently with a server handler.")
        if ModuleKind.SERVER_SCRIPT not in roles:
            raise DynamicDesignError(
                "Declared client/server Remotes but no server Luau handler. "
                "Add a server-authoritative module for each remote.")

    raw_objects = response.get("world_objects", [])
    if not isinstance(raw_objects, list):
        raise DynamicDesignError("Invalid world object declarations")
    objects: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in raw_objects:
        if not isinstance(item,dict) or item.get("class") not in _ALLOWED_OBJECTS:
            raise DynamicDesignError("Unsupported world instance class")
        name = item.get("name")
        if not isinstance(name,str) or not _VALID_NAME.fullmatch(name) or name in names:
            raise DynamicDesignError("Invalid or duplicate world instance name")
        if name in {"Baseplate", "SpawnLocation", "Remotes"}:
            raise DynamicDesignError("Cannot replace core Roblox instances")
        names.add(name)
        pos, size = item.get("position"), item.get("size")
        if not (isinstance(pos,list) and len(pos)==3 and
                all(type(x) in (int,float) and math.isfinite(x) and abs(x) <= 4000 for x in pos) and
                isinstance(size,list) and len(size)==3 and
                all(type(x) in (int,float) and math.isfinite(x) and 0.1 <= x <= 512 for x in size)):
            raise DynamicDesignError("Geometry outside bounded Roblox Studio limits")
        objects.append({"name":name,"class":item["class"],
                        "position":pos,"size":size})
    checks=response.get("acceptance")
    if not isinstance(checks,list) or not checks:
        raise DynamicDesignError("Behavioral acceptance cases required")
    accepted: dict[str,str] = {}
    for item in checks:
        if not isinstance(item,dict) or item.get("requirement_id") not in required_ids:
            raise DynamicDesignError("Acceptance case missing authored ID")
        behavior = item.get("observable_result")
        if not isinstance(behavior,str) or len(behavior.strip()) < 18:
            raise DynamicDesignError("Acceptance case needs observable gameplay result")
        accepted[item["requirement_id"]] = behavior
    if set(accepted) != required_ids:
        raise DynamicDesignError("Acceptance coverage incomplete")
    accepted_facets = {}
    for item in response.get("acceptance_facets", []):
        if not isinstance(item, dict) or item.get("facet_id") not in all_declared_facets:
            raise DynamicDesignError("Acceptance references invalid capability facet")
        observable = item.get("observable_result")
        if not isinstance(observable,str) or len(observable.strip()) < 18:
            raise DynamicDesignError("Each capability requires observable behavior")
        if item["facet_id"] in required_facets:
            accepted_facets[item["facet_id"]] = observable
    if required_facets and set(accepted_facets) != required_facets:
        raise DynamicDesignError("Capability-level acceptance cases incomplete")
    return {
        "schema": "rmm/dynamic-design-v1",
        "modules": modules,
        "module_requirements": assignment,
        "module_facets": facet_assignment,
        "module_behaviors": purposes,
        "acceptance_facets": accepted_facets,
        "remotes": remotes,
        "world_objects": objects,
        "acceptance": accepted,
        "design_verified": False,
        "source_reuse": "none_unless_validated",
    }


class RobloxDynamicArchitect:
    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router or ModelRouter()

    def design(self, prompt: str, research: dict[str, Any],
               existing_modules: list[RobloxModuleSpec]) -> dict[str, Any]:
        ledger = research.get("ledger", {})
        if not dynamic_design_enabled():
            raise DynamicDesignError("Local small-model architecture unavailable; configure ROBLOX_LLAMA_SERVER_URL")
        reqs = ledger.get("requirements", [])
        docs = [e for e in research.get("evidence", []) if
                e.get("grounding") == "fetched_official_document"]
        excerpts = [{"url":e["url"],"text":e["excerpt"][:950]}
                    for e in docs[:5]]
        prompt_text = (
            "Design NEW Roblox Luau modules for this game; do not re-use a module merely "
            "because its name sounds similar. Never claim that a package or Creator "
            "Store model was audited. No third-party code reuse without verified "
            "license, exact version, source implementation and compiler checks. "
            "All player rewards, purchases, damage and progression MUST be "
            "server authoritative. Luau scripts are to be written separately. "
            "Return JSON object with modules:[{name,role(server|client|shared),"
            "requirement_ids:[req-001],facet_ids:[pets],behavior}], "
            "remotes MUST be JSON array of {name:string,type:string}. "
            "For every remote, type MUST be exactly RemoteEvent or RemoteFunction: "
            "RemoteEvent sends one-way FireServer/OnServerEvent, while "
            "RemoteFunction returns a result via InvokeServer/OnServerInvoke. "
            "Example remotes:[{name:MineOre,type:RemoteEvent},"
            "{name:PurchaseShipPart,type:RemoteFunction}]. "
            "Do not use type=Remote, Signal, EventType, or RobloxService. "
            "If no client/server interaction is needed output remotes:[]. "
            "world_objects:[{name,class(Part|SpawnLocation),position:[0,0,0],"
            "size:[3,1,3]}], acceptance:[{requirement_id,observable_result}], "
            "acceptance_facets:[{facet_id,observable_result}]. "
            "Module names must be unique PascalCase, 3-58 alphanumeric. Each "
            "original requirement AND EVERY gameplay facet must be assigned "
            "a module and have an observable acceptance case. Do not include existing modules. "
            "Use as many distinct modules, remotes and objects as needed by the "
            "original requested mechanics; do not omit gameplay to satisfy a "
            "fixed count. Avoid duplicate or unused remotes. "
            "For large environments prefer a server procedural world builder. "
            "If remotes is nonempty, include at least one client Luau module AND "
            "one server Luau module. Plan REAL client keyboard/touch UI actions "
            "and corresponding server-authoritative handlers for every declared "
            "remote. Avoid declaring unnecessary response remotes when one "
            "RemoteFunction already returns a value. "
            "Do not output completed Luau here. Do not invent details about docs.\n"
            + json.dumps({"original_prompt":prompt,
                          "requirements":reqs,
                          "facets":implementation_facets(ledger),
                          "known_existing_modules":[m.name for m in existing_modules],
                          "official_docs":excerpts,
                          "existing_capabilities":research.get("reuse_candidates",[])},
                         ensure_ascii=False)
        )
        last_error = ""
        raw: Any = None
        observations = research.setdefault("architecture_attempts", [])
        for attempt in range(4):
            try:
                if attempt and isinstance(raw, dict):
                    # Aider-style feedback: keep working from the previous edit,
                    # rather than repeatedly asking the small model to rebuild
                    # the entire game architecture from scratch.
                    query = (
                        "Design NEW Roblox Luau modules: repair ONLY the invalid "
                        "fields in the previous architecture. Keep valid module "
                        "names, behaviors, requirement_ids, facet_ids, remotes, "
                        "world_objects and acceptance unchanged. Return the entire "
                        "corrected JSON object; do not remove user gameplay. "
                        "Validator observation: " + last_error + "\n"
                        "Required source obligations: " +
                        json.dumps({"requirements": reqs,
                                    "facets": implementation_facets(ledger)},
                                   ensure_ascii=False) + "\n"
                        "Previous JSON:\n" + json.dumps(raw, ensure_ascii=False)[:20000]
                    )
                else:
                    query = prompt_text + (
                        "\nPrevious validator observation: " + last_error +
                        "\nCorrect that error without losing any requirement."
                        if attempt else ""
                    )
                proposed = self.router.complete_json(
                    query, role="planner", temperature=0.1)
                if isinstance(proposed, dict):
                    raw = proposed
                else:
                    raw = None
                    raise DynamicDesignError("Model output must be a JSON object")
                # Repair a malformed remote *type* without regenerating
                # otherwise correct modules and acceptance tests.
                canonical = self._resolve_remote_declarations(raw)
                validated = _clean_model_json(
                    canonical, ledger, {m.name for m in existing_modules})
                observations.append({"attempt": attempt + 1, "passed": True,
                                     "validator": "all architecture obligations assigned"})
                return validated
            except Exception as exc:
                last_error = type(exc).__name__ + ": " + str(exc)[:420]
                observations.append({
                    "attempt": attempt + 1, "passed": False,
                    "validator_error": last_error,
                    # Store exact prior model output for postmortem; hard cap.
                    "model_response": raw if isinstance(raw, dict)
                        and len(json.dumps(raw, ensure_ascii=False)) <= 40000
                        else "unavailable_or_too_large",
                })
                print("[RMM architect] attempt " + str(attempt + 1) +
                      " failed: " + last_error, flush=True)
        raise DynamicDesignError("Architecture self-repair failed; " +
                                 str(len(observations)) + " attempts: " + last_error)

    def _resolve_remote_declarations(self, raw: Any) -> Any:
        if not isinstance(raw, dict) or "remotes" not in raw:
            return raw
        rows, missing = _normalize_remote_rows(raw["remotes"])
        if not missing:
            return dict(raw, remotes=rows)
        modules = raw.get("modules", [])
        context = [
            {"role": row.get("role"), "name": row.get("name"),
             "behavior": str(row.get("behavior", ""))[:300]}
            for row in modules if isinstance(row, dict)
        ] if isinstance(modules, list) else []
        # Classify ONLY ambiguous remote kinds. Never silently assume
        # RemoteEvent for a request/response channel.
        unresolved = set(missing)
        resolved = {r["name"]: r["type"] for r in rows if r["type"]}
        for attempt in range(3):
            if not unresolved:
                break
            batch = sorted(unresolved)
            print("[RMM architect] resolving remote types: " + ", ".join(batch),
                  flush=True)
            answer = self.router.complete_json(
                "Choose exact Roblox transport semantics for ONLY the listed "
                "existing remote names. Return JSON "
                '{"remotes":[{"name":"ExactName","type":"RemoteEvent"}]}. '
                "RemoteEvent = one-way FireServer/OnServerEvent or FireClient. "
                "RemoteFunction = synchronous InvokeServer/OnServerInvoke with "
                "a returned result. Names and module list must not change. "
                "Do not invent extra remote names. "
                "A purchase needing a synchronous result uses RemoteFunction; "
                "a one-way action uses RemoteEvent.\n"
                + json.dumps({"unresolved_remote_names": batch,
                              "modules": context}, ensure_ascii=False),
                role="planner", temperature=0.0,
            )
            if not isinstance(answer, dict) or "remotes" not in answer:
                continue
            proposed, still_missing = _normalize_remote_rows(answer["remotes"])
            _ = still_missing
            for item in proposed:
                if item["name"] in unresolved and item["type"]:
                    resolved[item["name"]] = item["type"]
                    unresolved.remove(item["name"])
        if unresolved:
            raise DynamicDesignError(
                "Cannot determine RemoteEvent vs RemoteFunction for: " +
                ", ".join(sorted(unresolved))
            )
        canonical = [{"name": item["name"],
                      "type": resolved[item["name"]]} for item in rows]
        return dict(raw, remotes=canonical)
