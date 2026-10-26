"""Genre-neutral first-interaction placement in an authored Roblox world.

Uses the project's real spawn location, object bounds, maximum interaction
distance, and clearance. No prompt phrases, genre labels, resource names or
fixed absolute coordinates determine the result. Fail closed instead of
silently placing an unreachable interaction behind dense geometry.
"""
from __future__ import annotations

import math
from typing import Any


def _vector(values: Any, *, allow_none: bool = False) -> tuple[float, float, float] | None:
    if values is None and allow_none:
        return None
    if (not isinstance(values, (tuple, list)) or len(values) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v)
                   for v in values)):
        raise ValueError("World geometry requires three finite coordinates")
    return tuple(float(v) for v in values)


def spawn_anchor(design: dict[str, Any], *, round_lobby: bool = False) -> tuple[float, float, float]:
    """Shared by Rojo serializer and host world-interaction placement."""
    dynamic = design.get("dynamic_design") or {}
    explicit = dynamic.get("spawn_position") if isinstance(dynamic, dict) else None
    if explicit is not None:
        return _vector(explicit)
    return (0.0, 1.0, 60.0 if round_lobby else 0.0)


def place_first_interaction(
    world_objects: list[dict[str, Any]],
    *,
    anchor: tuple[float, float, float],
    size: tuple[float, float, float] = (4.0, 4.0, 4.0),
    max_distance: float = 18.0,
    clearance: float = 1.0,
) -> list[float]:
    """Find an unoccupied, server-reachable center near an authored spawn.

    Candidates are relative polar offsets, not absolute game-specific spots.
    Every candidate is validated against the full planned AABB of each object.
    The upper distance bound respects the same 3D distance test as the server.
    Never accept objects from unrelated altitude bands as obstacles.
    """
    sx, sy, sz = _vector(anchor)
    dx, dy, dz = _vector(size)
    if not (1 <= max_distance <= 256 and 0 <= clearance <= 10
            and min(dx, dy, dz) > 0):
        raise ValueError("Invalid interaction range or geometry")

    # Bottom of node touches the spawn ground plane (spawn center - 1).
    cy = sy - 1.0 + dy / 2.0
    # Character's root stands higher than SpawnLocation. Stay inside range
    # with generous room for natural approach, so the button is reachable.
    vertical_gap = cy - sy
    horizontal = math.sqrt(max(0.0, max_distance**2 - vertical_gap**2))
    if horizontal <= dx / 2 + clearance:
        raise ValueError("Interaction volume exceeds server interaction range")

    bounds: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    for obj in world_objects:
        if not isinstance(obj, dict):
            raise ValueError("Malformed authored world object")
        center = _vector(obj.get("position"))
        dimensions = _vector(obj.get("size"))
        if min(dimensions) <= 0:
            raise ValueError("Invalid authored object bounds")
        bounds.append((center, dimensions))

    # Iterate rings in stable order; points cover all directions, not a
    # hardcoded row, map coordinate, game mode, resource type, or seed.
    min_radius = max(dx, dz) / 2 + 4.0
    max_radius = min(horizontal - 1.0, max_distance * 0.85)
    if min_radius > max_radius:
        raise ValueError("No reachable world-interaction radius")
    radius = min_radius
    while radius <= max_radius + 1e-6:
        samples = max(16, math.ceil(2 * math.pi * radius / 3))
        for index in range(samples):
            theta = 2 * math.pi * index / samples
            candidate = (sx + radius * math.cos(theta),
                         cy, sz + radius * math.sin(theta))
            def overlaps(position: tuple[float, float, float],
                         extent: tuple[float, float, float]) -> bool:
                # Full 3D overlap, not exact XYZ equality or a flat 7-stud
                # square. A distant spacecraft above the node is harmless.
                return all(
                    abs(candidate[axis] - position[axis])
                    < (size[axis] + extent[axis]) / 2 + clearance
                    for axis in range(3)
                )
            if not any(overlaps(pos, extent) for pos, extent in bounds):
                return [round(value, 4) for value in candidate]
        radius += 2.0
    raise ValueError(
        "No collision-free resource interaction near the real spawn; "
        "require an explicit authored location or redesign the scene"
    )
