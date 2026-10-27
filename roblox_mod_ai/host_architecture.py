"""Host-owned Roblox project architecture from small-model GAMEPLAY semantics.

The small model supplies ONLY game-specific mechanics. It never chooses source
IDs, Instance storage, Script roles, remote names/classes, files, coordinate
arrays or per-module ownership maps. Those are derived deterministically by
the host, then rechecked with the existing full source-ledger validator.

Official Roblox foundation: ServerScriptService is private, ReplicatedStorage
hosts client/server remotes; the server is the authority for client actions.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .semantic_preservation import source_intent_conflicts, source_outcome_conflicts
from .typed_action_contract import validate_contract, TypedActionContractError


class HostArchitectureError(ValueError):
    pass


# A deliberately compact schema for GGUF JSON-constrained output: a new game
# system is a behavior, NOT a pre-generated Roblox project.
SEMANTIC_FACET_SCHEMA = {
    "type": "object",
    "properties": {
        "systems": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "server_behavior": {"type": "string", "maxLength": 4096},
                    "client_behavior": {"type": "string", "maxLength": 4096},
                    "interaction": {"type": "string", "enum": [
                        "none", "event", "request_response"]},
                    "input_mode": {"type": "string", "enum": [
                        "custom", "host_button", "world_prompt"]},
                    "observable_result": {"type": "string", "maxLength": 4096},
                    "world_entities": {"type": "array", "items": {
                        "type": "string"}},
                    "action_choices": {"type": "array", "items": {
                        "type": "object", "properties": {
                            "id": {"type": "string"}, "label": {"type": "string"},
                        }, "required": ["id", "label"]}},
                },
                "required": [
                    "name", "server_behavior", "client_behavior",
                    "interaction", "world_entities",
                ],
            },
        },
    },
    "required": ["systems"],
}



# Production-local GGUF planner output. A gameplay author must not be asked to
# choose RemoteEvent/RemoteFunction/client_behavior: these have no meaning as
# source-level game mechanics. The host derives the transport AFTER source
# semantics and emits the UI. This schema deliberately has NO transport keys.
HOST_OWNED_SEMANTIC_FACET_SCHEMA = {
    "type": "object",
    "properties": {
        "systems": {"type": "array", "maxItems": 3, "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 120},
                # A source-level trigger is legitimate gameplay semantics.
                # The host still owns Roblox client/server routing.
                "autonomous": {"type": "boolean"},
                "server_behavior": {"type": "string", "maxLength": 4096},
                "observable_result": {"type": "string", "maxLength": 4096},
                "world_entities": {
                    "type": "array", "maxItems": 24,
                    "items": {"type": "string", "maxLength": 64},
                },
                # UI choices are derived or validated by the host from
                # source-controlled context, not invented by the 9B planner.
                # Never expose this unstable optional nested JSON format.
            },
            "required": [
                "name", "server_behavior", "observable_result",
                "world_entities",
            ],
        }},
    },
    "required": ["systems"],
}


def _pascal(value: str, fallback: str) -> str:
    # Suffix is always host-generated to avoid collisions across seven facets.
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", value)
    base = "".join(w[:1].upper() + w[1:] for w in words)
    if not base or not base[0].isalpha():
        base = fallback
    base = base[:31]
    if not base[0].isupper():
        base = base[0].upper() + base[1:]
    return base


# Some local GGUF structured-output providers omit one optional descriptive
# field even when the remaining gameplay semantics are complete. Recover only
# an omitted acceptance label from *model-authored* state changes and visible
# feedback. Never invent gameplay rules or waive an explicitly bad label.
_STATE_CHANGE = re.compile(
    r"\b(?:adds?|added|appl(?:y|ies|ied|ying)|awards?|grants?|gains?|"
    r"updates?|updated|changes?|changed|sets?|saves?|stores?|records?|"
    r"deducts?|deducted|decrements?|increments?|consumes?|converts?|"
    r"persists?|persisted|transfers?|transferred|settles?|settled|"
    r"spawns?|creates?|removes?|destroys?|teleports?|unlocks?|"
    r"deals?|damages?|heals?|equips?|rewards?|depletes?)\b", re.I,
)
_VISIBLE_FEEDBACK = re.compile(
    r"\b(?:shows?|displays?|updates?|reflects?|sees?|receives?|"
    r"notifies?|appears?|renders?|visible|feedback)\b", re.I,
)
_POST_ACTION = re.compile(
    r"\b(?:after|then|on success|successfully|confirmed|success|"
    r"result(?:s|ing)?|confirmations?|received|earned|reward|gain|updated|changes?|"
    r"rejected|completion|complete|status|notification|progress|feedback)\b", re.I,
)


def _recover_observable_result(server: Any, client: Any, interaction: Any) -> str | None:
    if interaction not in {"event", "request_response"}:
        return None
    if not isinstance(server, str) or not isinstance(client, str):
        return None
    if len(server.strip()) < 24 or len(client.strip()) < 24:
        return None
    if not (_STATE_CHANGE.search(server) and _VISIBLE_FEEDBACK.search(client)
            and _POST_ACTION.search(client)):
        return None
    # Do not promote a client explicitly reporting the absence of results.
    if re.search(
        r"\b(?:no|without|never)\s+(?:(?:visible|gameplay|server)\s+)?"
        r"(?:result|outcome|feedback|confirmation)\b", client, re.I
    ) or re.search(
        r"\bwithout\s+(?:\w+\s+){0,3}(?:showing|displaying|rendering)"
        r"\s+(?:any\s+)?(?:result|outcome|feedback)\b", client, re.I
    ):
        return None
    # This remains a *planned* outcome, not a claim of executed gameplay.
    return client.strip()


# Gameplay that requires a player's decision cannot be reachable only from
# Service.start(). A role='server' module with interaction='none' has no
# Remote or ProximityPrompt connected by the host.
_PLAYER_ACTION_INTENT = re.compile(
    r"\b(?:min(?:e|ing)|harvest(?:s|ing)?|trading?|trade|purchase|buy|sell|"
    r"upgrad(?:es?|ed|ing)|launch|travel|teleport|combat|fight|attack|"
    r"coloniz(?:e|ation)|craft|build|gather|collect|equip|reward|"
    r"exchange|ship\s+part)\b|(?:선택|채굴|거래|구매|업그레이드|우주선|전투|식민|발사)",
    re.I,
)
_EXPLICIT_AUTONOMOUS_TRIGGER = re.compile(
    r"\b(?:automatically|periodically|scheduled|server[- ]driven|"
    r"without player input|on playeradded|playeradded|on spawn|"
    r"on a timer|every \d+ seconds|background simulation)\b",
    re.I,
)



def requires_player_ingress(name: str, server_behavior: str) -> bool:
    """Whether this mechanic requires an actual host-wired player trigger.

    Passive server simulations are exempt only when the architecture
    explicitly describes an autonomous trigger. This is an early reachability
    check, not proof that a routed game action behaves correctly.
    """
    return bool(_PLAYER_ACTION_INTENT.search(name + " " + server_behavior)
                and not _EXPLICIT_AUTONOMOUS_TRIGGER.search(server_behavior))




def _repeats_empty_claims(prose: str) -> bool:
    """Reject repetitive boilerplate, not legitimate long server contracts."""
    sentences = [
        re.sub(r"\s+", " ", item).strip().casefold()
        for item in re.split(r"[.!?;\n]+", prose)
        if len(item.strip()) >= 45
    ]
    counts: dict[str, int] = {}
    for sentence in sentences:
        counts[sentence] = counts.get(sentence, 0) + 1
        if counts[sentence] >= 4:
            return True
    return False

def expand_semantic_facet(
    raw: dict[str, Any], *, facet_id: str, requirement_ids: list[str],
    source_requirements: list[dict[str, Any]],
    reserved_modules: set[str], reserved_remotes: set[str],
    reserved_objects: set[str],
    max_systems: int = 3,
) -> dict[str, Any]:
    """Convert a semantic-only LLM output to the strict legacy contract.

    Reject bad/missing *gameplay* instead of inventing mechanics. Fixed names,
    roles, remote types, geometry and coverage IDs are host responsibility.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("systems"), list):
        raise HostArchitectureError("Model must supply a systems array")
    systems = raw["systems"]
    if not systems:
        raise HostArchitectureError("No game-specific systems proposed")
    if not 1 <= max_systems <= 6:
        raise HostArchitectureError("Invalid host-owned scoped action bound")
    if len(systems) > max_systems:
        raise HostArchitectureError(
            "SCOPED_FEATURE_TOO_LARGE: source-owned action count exceeds "
            "the approved scoped capacity"
        )
    if not requirement_ids or any(
        not isinstance(rid, str) or not rid for rid in requirement_ids
    ):
        raise HostArchitectureError("Host source requirements missing")
    covered = {r.get("id") for r in source_requirements
               if isinstance(r, dict)}
    if not set(requirement_ids) <= covered:
        raise HostArchitectureError("Unattributed original requirements")

    modules: list[dict[str, Any]] = []
    remotes: list[dict[str, str]] = []
    objects: list[dict[str, Any]] = []
    host_world_actions: dict[str, dict[str, str]] = {}
    host_action_choices: dict[str, list[dict[str, str]]] = {}
    host_typed_actions: dict[str, dict[str, Any]] = {}
    host_executable_actions: dict[str, dict[str, Any]] = {}
    results: list[str] = []
    used_modules = set(reserved_modules)
    used_remotes = set(reserved_remotes)
    used_objects = set(reserved_objects)
    seed = hashlib.sha256(facet_id.encode("utf-8")).hexdigest()[:6].upper()
    seen_behaviors: set[tuple[Any, ...]] = set()
    for index, system in enumerate(systems):
        if not isinstance(system, dict):
            raise HostArchitectureError("Invalid gameplay system")
        server = system.get("server_behavior")
        client = system.get("client_behavior")
        name = system.get("name")
        interaction = system.get("interaction")
        input_mode = system.get("input_mode", "custom")
        observable = system.get("observable_result")
        if "observable_result" not in system:
            observable = _recover_observable_result(server, client, interaction)
        world = system.get("world_entities", [])
        # Some constrained-output model providers use name-only objects even
        # when the requested JSON schema says strings. Normalize only this
        # representation. Geometry, Roblox class, IDs and transforms are NEVER
        # trusted as game-specific model input.
        if not isinstance(world, list) or len(world) > 24:
            raise HostArchitectureError("world_entities must be a short names array")
        clean_world = []
        for entity in world:
            if isinstance(entity, dict) and set(entity) == {"name"}:
                entity = entity["name"]
            if (not isinstance(entity, str) or not entity.strip()
                    or len(entity.strip()) > 64
                    or not re.fullmatch(r"[\w][\w -]*",
                                        entity.strip(), flags=re.UNICODE)):
                raise HostArchitectureError(
                    "world_entities must be short names, not geometry")
            clean_world.append(entity.strip())
        world = clean_world
        from .semantic_world_entities import assert_physical_world_entities
        try:
            assert_physical_world_entities(world)
        except ValueError as exc:
            raise HostArchitectureError(str(exc)) from exc
        typed_contract = system.get("action_contract")
        if typed_contract is not None:
            if interaction not in {"event", "request_response"} or input_mode != "custom":
                raise HostArchitectureError("Typed action contract requires custom player input")
            try:
                typed_contract = validate_contract(
                    typed_contract, world_entities=world,
                    transport_only=system.get("host_standard_transport") is True,
                )
            except TypedActionContractError as exc:
                raise HostArchitectureError("INVALID_TYPED_ACTION_CONTRACT: " + str(exc)) from exc
        executable = system.get("effect_program")
        if executable is not None:
            if (not isinstance(executable, dict)
                    or executable.get("schema") not in (
                        "rmm/atomic-effect-v1", "rmm/transaction-effect-v1")
                    or typed_contract is None
                    or system.get("host_standard_transport") is True
                    or typed_contract["target"]["kind"] != "none"
                    or interaction != "request_response"):
                raise HostArchitectureError(
                    "EXECUTION_PROGRAM_REQUIRES_TYPED_STATE_CONTRACT")
            if executable["schema"] == "rmm/transaction-effect-v1":
                rows = executable.get("changes")
                if (set(executable) != {"schema", "namespace", "changes"}
                        or not isinstance(rows, list)
                        or not 1 <= len(rows) <= 5
                        or len(rows) != len(typed_contract["state_changes"])):
                    raise HostArchitectureError("EXECUTION_PROGRAM_INVALID_TRANSACTION")
            else:
                if (set(executable) != {"schema", "namespace", "field",
                                       "operation", "amount", "limit"}
                        or len(typed_contract["state_changes"]) != 1):
                    raise HostArchitectureError("EXECUTION_PROGRAM_INVALID_ATOMIC_EFFECT")
        choices = system.get("action_choices", [])
        if (not isinstance(choices, list) or len(choices) > 12
                or any(not isinstance(item, dict)
                       or not isinstance(item.get("id"), str)
                       or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", item["id"])
                       or not isinstance(item.get("label"), str)
                       or not (1 <= len(item["label"].strip()) <= 70)
                       for item in choices)
                or len({item["id"] for item in choices}) != len(choices)):
            raise HostArchitectureError("Action choices must be unique stable IDs with labels")
        if typed_contract is not None and choices:
            raise HostArchitectureError(
                "Typed action inputs and legacy action choices cannot coexist")
        if choices and not (interaction == "request_response" and input_mode == "custom"):
            raise HostArchitectureError("Selectable actions require a custom request_response ingress")
        if not isinstance(name, str) or not name.strip():
            raise HostArchitectureError("Gameplay system needs a descriptive name")
        if not isinstance(server, str) or len(server.strip()) < 24:
            raise HostArchitectureError("Gameplay system needs concrete server behavior")
        # Number of prose characters is not the number of gameplay actions.
        # Real server-side atomicity, ownership and rollback rules can require
        # >1000 characters; rejecting at 550 caused identical model retries.
        # Bound only pathologically large responses and repeated filler.
        if len(server) > 4096 or _repeats_empty_claims(server):
            raise HostArchitectureError(
                "SCOPED_FEATURE_TOO_LARGE: repetitive or unbounded server "
                "description; specify one concrete source-owned transition"
            )
        if not isinstance(observable, str) or len(observable.strip()) < 18:
            raise HostArchitectureError("Gameplay system needs observable result")
        if len(observable) > 4096 or _repeats_empty_claims(observable):
            raise HostArchitectureError(
                "SCOPED_FEATURE_TOO_LARGE: repeated or unbounded acceptance"
            )
        if re.search(r"\b(TODO|stub|placeholder|implement later)\b", server, re.I):
            raise HostArchitectureError("Unimplemented gameplay cannot pass host plan")
        # Never accept an explicit server-authority bypass merely because
        # the same behavior also promises a visible client result. A real
        # uploaded combat proposal said the server can apply attack results
        # "without validating" even though the preceding sentence claimed
        # to validate the target. Reject the contradiction at plan time.
        if re.search(
            r"\b(?:without\s+(?:\w+\s+){0,4}validat(?:ing|ion)|"
            r"(?:skip|skips|bypass|bypasses)\s+(?:\w+\s+){0,3}"
            r"(?:validat(?:ion|ing)|checks?|verification)|"
            r"(?:does\s+not|doesn't|never)\s+validat(?:e|es))\b",
            server, re.I,
        ):
            raise HostArchitectureError(
                "Server behavior explicitly bypasses action validation")
        if input_mode not in {"custom", "host_button", "world_prompt"}:
            raise HostArchitectureError("Unknown input mode")
        if input_mode == "world_prompt" and interaction != "event":
            raise HostArchitectureError(
                "ProximityPrompt is a one-way world interaction, not a response Remote")
        if input_mode == "host_button" and interaction == "none":
            raise HostArchitectureError("Server-only behavior cannot have a button")
        if interaction not in {"none", "event", "request_response"}:
            raise HostArchitectureError("Invalid semantic interaction")
        # world_prompt and host_button are constructed and wired by the
        # host itself. They deliberately need no model-authored LocalScript;
        # only custom player-driven ingress needs a real client UI contract.
        # Requiring client_behavior for a world_prompt caused a valid server
        # resource node action to be rejected in production plan-55.
        if not isinstance(client, str) or (
                interaction != "none" and input_mode == "custom"
                and len(client.strip()) < 24):
            raise HostArchitectureError("Client interaction needs a real UI/input behavior")
        if len(client) > 4096 or _repeats_empty_claims(client):
            raise HostArchitectureError(
                "SCOPED_FEATURE_TOO_LARGE: repeated or unbounded client description"
            )
        if input_mode == "world_prompt" and len(world) != 1:
            raise HostArchitectureError(
                "Host world prompt must attach to exactly one semantic world Part")
        if input_mode == "host_button" and world:
            # Clicking a generic button with zero arguments must not
            # masquerade as choosing a mineable node or combat target.
            raise HostArchitectureError(
                "Host button is for zero-argument global actions only; "
                "targeted world interactions need custom input")
        # Do not silently write an unreachable server-only module for a
        # player-driven mechanic. The host can wire a Remote or world prompt,
        # but interaction='none' explicitly tells it to wire neither.
        if interaction == "none" and requires_player_ingress(name, server):
            raise HostArchitectureError(
                "Player-driven gameplay has interaction=none and no host input "
                "route. Specify event/request_response with an appropriate "
                "client action, or event + world_prompt for a world Part. "
                "Only genuinely autonomous server systems may use none.")

        # A small planner can propose the identical action under several
        # different names. Do not create two server writers/Remotes for one
        # literal gameplay transition. Different targets or outcomes remain
        # distinct; this is exact semantic deduplication, not keyword reuse.
        behavior_signature = (
            server.strip(), client.strip(), interaction, input_mode,
            tuple(world), observable.strip(),
            repr(typed_contract),
        )
        if behavior_signature in seen_behaviors:
            continue
        seen_behaviors.add(behavior_signature)

        prefix = _pascal(name, "Gameplay")
        suffix = seed + str(index + 1)
        root = (prefix[:25] + suffix)
        server_name = root + "Server"
        client_name = root + "Client"
        remote_name = root + "Action"
        assigned_remotes = [remote_name] if interaction != "none" and input_mode != "world_prompt" else []
        module_names = [server_name] + ([client_name] if assigned_remotes else [])
        if used_modules.intersection(module_names):
            raise HostArchitectureError("Generated module name collision")
        if assigned_remotes and remote_name in used_remotes:
            raise HostArchitectureError("Generated Remote name collision")
        used_modules.update(module_names)
        used_remotes.update(assigned_remotes)
        modules.append({
            "name": server_name, "role": "server",
            "requirement_ids": list(requirement_ids),
            "facet_ids": [facet_id],
            "behavior": server.strip(),
            "uses_remotes": list(assigned_remotes),
        })
        if assigned_remotes:
            modules.append({
                "name": client_name, "role": "client",
                "requirement_ids": list(requirement_ids),
                "facet_ids": [facet_id],
                # A button's client controller is host-generated: the model
                # need not invent a separate UI. Preserve any real description,
                # but never feed an empty module contract into the Luau coder.
                "behavior": (client.strip() or (
                    "Host-generated button for " + name.strip() +
                    " invokes the corresponding server action and displays "
                    "the server-confirmed result to the player."
                )) if input_mode == "host_button" else client.strip(),
                "uses_remotes": list(assigned_remotes),
            })
            remotes.append({
                "name": remote_name,
                "type": ("RemoteEvent" if interaction == "event"
                         else "RemoteFunction"),
            })
        results.append(observable.strip())
        if typed_contract is not None:
            if not assigned_remotes or len(assigned_remotes) != 1:
                raise HostArchitectureError(
                    "Typed action requires exactly one routed Remote")
            target = typed_contract["target"]
            resolved_world = None
            if target["kind"] == "world_entity":
                index_of_target = world.index(target["name"])
                stem = _pascal(target["name"], "WorldObject")
                resolved_world = (
                    stem[:23] + suffix + str(index_of_target + 1))
            if executable is not None:
                host_executable_actions[remote_name] = executable
            host_typed_actions[remote_name] = {
                "contract": typed_contract,
                "server": server_name, "client": client_name,
                "world_entities": list(world),
                "world_name": resolved_world,
                "transport_only": system.get("host_standard_transport") is True,
            }
        if choices and assigned_remotes:
            host_action_choices[remote_name] = [
                {"id": item["id"], "label": item["label"].strip()}
                for item in choices
            ]
        for entity_index, entity in enumerate(world):
            # Model chooses WHICH world objects gameplay needs, but NEVER
            # Roblox classes, Transform coordinates, sizes, or trusted IDs.
            stem = _pascal(entity, "WorldObject")
            object_name = (stem[:23] + suffix + str(entity_index + 1))
            if object_name in used_objects:
                raise HostArchitectureError("World entity name collision")
            used_objects.add(object_name)
            # Global placement slot includes already accepted facets, so
            # separate semantic systems do not spawn Parts on top of each other.
            slot = len(used_objects) - 1
            if input_mode == "world_prompt":
                host_world_actions[object_name] = {
                    "service": server_name, "action_text": name.strip()[:44],
                }
            objects.append({
                "name": object_name, "class": "Part",
                # Deterministic starter geometry only; game-specific authored
                # world shapes still require generation and Studio inspection.
                "position": [
                    float(24 + slot % 17 * 12),
                    2.0,
                    float(24 + slot // 17 * 12),
                ],
                "size": [4.0, 4.0, 4.0],
            })

    # The model only authors gameplay semantics, but must preserve each
    # source-anchored objective before the host commits source IDs/remotes.
    # Rejecting here makes the facet planner retry this small JSON unit, rather
    # than allowing a wrong PvP/settlement plan to burn minutes of Luau codegen.
    combined_server = " ".join(
        m["behavior"] for m in modules if m["role"] == "server"
    )
    combined_outcome = " ".join(results)
    for source in source_requirements:
        if not isinstance(source, dict):
            continue
        # Server implementation and observable acceptance are independent
        # contracts. A client saying "colony established" must never mask a
        # server that only validates a menu click; likewise a genuine NPC
        # server cannot excuse a PvP-only acceptance description.
        for layer, owned_text in (
            ("server", combined_server), ("outcome", combined_outcome)
        ):
            issues = (
                source_intent_conflicts(source.get("statement", ""), owned_text)
                if layer == "server" else
                source_outcome_conflicts(source.get("statement", ""), owned_text)
            )
            if issues:
                raise HostArchitectureError(
                    "SEMANTIC_SOURCE_CONTRACT " + layer + ": " +
                    "; ".join(issues)
                )

    acceptance = [
        {"requirement_id": rid,
         "observable_result": " ".join(results)}
        for rid in requirement_ids
    ]
    return {
        "_host_world_actions": host_world_actions,
        "_host_action_choices": host_action_choices,
        "_host_typed_actions": host_typed_actions,
        "_host_executable_actions": host_executable_actions,
        "_host_client_actions": {
            modules_row["name"]: {
                "remote": modules_row["uses_remotes"][0],
                "label": system["name"][:44],
                "kind": ("RemoteEvent" if system["interaction"] == "event"
                         else "RemoteFunction"),
                "input_mode": "host_button",
                "argument_count": 0,
            }
            for system_index, system in enumerate(systems)
            if system.get("input_mode", "custom") == "host_button"
            for modules_row in modules
            if (modules_row["role"] == "client"
                and modules_row["name"].endswith(
                    hashlib.sha256(facet_id.encode("utf-8")).hexdigest()[:6].upper()
                    + str(system_index + 1) + "Client"))
        },
        "modules": modules, "remotes": remotes,
        "world_objects": objects,
        "acceptance": acceptance,
        "acceptance_facets": [{
            "facet_id": facet_id, "observable_result": " ".join(results),
        }],
    }
