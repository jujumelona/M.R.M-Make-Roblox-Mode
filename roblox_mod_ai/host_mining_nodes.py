"""Resolve Roblox mining targets from accepted source ownership, not naming guesses.

An authored module_world_objects binding is the authoritative relation between
a mechanic and its world Part. MiningSite is as valid as OreNode when explicitly
bound. Never steal an unrelated planet mineral, enemy, or settlement object.
For older plans without ownership metadata, retain only conservative name+stem
matching. This shared resolver is used in preflight and actual Luau rendering.
"""
from __future__ import annotations

import re
from typing import Any

from .spec import RobloxModuleSpec, RobloxProposal

_MINEABLE = re.compile(
    r"(?:resource.*node|ore.*node|ore.*deposit|mining.*site|mine.*site|quarry|harvest.*node)",
    re.I,
)


def mining_world_nodes(
    proposal: RobloxProposal,
    owner: RobloxModuleSpec,
) -> list[str]:
    design: dict[str, Any] = proposal.game_design.get("dynamic_design") or {}
    objects = {
        row["name"]: row
        for row in design.get("world_objects", [])
        if isinstance(row, dict) and row.get("class") == "Part"
        and isinstance(row.get("name"), str)
    }
    owners = design.get("module_world_objects") or {}
    linked = owners.get(owner.module_id) if isinstance(owners, dict) else None
    world_routes = design.get("host_world_actions") or {}

    def usable(name: str) -> bool:
        if not _MINEABLE.search(name):
            return False
        binding = world_routes.get(name)
        # An object with a source-owned action belongs to that service.
        return not (isinstance(binding, dict)
                    and binding.get("service") != owner.name)

    if isinstance(linked, list) and linked:
        # Never silently widen a source-owned list with unrelated world Parts.
        return sorted({name for name in linked
                       if isinstance(name, str) and name in objects
                       and usable(name)})
    if isinstance(linked, list) and not linked:
        # No explicit world target. The preflight may create a new node.
        # Do not search other mechanics' objects.
        return []

    # Compatibility for older plans that omitted module_world_objects.
    # Multiple ambiguous candidates never cross service boundaries.
    candidates = [name for name in objects if usable(name)]
    stems = re.findall(r"\d{5,}", owner.name)
    related = [name for name in candidates
               if any(stem in name for stem in stems)]
    if related:
        return sorted(related)
    if len(candidates) == 1:
        return candidates
    return []
