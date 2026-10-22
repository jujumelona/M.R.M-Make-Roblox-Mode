"""Normalize planner world references without accepting authored engine geometry.

The host owns Instances, physics, coordinates and class metadata. A small LLM
occasionally emits a named object with arbitrary commentary rather than a bare
name. Retain ONLY an explicitly valid name. Never import arbitrary dict fields
as executable mechanics, geometry, class names, or state mutations.
"""
from __future__ import annotations

import re
from typing import Any


_FORBIDDEN_ENGINE_FIELDS = frozenset({
    "position", "size", "cframe", "orientation", "rotation", "transform",
    "geometry", "mesh", "class", "class_name", "instance", "asset_id",
    "coordinates", "pivot", "velocity", "anchored", "parent",
})


def normalize_world_names(raw: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """Make named references usable; leave invalid identities for host rejection.

    Returns a copy and a list of normalized (system index, entity index).
    An explicitly supplied geometry/Class is NEVER silently accepted.
    """
    systems = raw.get("systems")
    if not isinstance(systems, list):
        return raw, []
    updated = []
    normalized: list[tuple[int, int]] = []
    for i, system in enumerate(systems):
        if not isinstance(system, dict) or not isinstance(system.get("world_entities"), list):
            updated.append(system)
            continue
        world = list(system["world_entities"])
        for j, entry in enumerate(world):
            if not isinstance(entry, dict):
                continue
            if set(str(k).casefold() for k in entry) & _FORBIDDEN_ENGINE_FIELDS:
                continue
            name = entry.get("name")
            if (isinstance(name, str) and 0 < len(name.strip()) <= 64
                    and re.fullmatch(r"[\w][\w -]*", name.strip(), re.UNICODE)):
                world[j] = name.strip()
                normalized.append((i, j))
        updated.append(dict(system, world_entities=world))
    return (dict(raw, systems=updated) if normalized else raw), normalized
