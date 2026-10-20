"""Limit each small-model coder call to its ONE assigned Roblox gameplay system.

The architecture may declare 20 remotes, but SpaceModeManager should not be
shown 20 unrelated interfaces and asked to implement Mining, Trading, Combat,
Colonization and the launch UI again inside its own source file.
"""
from __future__ import annotations

import re
from typing import Any


_GENERIC = frozenset({
    "client", "server", "service", "controller", "manager", "ui", "state",
    "request", "response", "result", "action", "event", "function", "handler",
    "system", "data", "get", "set", "update", "player",
})


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|\d+", value)
    return {word.lower() for word in words if len(word) >= 3 and word.lower() not in _GENERIC}


def relevant_remotes(module: Any, design: dict[str, Any]) -> dict[str, str]:
    """Prompt routing guidance only; NOT a replacement for required wiring checks.

    Prefer explicit validated module_remotes if authored by the planner. For
    older plans, use CamelCase action stems from the module NAME first,
    then its behavior only if no name match. This avoids cross-domain code.
    """
    remotes = design.get("remotes") or {}
    if not isinstance(remotes, dict):
        return {}
    names = design.get("module_remotes")
    if isinstance(names, dict) and module.module_id in names:
        selected = names[module.module_id]
        if isinstance(selected, (list, tuple)):
            return {name: remotes[name] for name in selected if name in remotes}
    module_name_tokens = _tokens(module.name)
    description = (
        str(module.description) + " " +
        str((design.get("module_behaviors") or {}).get(module.module_id, ""))
    )
    description_tokens = _tokens(description)
    result = {}
    for name, kind in remotes.items():
        stem = _tokens(name)
        # A 'ShipPartRequest' belongs to ShipBuilder, not every script that
        # happens to mention a ship in its description.
        if stem and stem & module_name_tokens:
            result[name] = kind
    if not result:
        for name, kind in remotes.items():
            stem = _tokens(name)
            if stem and stem & description_tokens:
                result[name] = kind
    return result


def relevant_world_objects(module: Any, design: dict[str, Any]) -> list[dict[str, Any]]:
    """New scoped plans carry host-authored world ownership, including empty lists.

    Legacy imported plans without this mapping retain their declared world until
    replanned; name similarity is not evidence of authoritative ownership.
    """
    world = design.get("world_objects") or []
    owners = design.get("module_world_objects")
    if isinstance(owners, dict) and module.module_id in owners:
        names = set(owners[module.module_id])
        return [item for item in world if item.get("name") in names]
    return world


def relevant_detailed_plan(module: Any, proposal: Any,
                           requirement_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project shared requirements onto the actual module responsibility.

    A source clause can have many implementation owners. Its combined outcome
    and AI steps are not per-module instructions: proposal15 assigned mining,
    trading and combat to the mode initializer this way. Preserve the approved
    plan itself and retain complete details for one service and its clients.
    """
    design = proposal.game_design.get("dynamic_design") or {}
    detail = proposal.game_design.get("detailed_implementation_plan") or {}
    contracts = []
    complete_details = set()
    for row in detail.get("required_functions", []):
        if not isinstance(row, dict) or row.get("id") not in requirement_ids:
            continue
        owners = set(row.get("owner_modules") or []) or {
            candidate.name for candidate in proposal.modules
            if row["id"] in (design.get("module_requirements") or {}).get(
                candidate.module_id, [])
        }
        files = set(row.get("owner_files") or [])
        members = [candidate for candidate in proposal.modules if candidate.name in owners]
        servers = [candidate for candidate in members if candidate.file_path.startswith("src/server/")]
        facets = {tuple(sorted((design.get("module_facets") or {}).get(
            candidate.module_id, []))) for candidate in members}
        # A server and its UI implement one mechanic together. Keep their
        # approved prerequisites and rejection cases. Multiple server owners
        # (including proposal15's eleven servers in ONE facet) remain separate
        # gameplay responsibilities, even if the source clause is the same.
        one_service = (
            len(owners) > 1 and module.name in owners and len(members) == len(owners)
            and len(servers) == 1 and len(facets) == 1
            and (not files or files == {candidate.file_path for candidate in members})
            and all(candidate in servers or candidate.file_path.endswith(".client.luau")
                    for candidate in members)
        )
        if (owners == {module.name} and (not files or files == {module.file_path})) or one_service:
            contracts.append(dict(row, owner_modules=[module.name], owner_files=[module.file_path]))
            complete_details.add(row["id"])
        else:
            contracts.append({
                "id": row["id"],
                "original_request": row.get("original_request", ""),
                "owner_modules": [module.name],
                "owner_files": [module.file_path],
                "responsibility": module.description,
                "behavior": (design.get("module_behaviors") or {}).get(
                    module.module_id, module.description),
                "scope": "shared requirement; implement only this module responsibility",
            })
    steps = {
        rid: value for rid, value in
        (detail.get("ai_planning", {}).get("requirements") or {}).items()
        if rid in complete_details
    }
    return contracts, steps
