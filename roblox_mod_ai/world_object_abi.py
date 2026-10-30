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
    # Host-compiled typed combat/mining requires the SAME exact orbit pad
    # verified through its launcher+builder+arrival chain. The previous
    # exception covered host_space_actions only, so newly compiled handlers
    # passed their own eligibility gate but failed the generated-module ABI
    # on their own legitimate arrival lookup (log 27).
    #
    # Do not loosen this to all known world names, word prefixes or any
    # model-authored action. The world target must be separately owned by this
    # module and the renderer must prove the arrival is the one in the
    # vehicle binding. The arrival is read-only placement context.
    if module is not None and getattr(module, "kind", None) == "server_module":
        from .host_verified_typed_effects import eligible_verified_effect
        match = eligible_verified_effect(module, proposal)
        if match is not None:
            effect, _remote, target, destination = match
            if (effect in ("world_damage", "world_harvest")
                    and target in authorized
                    and destination in declared):
                authorized.append(destination)
    return sorted(declared), sorted(set(authorized))


def world_lookup_guidance(proposal: Any, module: Any) -> str:
    declared, authorized = world_names(proposal, module)
    if not declared:
        return ""
    design = getattr(proposal, "game_design", {}).get("dynamic_design") or {}
    # Supply exact declared class, not just a set of names. For any action,
    # this prevents an LLM from treating a Part as a Model (or vice versa).
    classes = {
        row.get("name"): row.get("class")
        for row in design.get("world_objects", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    objects = [{"name": name, "class": classes.get(name, "Instance")}
               for name in authorized]
    return (
        "AUTHORIZED MATERIALIZED WORLD INSTANCES (exact name and class): "
        + json.dumps(objects, ensure_ascii=False) + ". "
        "Objects NOT listed here must not be accessed by this action. "
        "Only these exact workspace objects may be accessed by this action. "
        "These are NOT injected server services. Use the Roblox APIs for "
        "each declared class; a Part is not a Model. If the intended effect "
        "needs an absent actor or object, it requires a verified architectural "
        "producer, NOT an invented workspace name or an unrelated replacement. "
        "Do not treat Instance Attributes as objects or Lua tables.\\n"
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
