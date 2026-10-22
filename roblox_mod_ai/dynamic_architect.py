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
from pathlib import Path
from typing import Any

from .spec import ModuleKind, RobloxModuleSpec, RobloxService
from .model_router import ModelRouter
from .request_contract import implementation_facets
from .request_semantics import request_semantic_errors
from .semantic_preservation import source_intent_conflicts, source_outcome_conflicts
from .host_architecture import SEMANTIC_FACET_SCHEMA, expand_semantic_facet
from .facet_scope import scope_semantic_systems, _terms
from .semantic_input_contract import (
    canonicalize_interaction_fields, interaction_issues,
    apply_interaction_patch,
)

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

# Keep JSON grammar small: the host enforces coverage, names and semantics.
# Schema-constrained decoding prevents malformed/truncated-looking JSON syntax,
# but it does NOT prove that a proposed gameplay system is implemented.
_FACET_MODULE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "role": {"type": "string", "enum": ["server", "client", "shared"]},
        "requirement_ids": {"type": "array", "items": {"type": "string"}},
        "facet_ids": {"type": "array", "items": {"type": "string"}},
        "behavior": {"type": "string"},
        "uses_remotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "role", "requirement_ids", "facet_ids",
                 "behavior", "uses_remotes"],
}
_FACET_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "modules": {"type": "array", "items": _FACET_MODULE_SCHEMA},
        "remotes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string", "enum": ["RemoteEvent", "RemoteFunction"]},
            },
            "required": ["name", "type"],
        }},
        "world_objects": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "class": {"type": "string", "enum": ["Part", "SpawnLocation"]},
                "position": {"type": "array", "items": {"type": "number"}},
                "size": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["name", "class", "position", "size"],
        }},
        "acceptance": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "requirement_id": {"type": "string"},
                "observable_result": {"type": "string"},
            },
            "required": ["requirement_id", "observable_result"],
        }},
        "acceptance_facets": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "facet_id": {"type": "string"},
                "observable_result": {"type": "string"},
            },
            "required": ["facet_id", "observable_result"],
        }},
    },
    "required": ["modules", "remotes", "world_objects",
                 "acceptance", "acceptance_facets"],
}
_CLIENT_PATCH_SCHEMA = {
    "type": "object",
    "properties": {"modules": {"type": "array", "items": _FACET_MODULE_SCHEMA}},
    "required": ["modules"],
}
# Only the semantically incorrect field should be retried, never a previously
# accepted combat/state-change contract in the same feature.
_SCOPED_SEMANTIC_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"replacement": {"type": "string", "maxLength": 4096}},
    "required": ["replacement"],
}
_SCOPED_DUAL_SEMANTIC_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "server_addition": {"type": "string", "maxLength": 4096},
        "outcome_addition": {"type": "string", "maxLength": 4096},
    },
    "required": ["server_addition", "outcome_addition"],
}

_SCOPED_INPUT_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"systems": {
        "type": "array", "maxItems": 3,
        "items": {"type": "object", "properties": {
            "index": {"type": "integer"},
            "interaction": {"type": "string", "enum": [
                "none", "event", "request_response"]},
            "input_mode": {"type": "string", "enum": [
                "custom", "host_button", "world_prompt"]},
            "client_behavior": {"type": "string", "maxLength": 4096},
        }, "required": ["index", "interaction", "input_mode",
                        "client_behavior"]}},
    },
    "required": ["systems"],
}

# Genre-independent secondary review. The reviewer must quote actual source
# actions and visible results from the proposed facet; its own unsupported
# "yes" is never treated as evidence. The same contract applies to all games.
_SOURCE_FIDELITY_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "covered": {"type": "boolean"},
        "server_quote": {"type": "string"},
        "outcome_quote": {"type": "string"},
        "missing": {"type": "string"},
    },
    "required": ["covered", "server_quote", "outcome_quote", "missing"],
}


