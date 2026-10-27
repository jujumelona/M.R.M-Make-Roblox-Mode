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


# The world contract creates physical Roblox Parts. A plain gameplay-state
# variable is not a Part, service or replicated Remote, irrespective of its
# model-generated name. Keep actual physical nouns such as InventoryChest,
# CurrencyMachine or TradeRequestBoard; reject names ending in a logical
# state/data role until the planner specifies an actual world object.
_LOGICAL_DATA_SUFFIX = re.compile(
    r"(?:balance|currency|inventory|wallet|state|data|request|ledger|"
    r"progress|score|level|rank)\Z", re.I,
)


def assert_physical_world_entities(world_names: list[str]) -> None:
    """Refuse to materialize logical state handles as real world geometry.

    The small model must keep state in a typed/persistent server contract
    instead of inventing workspace Parts and then referencing them as services.
    This check applies to any gameplay domain, not only trade or inventory.
    """
    for name in world_names:
        if not isinstance(name, str):
            raise ValueError("WORLD_ENTITY_NAME_INVALID")
        normalized = re.sub(r"[\s_\-]+", "", name)
        if _LOGICAL_DATA_SUFFIX.search(normalized):
            raise ValueError(
                "WORLD_ENTITY_LOGICAL_STATE_NOT_PHYSICAL: " + name
                + " is a logical datum, not a physical Roblox Instance. "
                "Describe a physical world object or use typed server state."
            )



def normalize_logical_state_references(
    raw: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Remove model-authored pseudo-Parts for numeric/logical data, not actions.

    Only the player's custom-input semantics may take this correction: logical
    variables belong to server-owned state, not Workspace. World prompts and
    explicitly physical targets are NOT silently rewritten; the host's strict
    physical-entity validator then rejects them for a scoped replan.
    """
    systems = raw.get("systems")
    if not isinstance(systems, list):
        return raw, []
    updated = []
    removed = []
    for i, system in enumerate(systems):
        if not isinstance(system, dict):
            updated.append(system)
            continue
        world = system.get("world_entities")
        contract = system.get("action_contract")
        target = contract.get("target") if isinstance(contract, dict) else None
        safe_custom = (
            system.get("input_mode", "custom") == "custom"
            and system.get("interaction") in ("event", "request_response")
            and (not isinstance(target, dict) or target.get("kind") == "none")
        )
        if not safe_custom or not isinstance(world, list):
            updated.append(system)
            continue
        accepted = []
        for name in world:
            if not isinstance(name, str) or not _LOGICAL_DATA_SUFFIX.search(
                re.sub(r"[\s_\-]+", "", name)
            ):
                accepted.append(name)
                continue
            # Natural-language UI/interaction with an object can designate
            # real world affordances. Never silently convert such a target.
            physical_text = " ".join((
                str(system.get("client_behavior") or ""),
                str(system.get("server_behavior") or ""),
            )).lower()
            phrase = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).lower()
            if (phrase in physical_text or name.lower() in physical_text) and re.search(
                r"\b(?:click\w*|touch\w*|approach\w*|interact\w*|proximity|"
                r"walk\w*|stand\w*|open\w*|raycast\w*|collision\w*|"
                r"distance|position|workspace)\b",
                physical_text,
            ):
                accepted.append(name)
                continue
            removed.append({
                "system_index": i,
                "name": name,
                "reason": "logical_state_reference_not_world_geometry",
            })
        updated.append(dict(system, world_entities=accepted))
    return (dict(raw, systems=updated) if removed else raw), removed
