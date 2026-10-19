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