def _ground_source_fidelity_review(
    review: Any, server_text: str, outcome_text: str,
) -> str:
    """Return a repairable issue, or empty string for grounded coverage.

    A same-model reviewer is a semantic cross-check, not independent proof
    of code behavior. Verbatim quotes make unsupported approvals detectable.
    """
    if not isinstance(review, dict) or type(review.get("covered")) is not bool:
        return "Review did not provide a bounded coverage verdict"
    if not review["covered"]:
        missing = review.get("missing")
        return ("Unimplemented source action: " + str(missing or "not specified")[:240])
    for key, original in (
        ("server_quote", server_text),
        ("outcome_quote", outcome_text),
    ):
        quote = review.get(key)
        if (not isinstance(quote, str) or len(quote.strip()) < 16
                or " ".join(quote.casefold().split())
                not in " ".join(original.casefold().split())):
            return "Unsupported " + key + ": evidence must quote the authored mechanic"
    return ""


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
    semantic_errors = request_semantic_errors(
        response, ledger.get("request_context", ledger.get("original_prompt", "")))
    if semantic_errors:
        raise DynamicDesignError("; ".join(semantic_errors))
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
    explicit_remote_map = any(isinstance(row, dict) and "uses_remotes" in row
                              for row in records)
    module_remotes: dict[str, list[str]] = {}
    module_roles: dict[str, str] = {}
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
        module_roles[module_id] = role
        if explicit_remote_map:
            names = row.get("uses_remotes")
            if not isinstance(names, list) or any(
                not isinstance(name, str) for name in names
            ):
                raise DynamicDesignError(
                    "Every module needs a list of uses_remotes for explicit wiring")
            module_remotes[module_id] = list(dict.fromkeys(names))
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
        re.search(r"외[계게]인|\balien(?:s)?\b|\bextraterrestrial", original_request, re.I)
        and re.search(r"싸움|싸우|전투|\bfight|\bcombat|\bbattle", original_request, re.I)
    )
    if explicitly_alien_combat:
        found_alien_enemy = any(
            re.search(r"외[계게]인|\balien(?:s)?\b|\bextraterrestrial|\bNPC\b|\benem(?:y|ies)\b",
                      (m.name + " " + m.description), re.I)
            and re.search(r"싸움|싸우|전투|\bcombat|\bfight|\bdamage|\battack|\bhealth|\bdefeat",
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

    if explicit_remote_map:
        for module_id, used_names in module_remotes.items():
            unknown = set(used_names) - set(remotes)
            if unknown:
                raise DynamicDesignError(
                    "Module uses undeclared Remotes: " +
                    ", ".join(sorted(unknown)))
        for name in remotes:
            clients = [mid for mid, names in module_remotes.items()
                       if name in names and module_roles[mid] == "client"]
            servers = [mid for mid, names in module_remotes.items()
                       if name in names and module_roles[mid] == "server"]
            if not clients or not servers:
                raise DynamicDesignError(
                    "Remote " + name + " needs explicit client and server "
                    "module owners in uses_remotes; missing: " +
                    ("client " if not clients else "") +
                    ("server" if not servers else ""))

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
        "module_remotes": module_remotes,
        "acceptance_facets": accepted_facets,
        "remotes": remotes,
        "world_objects": objects,
        "acceptance": accepted,
        "design_verified": False,
        "source_reuse": "none_unless_validated",
    }



def _bind_scoped_feature_ids(
    draft: dict[str, Any],
    *,
    facet_id: str,
    owned_ids: list[str],
    all_facet_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Attach authoritative source-ledger IDs to a ONE-facet model plan.

    Models reliably generate local aliases such as fac-001 instead of the
    source-anchored intent hash (proposal 12 failed all 3 attempts this way).
    Local labels have no authority: only the host knows the original source.
    This binding never changes module behavior, role, remote declarations or
    gameplay acceptance prose. The normal semantic/remote/world validator still
    runs after binding, and cross-facet IDs and missing acceptance are rejected.
    """
    if not isinstance(draft, dict):
        raise DynamicDesignError("Scoped architecture must be JSON object")
    modules = draft.get("modules")
    if not isinstance(modules, list) or not modules:
        raise DynamicDesignError("Scoped architecture has no modules")
    accepted = draft.get("acceptance_facets")
    if not isinstance(accepted, list) or not accepted:
        raise DynamicDesignError("Scoped architecture has no facet acceptance")
    allowed_reqs = set(owned_ids)
    if not allowed_reqs:
        raise DynamicDesignError("Scoped feature has no original requirement IDs")
    response = dict(draft)
    bound_modules = []
    aliases: set[str] = set()
    for row in modules:
        if not isinstance(row, dict):
            raise DynamicDesignError("Invalid scoped module record")
        refs = row.get("requirement_ids")
        if not isinstance(refs, list) or not refs or not set(refs) <= allowed_reqs:
            raise DynamicDesignError("Scoped module has foreign or missing source requirement")
        raw_ids = row.get("facet_ids")
        if not isinstance(raw_ids, list) or not raw_ids or any(
            not isinstance(i, str) or not i.strip() for i in raw_ids
        ):
            raise DynamicDesignError("Scoped module must declare its feature ownership")
        foreign = (set(raw_ids) & all_facet_ids) - {facet_id}
        if foreign:
            raise DynamicDesignError("Scoped module references different original feature: " +
                                     ", ".join(sorted(foreign)))
        aliases.update(raw_ids)
        bound_modules.append(dict(row, facet_ids=[facet_id]))
    results = []
    for item in accepted:
        if not isinstance(item, dict):
            raise DynamicDesignError("Invalid scoped acceptance")
        original = item.get("facet_id")
        if not isinstance(original, str) or not original.strip():
            raise DynamicDesignError("Scoped acceptance lacks feature identity")
        if original in all_facet_ids and original != facet_id:
            raise DynamicDesignError("Acceptance references another original feature")
        observable = item.get("observable_result")
        if not isinstance(observable, str) or len(observable.strip()) < 18:
            raise DynamicDesignError("Scoped acceptance lacks observable behavior")
        aliases.add(original)
        if observable not in results:
            results.append(observable)
    response["modules"] = bound_modules
    # Multiple invented local subfeature labels all belong to this one source
    # span. Preserve the testable observations, not their fabricated identities.
    response["acceptance_facets"] = [{
        "facet_id": facet_id,
        "observable_result": " ".join(results),
    }]
    return response, {"source_facet": facet_id,
                      "model_aliases": sorted(aliases - {facet_id}),
                      "source_requirements": sorted(allowed_reqs)}



class RobloxDynamicArchitect:
    def __init__(self, router: ModelRouter | None = None,
                 checkpoint_dir: Path | str | None = None) -> None:
        self.router = router or ModelRouter()
        self.checkpoint_file = (
            Path(checkpoint_dir).resolve() / "architecture_subplans_checkpoint.json"
            if checkpoint_dir is not None else None
        )

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
        # A single gameplay mechanic needs the same protected architecture as
        # a 12-feature experience. Never select model-owned Roblox wiring by
        # an arbitrary >=3 facet threshold. Old full-JSON transports remain
        # explicitly opt-in for compatibility with saved legacy workflows.
        facets = implementation_facets(ledger)
        if os.environ.get("RMM_LEGACY_ARCHITECTURE_PROTOCOL", "0") != "1":
            if not facets:
                raise DynamicDesignError(
                    "Source requirements have no implementation facets. "
                    "Recover original request decomposition before game planning; "
                    "do not invent a stock project to fill this gap.")
            return self._design_by_facets(prompt, research, existing_modules)
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
                    "model_runtime": getattr(self.router, "last_generation_report", {}),
                    # Store exact prior model output for postmortem; hard cap.
                    "model_response": raw if isinstance(raw, dict)
                        and len(json.dumps(raw, ensure_ascii=False)) <= 40000
                        else "unavailable_or_too_large",
                })
                print("[RMM architect] attempt " + str(attempt + 1) +
                      " failed: " + last_error, flush=True)
        raise DynamicDesignError("Architecture self-repair failed; " +
                                 str(len(observations)) + " attempts: " + last_error)


    def _design_by_facets(self, prompt: str, research: dict[str, Any],
                          existing_modules: list[RobloxModuleSpec]) -> dict[str, Any]:
        """Small-model orchestration: scoped architecture calls, retained successes.

        The host owns the merge, requirement IDs, duplicate detection, and
        validation. A failed facet never causes already accepted facets to be
        regenerated. A missing client role is fixed with a small additive
        module-only response, never by reproducing the entire game design.
        """
        ledger = research["ledger"]
        facets = implementation_facets(ledger)
        required = {r["id"]: r for r in ledger.get("requirements", [])
                    if isinstance(r, dict) and r.get("id")}
        docs = [e for e in research.get("evidence", [])
                if e.get("provider") == "official_docs"
                and e.get("grounding") == "fetched_official_document"]
        reserved_modules = {m.name for m in existing_modules}
        reserved_remotes: set[str] = set()
        reserved_objects: set[str] = set()
        accepted_parts: list[dict[str, Any]] = []
        observations = research.setdefault("architecture_attempts", [])
        checkpoints = research.setdefault("architecture_subplans", [])

        # Preserve valid feature semantics across re-retrieval of official
        # documentation. Search ranking, snippets and last_updated metadata
        # fluctuate even if the user's request, action ownership and host ABI
        # are unchanged. Documentation is reference evidence, not a source
        # contract; every cached design is still validated with current host
        # policy, source facet IDs, collisions and action/Remote constraints.
        signature = hashlib.sha256(json.dumps({
            "policy_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "host_policy_sha256": hashlib.sha256(
                (Path(__file__).parent / "host_architecture.py").read_bytes()
            ).hexdigest(),
            "scope_policy_sha256": hashlib.sha256(
                (Path(__file__).parent / "facet_scope.py").read_bytes()
            ).hexdigest(),
            "semantic_preservation_sha256": hashlib.sha256(
                (Path(__file__).parent / "semantic_preservation.py").read_bytes()
            ).hexdigest(),
            "request_semantics_sha256": hashlib.sha256(
                (Path(__file__).parent / "request_semantics.py").read_bytes()
            ).hexdigest(),
            "original_prompt": prompt, "ledger": ledger,
            "reserved_modules": sorted(reserved_modules),
        }, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        stored_parts: dict[str, Any] = {}
        if self.checkpoint_file is not None and os.environ.get(
                "RMM_DISABLE_ARCHITECTURE_CACHE", "0") != "1":
            try:
                saved = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
                if (saved.get("schema") == "rmm/scoped-design-checkpoint-v1"
                        and saved.get("input_sha256") == signature
                        and isinstance(saved.get("facets"), dict)):
                    stored_parts = saved["facets"]
            except (OSError, ValueError, TypeError, AttributeError):
                pass

        def persist_part(feature_id: str, design: dict[str, Any]) -> None:
            if self.checkpoint_file is None or os.environ.get(
                    "RMM_DISABLE_ARCHITECTURE_CACHE", "0") == "1":
                return
            stored_parts[feature_id] = design
            self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            staging = self.checkpoint_file.with_suffix(".json.tmp")
            staging.write_text(json.dumps({
                "schema": "rmm/scoped-design-checkpoint-v1",
                "input_sha256": signature, "facets": stored_parts,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            staging.replace(self.checkpoint_file)

        for index, facet in enumerate(facets):
            facet_id = str(facet["id"])
            owned_ids = list(dict.fromkeys(
                rid for rid in facet.get("requirements", []) if rid in required))
            if not owned_ids:
                raise DynamicDesignError("Feature " + facet_id +
                                         " has no valid source requirement")
            subset = [required[rid] for rid in owned_ids]
            # The original request may describe other unrelated features
            # (e.g. alien combat). Do not enforce them on a mining-only slice.
            slice_request = " ".join(str(r.get("statement", "")) for r in subset)
            slice_ledger = {"requirements": subset, "facets": [facet],
                            "original_prompt": slice_request, "request_context": prompt}
            # Retrieval queries are model-authored search hints, NOT source
            # requirements. Source classification can include neighboring
            # actions in an English query even when this span owns only one.
            # Only the original user span may authorize an implementation.
            source_owned_feature = {
                "id": facet_id, "requirements": owned_ids,
                "source_span": slice_request,
            }
            # RAG retrieval status is not evidence of relevance. The real
            # plan-50 request for launching a ship retrieved tutorials on
            # grouping/animating Parts; passing those snippets encouraged
            # another upgrade editor instead of a launch action. Require
            # distinct topical terms from the source intent in the doc's
            # URL/title/short excerpt before adding it to a 9B prompt.
            intent_terms = _terms(str(facet.get("search_query") or ""))
            excerpts = [
                {"url": e["url"], "text": str(e.get("excerpt", ""))[:650]}
                for e in docs
                if e.get("facet") == facet_id
                and len(intent_terms & _terms(
                    str(e.get("url", "")) + " " +
                    str(e.get("excerpt", ""))[:650]
                )) >= 2
            ][:2]
            payload = {"feature_id": facet_id, "feature": source_owned_feature,
                       "source_requirements": subset,
                       "game_context": {"scope": "only_this_source_clause",
                                        "original_request": prompt},
                       "existing_module_names": sorted(reserved_modules),
                       "existing_remote_names": sorted(reserved_remotes),
                       "existing_world_object_names": sorted(reserved_objects),
                       "official_references": excerpts}
            # Ask the 9B model ONLY for game-specific behavior. The host
            # owns Roblox role allocation, instance hierarchy, IDs, remote
            # names/kinds, world coordinates and acceptance source binding.
            task = (
                "Describe ONLY the requested Roblox GAMEPLAY mechanic as JSON. "
                "Return {systems:[{name,server_behavior,client_behavior,"
                "interaction,input_mode,observable_result,world_entities}]}. "
                "Each system has concrete server-owned rules, including "
                "validation of any player actions. interaction is: "
                "none (server-only), event (player action without direct "
                "return), or request_response (player request needing result). "
                "For approaching exactly one static world object to interact, "
                "use input_mode=world_prompt, interaction=event and exactly "
                "one world_entities name. The host installs ProximityPrompt "
                "and safely dispatches it on the SERVER: no client module "
                "or Remote needs to be authored. This cannot return a "
                "RemoteFunction response or select among inventory items. "
                "Set input_mode=host_button ONLY for a no-argument action "
                "that needs no target, item selection, aiming, or other "
                "custom UI. The host then builds all screen buttons and "
                "Remote calls without another AI code generation. "
                "With host_button, world_entities MUST be empty. "
                "Otherwise set input_mode=custom to generate the necessary "
                "game-specific client interactions. "
                "For custom request_response actions with finite menu choices, "
                "provide action_choices:[{id,label}] with stable short action "
                "IDs the SERVER will handle and visible labels. These same IDs "
                "are validated by the host and rendered as client buttons, so "
                "the small coder never needs to invent its own Remote IDs. "
                "Omit action_choices for aiming, free-form targeting or "
                "complex input not representable as selectable choices. "
                "If interaction is none, input_mode=custom and "
                "client_behavior must be empty. "
                "If interaction needs player input, describe its actual "
                "UI/input and visible response in client_behavior. "
                "world_entities is an array of gameplay-specific object names; "
                "empty if no static world object is needed. Do NOT provide "
                "Luau code, Remote names/types, JSON source IDs, module roles, "
                "file paths, Roblox coordinates, geometries, template scripts "
                "or generic engine boilerplate. The host generates those. "
                "The complete original_request is context for ambiguous nouns, "
                "currency and progression only; source_requirements defines this "
                "feature's exclusive implementation ownership. Ordinary purchases "
                "use earned game currency; never invent Robux monetization. "
                "If player-to-player trading is not explicitly requested, do "
                "not invent peer inventories, counteroffers, or cross-profile "
                "transactions. Generic in-game trading uses a validated "
                "server-priced item/resource catalog. "
                "IMPORTANT: one source facet only, not the whole game. "
                "Do NOT echo other features from original_request. "
                "Return one system PER independently triggered gameplay "
                "action, with its own authoritative state transition, "
                "actual target and visible outcome. A single source clause "
                "may require multiple distinct actions; do not collapse "
                "them into one generic menu or success description. "
                "Do not reproduce actions owned by other source clauses. "
                "Each system MUST directly implement the user's single "
                "source_requirements clause. No unrelated systems. "
                "Do not claim a world has been built or gameplay tested. "
                "JSON ONLY.\n"
                + json.dumps({
                    "feature_id": facet_id,
                    "feature": source_owned_feature,
                    "source_requirements": subset,
                    "game_context": {"scope": "only_this_source_clause",
                                        "original_request": prompt},
                    "official_references": excerpts,
                }, ensure_ascii=False)
            )
            previous_error = ""
            draft: dict[str, Any] | None = None
            semantic_repair: tuple[dict[str, Any], dict[str, list[str]]] | None = None
            semantic_replan: list[str] | None = None
            input_repair: tuple[dict[str, Any], dict[int, list[str]]] | None = None
            successful = False
            cache_hit = False
            for attempt in range(3):
                rejected_scope_names: list[str] = []
                previous_repair = semantic_repair
                previous_replan = semantic_replan
                previous_input_repair = input_repair
                try:
                    # A previously validated feature is reused only after the
                    # SAME current source ownership and collision checks.
                    if attempt == 0 and isinstance(stored_parts.get(facet_id), dict):
                        draft = stored_parts[facet_id]
                        cache_hit = True
                    # Repair a missing client/server role by APPENDING modules
                    # instead of asking the small model to reprint its large JSON.
                    missing_role = (
                        isinstance(draft, dict) and draft.get("remotes")
                        and not any(m.get("role") == "client"
                                    for m in draft.get("modules", [])
                                    if isinstance(m, dict))
                    )
                    if cache_hit:
                        pass  # validation below, no model inference needed
                    elif input_repair is not None:
                        original, invalid = input_repair
                        input_repair = None
                        # Repair only interaction metadata and client input.
                        # Preserve server behavior, results, actors and objects.
                        patch = self.router.complete_json(
                            "Correct ONLY the interaction protocol for the "
                            "indicated existing system indexes. Return JSON "
                            "{systems:[{index,interaction,input_mode,"
                            "client_behavior}]}. interaction is one of "
                            "none/event/request_response; input_mode is one "
                            "of custom/host_button/world_prompt. host_button "
                            "requires zero arguments and no world_entities "
                            "or action_choices; custom supports targets and "
                            "selected items. world_prompt requires event "
                            "and exactly one world object. For player-driven "
                            "actions, client_behavior must describe real "
                            "input/UI, not just an animation. Preserve the "
                            "requested gameplay, server rules, world targets, "
                            "action choices and observable results. JSON ONLY.\n"
                            + json.dumps({
                                "issues": invalid,
                                "systems": [{
                                    "index": i,
                                    "interaction": original["systems"][i].get(
                                        "interaction"),
                                    "input_mode": original["systems"][i].get(
                                        "input_mode", "custom"),
                                    "world_entities": original["systems"][i].get(
                                        "world_entities", []),
                                    "action_choices": original["systems"][i].get(
                                        "action_choices", []),
                                    "client_behavior": original["systems"][i].get(
                                        "client_behavior", ""),
                                } for i in invalid],
                                "previous_rejection": previous_error,
                            }, ensure_ascii=False),
                            role="planner", temperature=0.0, max_tokens=600,
                            json_schema=_SCOPED_INPUT_REPAIR_SCHEMA,
                        )
                        draft = apply_interaction_patch(original, patch)
                    elif semantic_replan is not None:
                        missing_rules = list(semantic_replan)
                        semantic_replan = None
                        # Discard a design that substituted the requested
                        # action. This branch is selected by generic source-
                        # intent coverage, never by a game genre, action name
                        # or validator error code. Replan ONLY this facet.
                        # Preserve independent actions: one source clause may
                        # legitimately require several interacting systems.
                        draft = self.router.complete_json(
                            "The previous proposal did not implement the "
                            "source-owned gameplay actions. Recreate only "
                            "the missing source requirement as a short JSON "
                            "object: {systems:[{name,server_behavior,"
                            "client_behavior,observable_result,interaction,"
                            "input_mode,world_entities}]}. Produce one system "
                            "per independently triggered player/server action "
                            "(up to three), each with a real server-owned "
                            "transition, actor/target and visible consequence. "
                            "Do not substitute a prerequisite, menu, visual "
                            "effect or another action for the requested "
                            "transition. Preserve the request's actual input "
                            "shape: none, event or request_response; choose "
                            "world_prompt, host_button or custom only when "
                            "appropriate. Return world_entities=[] when no "
                            "physical object is needed. Do not add unrelated "
                            "mechanics. Short JSON only.\n"
                            + json.dumps({
                                "source_requirements": subset,
                                "original_request_context_only": prompt,
                                "missing_obligations": missing_rules,
                            }, ensure_ascii=False),
                            role="planner", temperature=0.0,
                            max_tokens=1024, json_schema=SEMANTIC_FACET_SCHEMA,
                        )
                    elif semantic_repair is not None:
                        previous_draft, field_issues = semantic_repair
                        semantic_repair = None
                        draft = previous_draft  # retain the valid base on patch error
                        original_system = previous_draft["systems"][0]
                        fields = list(field_issues)
                        dual = len(fields) > 1
                        # Multiple obligations in one source clause can fail
                        # independently. Repair BOTH server state and visible
                        # outcome in ONE inference, instead of consuming the
                        # final retry on a second single-field patch.
                        if dual:
                            instruction = (
                                "Return ONLY JSON with server_addition and "
                                "outcome_addition strings. Each is a SHORT "
                                "additional rule that satisfies ALL listed "
                                "missing constraints for its corresponding "
                                "field. Preserve EVERY existing behavior. "
                                "A condition that something already exists "
                                "is not a newly committed state transition. "
                                "An outcome must name the actual target and "
                                "observable state change, not just success "
                                "feedback. Do not replace prior behavior or "
                                "invent unrelated game actions. JSON ONLY.\\n"
                            )
                            schema = _SCOPED_DUAL_SEMANTIC_REPAIR_SCHEMA
                            token_budget = 1000
                        else:
                            instruction = (
                                "Return ONLY JSON {replacement:string} with "
                                "the ADDITIONAL rule satisfying EVERY listed "
                                "missing constraint for the specified field. "
                                "Do not repeat prior statements. A prerequisite "
                                "or a generic menu result is NOT the required "
                                "state transition. Preserve all original actions "
                                "and their targets. JSON ONLY.\\n"
                            )
                            schema = _SCOPED_SEMANTIC_REPAIR_SCHEMA
                            token_budget = 780
                        patch = self.router.complete_json(
                            instruction + json.dumps({
                                "fields": fields,
                                "validator_issues": field_issues,
                                "source_requirements": subset,
                                "previous_system": original_system,
                                **({"field": fields[0]} if not dual else {}),
                            }, ensure_ascii=False),
                            role="planner", temperature=0.0,
                            max_tokens=token_budget, json_schema=schema,
                        )
                        if not isinstance(patch, dict):
                            raise DynamicDesignError(
                                "Semantic repair returned no JSON object"
                            )
                        revised: dict[str, str] = {}
                        for field in fields:
                            answer_key = (
                                ("server_addition" if field == "server_behavior"
                                 else "outcome_addition")
                                if dual else "replacement"
                            )
                            addition = patch.get(answer_key)
                            # Smaller local structured-output backends sometimes
                            # use a semantic field name despite the requested
                            # compact {replacement:string} schema. Accept only
                            # the exact field's known aliases, then revalidate
                            # the completed contract; never use a different
                            # behavioral field as the missing rule.
                            if not isinstance(addition, str):
                                for alias in (
                                    field,
                                    "server_addition" if field == "server_behavior"
                                    else "outcome_addition",
                                    "replacement",
                                ):
                                    candidate = patch.get(alias)
                                    if isinstance(candidate, str):
                                        addition = candidate
                                        break
                            if (not isinstance(addition, str)
                                    or not 24 <= len(addition.strip()) <= 4096):
                                raise DynamicDesignError(
                                    "Semantic repair omitted " + field
                                )
                            existing = original_system.get(field)
                            if not isinstance(existing, str):
                                existing = ""
                            # Keep the model-authored feedback as the basis
                            # for a previously omitted observable_result.
                            if field == "observable_result" and not existing:
                                existing = original_system.get(
                                    "client_behavior", "")
                            addition = addition.strip()
                            if addition.casefold() in existing.casefold():
                                raise DynamicDesignError(
                                    "Semantic repair repeated the previous "
                                    "rule for " + field
                                )
                            combined = (
                                existing.strip().rstrip(". ") + ". " + addition
                                if existing.strip() else addition
                            )
                            if len(combined) > 4096:
                                raise DynamicDesignError(
                                    "Semantic repair exceeds field limit: "
                                    + field
                                )
                            revised[field] = combined
                        draft = dict(previous_draft)
                        draft["systems"] = [
                            dict(original_system, **revised)
                        ]
                    elif missing_role:
                        patch = self.router.complete_json(
                            "Return ONLY JSON {\"modules\":[...]} with NEW "
                            "client Luau controller modules that supply actual "
                            "UI/input and invoke the already declared remotes. "
                            "Do not regenerate server modules, remotes, objects "
                            "or acceptance cases. Each module must have name, "
                            "role=client, requirement_ids, facet_ids, behavior "
                            "(at least 24 characters), and uses_remotes "
                            "listing each invoked Remote name. Use ONLY the "
                            "supplied source IDs. Use new names.\n"
                            + json.dumps({
                                "feature": facet, "requirements": subset,
                                "existing_modules": draft["modules"],
                                "remotes": draft["remotes"],
                                "reserved_names": sorted(reserved_modules),
                            }, ensure_ascii=False),
                            role="planner", temperature=0.0, max_tokens=2600,
                            json_schema=_CLIENT_PATCH_SCHEMA,
                        )
                        extra = patch.get("modules") if isinstance(patch, dict) else None
                        if not isinstance(extra, list) or not extra or any(
                            not isinstance(row, dict) or row.get("role") != "client"
                            for row in extra
                        ):
                            raise DynamicDesignError("Client-only repair returned no client modules")
                        draft = dict(draft, modules=[*draft["modules"], *extra])
                    else:
                        query = task + (
                            "\nPREVIOUS VALIDATOR FAILURE: " + previous_error +
                            "\nRegenerate ONLY this feature, preserving its requested behavior."
                            if attempt else ""
                        )
                        draft = self.router.complete_json(
                            query, role="planner", temperature=0.1,
                            max_tokens=1400, json_schema=SEMANTIC_FACET_SCHEMA,
                        )
                    if not isinstance(draft, dict):
                        raise DynamicDesignError("Facet architecture must be JSON object")
                    # New default: the model chooses only gameplay semantics.
                    # Old saved plans and deterministic CI transports use
                    # explicit modules; validate that legacy contract exactly
                    # as before rather than silently breaking existing files.
                    if "systems" in draft:
                        # A small model may echo unrelated features from the
                        # full request. Attribute ONLY demonstrably source-owned
                        # systems; every dropped feature keeps its own facet.
                        draft, rejected_scope_names = scope_semantic_systems(
                            draft, facet=facet, all_facets=facets)
                        # Two disjoint enum domains can be restored after a
                        # verified exchange. Ambiguous input is never guessed.
                        draft, swapped_indexes = canonicalize_interaction_fields(draft)
                        invalid_input = interaction_issues(draft)
                        if invalid_input:
                            input_repair = (draft, invalid_input)
                            raise DynamicDesignError(
                                "SEMANTIC_INPUT_CONTRACT: " + str(invalid_input))
                        # Compare original user actions against the complete
                        # proposed behavior even for novel genres for which
                        # no specialized regular-expression validator exists.
                        # This is intentionally separate from genre adapters.
                        if (getattr(self.router, "supports_source_fidelity_audit", False)
                                and os.environ.get(
                                    "RMM_SOURCE_FIDELITY_AUDIT", "1") != "0"
                                and not cache_hit):
                            systems = draft.get("systems", [])
                            server_text = " ".join(
                                str(s.get("server_behavior") or "")
                                for s in systems if isinstance(s, dict))
                            outcome_text = " ".join(
                                str(s.get("observable_result")
                                    or s.get("client_behavior") or "")
                                for s in systems if isinstance(s, dict))
                            for original_source in subset:
                                review = self.router.complete_json(
                                    "Audit the source requirement AGAINST "
                                    "the drafted server behavior and observable "
                                    "result. Determine whether all actions and "
                                    "their targets explicitly requested by the "
                                    "source are genuinely implemented, not just "
                                    "mentioned or used as prerequisites. "
                                    "An unrelated mechanic, an open menu, "
                                    "a success toast, or an already-existing "
                                    "state is not the requested action. "
                                    "If covered, copy one EXACT continuous "
                                    "substring (at least 16 characters) "
                                    "from server_behavior into server_quote "
                                    "and one from observable_result into "
                                    "outcome_quote that demonstrate the "
                                    "requested transition. If not covered, "
                                    "return covered=false and explain the "
                                    "missing action in missing. "
                                    "Return ONLY JSON with covered:boolean, "
                                    "server_quote:string, outcome_quote:string, "
                                    "missing:string. No extra keys.\\n"
                                    + json.dumps({
                                        "source_requirement": original_source,
                                        "server_behavior": server_text[:2400],
                                        "observable_result": outcome_text[:1600],
                                    }, ensure_ascii=False),
                                    role="planner", temperature=0.0,
                                    max_tokens=360,
                                    json_schema=_SOURCE_FIDELITY_REVIEW_SCHEMA,
                                )
                                issue = _ground_source_fidelity_review(
                                    review, server_text, outcome_text)
                                if issue:
                                    raise DynamicDesignError(
                                        "SEMANTIC_FIDELITY_CONTRACT: " + issue)
                        semantic_errors = request_semantic_errors(draft, prompt)
                        if semantic_errors:
                            raise DynamicDesignError(
                                "SEMANTIC_REQUEST_CONTRACT: " + "; ".join(
                                    semantic_errors))
                        draft = expand_semantic_facet(
                            draft, facet_id=facet_id,
                            requirement_ids=owned_ids,
                            source_requirements=subset,
                            reserved_modules=reserved_modules,
                            reserved_remotes=reserved_remotes,
                            reserved_objects=reserved_objects,
                        )
                        draft["_host_semantic"] = True
                    # Source IDs are host-owned, not model-generated. One
                    # scoped task equals one canonical source facet.
                    draft, id_binding = _bind_scoped_feature_ids(
                        draft, facet_id=facet_id, owned_ids=owned_ids,
                        all_facet_ids={str(f["id"]) for f in facets},
                    )
                    draft = self._resolve_remote_declarations(draft)
                    rows, _ = _normalize_remote_rows(draft.get("remotes", []))
                    overlap = reserved_remotes.intersection(r["name"] for r in rows)
                    if overlap:
                        raise DynamicDesignError(
                            "Remote collision with completed feature: " +
                            ", ".join(sorted(overlap)))
                    objects = draft.get("world_objects", [])
                    if not isinstance(objects, list):
                        raise DynamicDesignError("World objects must be a list")
                    overlap_objects = reserved_objects.intersection(
                        obj.get("name") for obj in objects if isinstance(obj, dict))
                    if overlap_objects:
                        raise DynamicDesignError(
                            "World object collision: " +
                            ", ".join(sorted(overlap_objects)))
                    part = _clean_model_json(draft, slice_ledger, reserved_modules)
                    reserved_modules.update(m.name for m in part["modules"])
                    reserved_remotes.update(part["remotes"])
                    reserved_objects.update(obj["name"] for obj in part["world_objects"])
                    accepted_parts.append(draft)
                    persist_part(facet_id, draft)
                    checkpoints.append({
                        "cache_hit": cache_hit,
                        "facet_id": facet_id,
                        "module_names": [m.name for m in part["modules"]],
                        "remote_names": list(part["remotes"]),
                        "validated": True,
                        "id_binding": id_binding,
                    })
                    observations.append({
                        "facet_id": facet_id, "attempt": attempt + 1,
                        "passed": True, "validator": "scoped feature validated",
                        "cache_hit": cache_hit,
                        "id_binding": id_binding,
                        "out_of_scope_systems_ignored": rejected_scope_names,
                    })
                    successful = True
                    break
                except Exception as exc:
                    if cache_hit:
                        # Never retry the same corrupt checkpoint as if the
                        # model had generated it again.
                        stored_parts.pop(facet_id, None)
                        cache_hit = False
                    previous_error = type(exc).__name__ + ": " + str(exc)[:500]
                    observations.append({
                        "facet_id": facet_id, "attempt": attempt + 1,
                        "passed": False, "validator_error": previous_error,
                        "model_runtime": getattr(self.router, "last_generation_report", {}),
                        "model_response": draft if isinstance(draft, dict)
                            and len(json.dumps(draft, ensure_ascii=False)) <= 16000
                            else "unavailable_or_too_large",
                    })
                    # Preserve the original facet plan when the model's
                    # bounded repair response is malformed. Retrying the SAME
                    # small repair is preferable to regenerating 1,400+ output
                    # tokens and losing source-scoped progress.
                    if (previous_repair is not None
                            and ("Semantic repair omitted " in previous_error
                                 or "Semantic repair returned no JSON" in previous_error
                                 or "Model JSON completion truncated" in previous_error)):
                        semantic_repair = previous_repair
                    if previous_input_repair is not None and input_repair is None:
                        # Invalid bounded patches remain local to this facet.
                        input_repair = previous_input_repair
                    if previous_replan is not None:
                        # Any failed bounded replan stays bounded, including
                        # omitted fields, provider errors, semantic mismatch or
                        # output truncation. No fallback to the long original
                        # prompt that caused plan-50's final length failure.
                        # A newer semantic contract below may replace the
                        # missing-obligations list with more precise evidence.
                        semantic_replan = previous_replan
                    if "SEMANTIC_FIDELITY_CONTRACT:" in previous_error:
                        # A coverage reviewer rejected this source action,
                        # regardless of genre. Recreate only the affected
                        # feature; do not keep a falsely validated checkpoint.
                        semantic_replan = [previous_error]
                        semantic_repair = None
                    # Compute *all* contracts against the complete scoped
                    # feature, including multi-system responses. Never infer
                    # a repair policy from a scenario-specific error token or
                    # blindly edit systems[0] when the model supplied several
                    # independent gameplay actions.
                    if (isinstance(draft, dict)
                            and isinstance(draft.get("systems"), list)
                            and draft["systems"]
                            and all(isinstance(s, dict)
                                    for s in draft["systems"])
                            and ("SEMANTIC_SOURCE_CONTRACT " in previous_error
                                 or "SEMANTIC_REQUEST_CONTRACT:" in previous_error)):
                        systems = draft["systems"]
                        server_text = " ".join(
                            str(s.get("server_behavior") or "") for s in systems)
                        outcome_text = " ".join(
                            str(s.get("observable_result")
                                or s.get("client_behavior") or "")
                            for s in systems)
                        issues: dict[str, list[str]] = {}
                        missing_source_actions: list[str] = []
                        for source in subset:
                            statement = str(source.get("statement") or "")
                            for field, failures in (
                                ("server_behavior", source_intent_conflicts(
                                    statement, server_text)),
                                ("observable_result", source_outcome_conflicts(
                                    statement, outcome_text)),
                            ):
                                if failures:
                                    issues.setdefault(field, []).extend(failures)
                            missing_source_actions.extend(
                                source_intent_conflicts(
                                    statement, server_text + " " + outcome_text,
                                    require_implementation=False)
                            )
                        violations = [
                            e for values in issues.values() for e in values
                        ]
                        if "SEMANTIC_REQUEST_CONTRACT:" in previous_error:
                            # An unsolicited mechanic cannot be safely
                            # appended around; the model must redesign the
                            # source-owned feature without it.
                            semantic_replan = [previous_error]
                            semantic_repair = None
                        elif issues and (
                            missing_source_actions or len(systems) != 1
                        ):
                            # A missing requested action is not repairable by
                            # tacking prose onto an unrelated action. Multiple
                            # systems cannot be safely patched at index zero.
                            semantic_replan = (
                                missing_source_actions or violations)
                            semantic_repair = None
                        elif issues:
                            # Requested action is already present: supplement
                            # missing state authority or observable feedback,
                            # preserving the rest of the valid system.
                            semantic_repair = (draft, issues)
                            semantic_replan = None
                    if "no client Luau controller" not in previous_error:
                        draft = None
                    print("[RMM architect] feature " + facet_id +
                          " attempt " + str(attempt + 1) +
                          " failed: " + previous_error, flush=True)
            if not successful:
                raise DynamicDesignError(
                    "Feature " + facet_id + " could not be validated after "
                    "3 scoped attempts: " + previous_error)
            print("[RMM architect] feature " + facet_id + " (" +
                  str(index + 1) + "/" + str(len(facets)) +
                  ") contract accepted", flush=True)

        combined = {"modules": [], "remotes": [], "world_objects": [],
                    "acceptance": [], "acceptance_facets": []}
        for part in accepted_parts:
            for key in combined:
                combined[key].extend(part.get(key, []))
        # Re-run the full original-request validator. No successful feature
        # means the whole game is compiled or gameplay tested.
        result = _clean_model_json(
            combined, ledger, {m.name for m in existing_modules})
        module_ids = {module.name: module.module_id for module in result["modules"]}
        result["module_world_objects"] = {
            module_ids[row["name"]]: [item["name"] for item in part.get("world_objects", [])]
            for part in accepted_parts for row in part.get("modules", [])
        }
        # Only semantic-only host-authored plans opt into the host Remote
        # gateway. Legacy full-module JSON retains its current explicit
        # source wiring so saved projects are not silently rewritten.
        host_module_names = {
            row["name"] for part in accepted_parts
            if part.get("_host_semantic") is True
            for row in part["modules"] if row.get("role") == "server"
        }
        if host_module_names:
            host_actions: dict[str, dict[str, str]] = {}
            for module in result["modules"]:
                if module.name not in host_module_names:
                    continue
                for remote in result["module_remotes"].get(module.module_id, []):
                    if remote in host_actions:
                        raise DynamicDesignError("Ambiguous host-owned Remote owner: " + remote)
                    host_actions[remote] = {
                        "service": module.name,
                        "kind": result["remotes"][remote],
                    }
            result["host_actions"] = host_actions
            host_client_actions: dict[str, dict[str, Any]] = {}
            client_names = {
                m.name for m in result["modules"]
                if m.file_path.endswith(".client.luau")
            }
            for part in accepted_parts:
                for client_name, binding in part.get(
                        "_host_client_actions", {}).items():
                    if client_name not in client_names:
                        raise DynamicDesignError(
                            "Host UI requires existing client module: " +
                            str(client_name))
                    remote = binding.get("remote")
                    if (client_name in host_client_actions
                            or remote not in host_actions
                            or binding.get("kind") != host_actions[remote]["kind"]
                            or binding.get("input_mode") != "host_button"
                            or binding.get("argument_count") != 0):
                        raise DynamicDesignError(
                            "Host UI route not backed by exact no-argument Remote")
                    # One zero-argument UI route cannot be used to reach an
                    # arbitrary server handler with fabricated payloads.
                    host_actions[remote]["max_args"] = 0
                    host_client_actions[client_name] = binding
            result["host_client_actions"] = host_client_actions
            approved_choices: dict[str, list[dict[str, str]]] = {}
            for part in accepted_parts:
                for remote_name, choices in part.get("_host_action_choices", {}).items():
                    if (remote_name in approved_choices
                            or remote_name not in host_actions
                            or host_actions[remote_name]["kind"] != "RemoteFunction"):
                        raise DynamicDesignError(
                            "Action IDs must belong to one declared host RemoteFunction")
                    approved_choices[remote_name] = choices
            result["host_action_choices"] = approved_choices
            # A Roblox ProximityPrompt already renders a cross-platform
            # object interaction. Host owns its Instance and server callback;
            # no fabricated client module or client-to-server Remote.
            host_world_actions: dict[str, dict[str, str]] = {}
            actual_world = {o["name"] for o in result["world_objects"]}
            for part in accepted_parts:
                for world_name, binding in part.get(
                        "_host_world_actions", {}).items():
                    if (world_name in host_world_actions
                            or world_name not in actual_world
                            or not isinstance(binding, dict)
                            or binding.get("service") not in host_module_names
                            or not isinstance(binding.get("action_text"), str)
                            or not binding["action_text"].strip()):
                        raise DynamicDesignError(
                            "Invalid or unowned host ProximityPrompt world action")
                    host_world_actions[world_name] = binding
            if host_world_actions:
                result["host_world_actions"] = host_world_actions
        research["architecture_assembly"] = {
            "strategy": "source_anchored_scoped_feature_contracts",
            "feature_count": len(facets),
            "module_count": len(result["modules"]),
            "remote_count": len(result["remotes"]),
            "validated": True,
            "gameplay_verified": False,
        }
        return result

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
