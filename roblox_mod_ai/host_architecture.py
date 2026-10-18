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
                    "observable_result": {"type": "string"},
                    "world_entities": {"type": "array", "items": {
                        "type": "string"}},
                },
                "required": [
                    "name", "server_behavior", "client_behavior",
                    "interaction", "observable_result", "world_entities",
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
        observable = system.get("observable_result")
        world = system.get("world_entities", [])
        if not isinstance(name, str) or not name.strip():
            raise HostArchitectureError("Gameplay system needs a descriptive name")
        if not isinstance(server, str) or len(server.strip()) < 24:
            raise HostArchitectureError("Gameplay system needs concrete server behavior")
        if not isinstance(observable, str) or len(observable.strip()) < 18:
            raise HostArchitectureError("Gameplay system needs observable result")
        if re.search(r"\b(TODO|stub|placeholder|implement later)\b", server, re.I):
            raise HostArchitectureError("Unimplemented gameplay cannot pass host plan")
        if interaction not in {"none", "event", "request_response"}:
            raise HostArchitectureError("Invalid semantic interaction")
        if not isinstance(client, str) or (
                interaction != "none" and len(client.strip()) < 24):
            raise HostArchitectureError("Client interaction needs a real UI/input behavior")
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
        assigned_remotes = [remote_name] if interaction != "none" else []
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
            objects.append({
                "name": object_name, "class": "Part",
                # Deterministic grid separated from main spawn. These are
                # *starter placeholders* for the requested semantic entities,
                # not proof of a playable 3D world.
                "position": [
                    float(24 + len(objects) % 10 * 12),
                    2.0,
                    float(24 + len(objects) // 10 * 12),
                ],
                "size": [4.0, 4.0, 4.0],
            })

    acceptance = [
        {"requirement_id": rid,
         "observable_result": " ".join(results)}
        for rid in requirement_ids
    ]
    return {
        "modules": modules, "remotes": remotes,
        "world_objects": objects,
        "acceptance": acceptance,
        "acceptance_facets": [{
            "facet_id": facet_id, "observable_result": " ".join(results),
        }],
    }
