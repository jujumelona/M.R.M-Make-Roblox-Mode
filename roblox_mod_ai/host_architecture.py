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


class HostArchitectureError(ValueError):
    pass


# A deliberately compact schema for GGUF JSON-constrained output: a new game
# system is a behavior, NOT a pre-generated Roblox project.
SEMANTIC_FACET_SCHEMA = {
    "type": "object",
    "properties": {
        "systems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "server_behavior": {"type": "string"},
                    "client_behavior": {"type": "string"},
                    "interaction": {"type": "string", "enum": [
                        "none", "event", "request_response"]},
                    "input_mode": {"type": "string", "enum": [
                        "custom", "host_button", "world_prompt"]},
                    "observable_result": {"type": "string"},
                    "world_entities": {"type": "array", "items": {
                        "type": "string"}},
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
    r"\\b(?:adds?|added|appl(?:y|ies|ied)|awards?|grants?|gains?|"
    r"updates?|updated|changes?|changed|sets?|saves?|stores?|records?|"
    r"deducts?|deducted|decrements?|increments?|consumes?|converts?|"
    r"spawns?|creates?|removes?|destroys?|teleports?|unlocks?|"
    r"deals?|damages?|heals?|equips?|rewards?|depletes?)\\b", re.I,
)
_VISIBLE_FEEDBACK = re.compile(
    r"\\b(?:shows?|displays?|updates?|reflects?|sees?|receives?|"
    r"notifies?|appears?|renders?|visible|feedback)\\b", re.I,
)
_POST_ACTION = re.compile(
    r"\\b(?:after|then|on success|successfully|confirmed|success|"
    r"result|received|earned|reward|gain|updated|changes?|"
    r"rejected|completion|complete|status|notification|progress)\\b", re.I,
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
    # This remains a *planned* outcome, not a claim of executed gameplay.
    return client.strip()


def expand_semantic_facet(
    raw: dict[str, Any], *, facet_id: str, requirement_ids: list[str],
    source_requirements: list[dict[str, Any]],
    reserved_modules: set[str], reserved_remotes: set[str],
    reserved_objects: set[str],
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
    results: list[str] = []
    used_modules = set(reserved_modules)
    used_remotes = set(reserved_remotes)
    used_objects = set(reserved_objects)
    seed = hashlib.sha256(facet_id.encode("utf-8")).hexdigest()[:6].upper()
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
        if not isinstance(name, str) or not name.strip():
            raise HostArchitectureError("Gameplay system needs a descriptive name")
        if not isinstance(server, str) or len(server.strip()) < 24:
            raise HostArchitectureError("Gameplay system needs concrete server behavior")
        if not isinstance(observable, str) or len(observable.strip()) < 18:
            raise HostArchitectureError("Gameplay system needs observable result")
        if re.search(r"\b(TODO|stub|placeholder|implement later)\b", server, re.I):
            raise HostArchitectureError("Unimplemented gameplay cannot pass host plan")
        if input_mode not in {"custom", "host_button", "world_prompt"}:
            raise HostArchitectureError("Unknown input mode")
        if input_mode == "world_prompt" and interaction != "event":
            raise HostArchitectureError(
                "ProximityPrompt is a one-way world interaction, not a response Remote")
        if input_mode == "host_button" and interaction == "none":
            raise HostArchitectureError("Server-only behavior cannot have a button")
        if interaction not in {"none", "event", "request_response"}:
            raise HostArchitectureError("Invalid semantic interaction")
        if not isinstance(client, str) or (
                interaction != "none" and len(client.strip()) < 24):
            raise HostArchitectureError("Client interaction needs a real UI/input behavior")
        if input_mode == "world_prompt" and len(world) != 1:
            raise HostArchitectureError(
                "Host world prompt must attach to exactly one semantic world Part")
        if input_mode == "host_button" and world:
            # Clicking a generic button with zero arguments must not
            # masquerade as choosing a mineable node or combat target.
            raise HostArchitectureError(
                "Host button is for zero-argument global actions only; "
                "targeted world interactions need custom input")
        if not isinstance(world, list) or any(
            not isinstance(item, str) or not item.strip() for item in world
        ):
            raise HostArchitectureError("world_entities must be short names, not geometry")

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
                "behavior": client.strip(),
                "uses_remotes": list(assigned_remotes),
            })
            remotes.append({
                "name": remote_name,
                "type": ("RemoteEvent" if interaction == "event"
                         else "RemoteFunction"),
            })
        results.append(observable.strip())
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

    acceptance = [
        {"requirement_id": rid,
         "observable_result": " ".join(results)}
        for rid in requirement_ids
    ]
    return {
        "_host_world_actions": host_world_actions,
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
