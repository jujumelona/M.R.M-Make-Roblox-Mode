"""Host-owned real Roblox world names for model source and checkpoint review.

The planner assigns concrete Part names when it materializes the world.
Generated code MUST NOT guess a different workspace:FindFirstChild literal
and receive nil at runtime. A dynamic object explicitly constructed in the
same script is exempt, as are runtime properties and non-workspace lookups.
"""
from __future__ import annotations

import json
import re
from typing import Any
from .dynamic_wiring import _mask_strings, _without_comments

_LOOKUP = re.compile(
    r"\bworkspace\s*:\s*(?:FindFirstChild|WaitForChild)\s*\(\s*"
    r"(['\"])([^'\"\n]+)\1"
)
_NAME_ASSIGNED = re.compile(
    r"\b[A-Za-z_]\w*\.Name\s*=\s*(['\"])([^'\"\n]+)\1"
)


def world_names(proposal: Any, module: Any = None) -> tuple[list[str], list[str]]:
    design = getattr(proposal, "game_design", {}).get("dynamic_design") or {}
    declared = {
        obj.get("name") for obj in design.get("world_objects", [])
        if isinstance(obj, dict) and isinstance(obj.get("name"), str)
    }
    authorized = []
    if module is not None:
        authorized = [
            name for name in (
                design.get("module_world_objects") or {}
            ).get(getattr(module, "module_id", ""), [])
            if name in declared
        ]
    # An arrival pad is owned/materialized by the launch module, not by the
    # planet actions. Grant exact read-only target lookup to a VERIFIED
    # host-owned space handler; never add it to arbitrary model code.
    # The handler must have the same source-bound builder/launch/arrival
    # binding and its own planet target must be in its module manifest.
    if module is not None and getattr(module, "kind", None) == "server_module":
        name = getattr(module, "name", "")
        if name.startswith(("AlienCombat", "MarkPlanetColonized",
                            "ExtractOtherPlanetMineral")):
            from .host_space_actions import (
                RULES, _role, render_host_space_action,
            )
            role = _role(module)
            if role in RULES and render_host_space_action(module, proposal) is not None:
                linked_prefix = RULES[role][2]
                if any(obj_name.startswith(linked_prefix) for obj_name in authorized):
                    bindings = design.get("host_vehicle_identity_bindings") or []
                    arrivals = design.get("host_arrival_materializations") or []
                    if len(bindings) == 1:
                        binding = bindings[0]
                        valid = [
                            row.get("arrival") for row in arrivals
                            if isinstance(row, dict)
                            and row.get("server") == binding.get("server")
                            and row.get("builder") == binding.get("builder")
                            and row.get("arrival") in declared
                        ]
                        if len(valid) == 1:
                            authorized.append(valid[0])
    return sorted(declared), sorted(set(authorized))


def world_lookup_guidance(proposal: Any, module: Any) -> str:
    declared, authorized = world_names(proposal, module)
    if not declared:
        return ""
    # A prompt containing EVERY object in the game encouraged the 9B coder
    # to mutate sellers, NPCs and destination planets in an unrelated action.
    # Show only this module's independently authored and linked world targets.
    return (
        "ACTUAL MATERIALIZED WORLD ABI: ONLY the following objects are "
        "linked to this action: " +
        json.dumps(authorized, ensure_ascii=False) + ". "
        "These names are Part/Model instances in workspace, NEVER entries "
        "in the injected services table. Objects NOT listed here must not "
        "be accessed or mutated by this action. Use their exact case. "
        "Never guess "
        "workspace:FindFirstChild('Spaceship') or a thematic name "
        "that is NOT in the declared list; such a lookup returns nil. "
        "Do not treat Instance Attributes as objects or Lua tables.\n"
    )


def world_lookup_errors(code: str, proposal: Any,
                        module: Any = None) -> list[str]:
    declared, authorized = world_names(proposal, module)
    if not declared or not isinstance(code, str) or not code:
        return []
    source = _without_comments(code)
    masked = _mask_strings(source)
    constructed = {
        match.group(2) for match in _NAME_ASSIGNED.finditer(source)
        if re.match(r"[A-Za-z_]\w*\.Name\b", masked[match.start():])
    }
    errors: list[str] = []
    seen = set()
    for match in _LOOKUP.finditer(source):
        if masked[match.start():match.start()+9] != "workspace":
            continue
        name = match.group(2)
        if name in constructed or name in seen:
            continue
        if name in declared and (module is None or name in authorized):
            continue
        seen.add(name)
        errors.append(
            "WORLD_OBJECT_NAME_UNDECLARED: workspace lookup " + repr(name) +
            " is not present in the action's authorized materialized world "
            "targets; allowed names: " +
            ", ".join((authorized if module is not None else declared)[:30])
        )
    return errors
