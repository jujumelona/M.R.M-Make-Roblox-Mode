"""Genre-independent validation of model-authored interaction metadata.

The author describes gameplay; the host owns Roblox ingress, remotes and
input routing. Reinterpret only an UNAMBIGUOUS exchange of two disjoint enum
domains. Ambiguous routing (e.g. button with world targets) must be returned
as a scoped correction request, not silently promoted to working gameplay.
"""
from __future__ import annotations

from typing import Any

INTERACTIONS = frozenset(("none", "event", "request_response"))
INPUT_MODES = frozenset(("custom", "host_button", "world_prompt"))


def canonicalize_interaction_fields(raw: dict[str, Any]) -> tuple[dict[str, Any], list[int]]:
    """Swap two obviously inverted enum values; leave semantics untouched."""
    systems = raw.get("systems")
    if not isinstance(systems, list):
        return raw, []
    changed: list[int] = []
    normalized: list[Any] = []
    for index, row in enumerate(systems):
        if not isinstance(row, dict):
            normalized.append(row)
            continue
        interaction, mode = row.get("interaction"), row.get("input_mode", "custom")
        if interaction in INPUT_MODES and mode in INTERACTIONS:
            row = dict(row, interaction=mode, input_mode=interaction)
            changed.append(index)
        normalized.append(row)
    return (dict(raw, systems=normalized) if changed else raw), changed


def interaction_issues(raw: dict[str, Any]) -> dict[int, list[str]]:
    """Machine-verifiable routing errors, independently of game genre."""
    output: dict[int, list[str]] = {}
    for index, row in enumerate(raw.get("systems", [])):
        if not isinstance(row, dict):
            continue  # normal host schema validation reports malformed systems
        interaction = row.get("interaction")
        mode = row.get("input_mode", "custom")
        world = row.get("world_entities", [])
        choices = row.get("action_choices", [])
        errors: list[str] = []
        if interaction not in INTERACTIONS:
            errors.append("interaction must be none, event or request_response")
        if mode not in INPUT_MODES:
            errors.append("input_mode must be custom, host_button or world_prompt")
        if mode == "world_prompt" and interaction != "event":
            errors.append("world_prompt requires event interaction")
        if mode == "world_prompt" and (not isinstance(world, list) or len(world) != 1):
            errors.append("world_prompt requires exactly one world entity")
        if mode == "host_button" and world:
            errors.append("host_button accepts no world entity or target selection")
        if mode == "host_button" and interaction == "none":
            errors.append("host_button requires player interaction")
        if choices and (mode != "custom" or interaction != "request_response"):
            errors.append("action_choices require custom request_response")
        if interaction == "none" and mode != "custom":
            errors.append("passive server systems must use custom with no input")
        if errors:
            output[index] = errors
    return output


def apply_interaction_patch(
    raw: dict[str, Any], corrections: Any,
) -> dict[str, Any]:
    """Apply an explicitly bounded input/transport patch.

    Small constrained-output backends can return a whole unchanged system,
    omit the sole obvious index, or leave unchanged fields implicit. Accept
    such *representations*, never an unauthorized gameplay modification.
    Server behavior, world entities, action choices, identity and visible
    results are immutable. An ambiguous mapping is always rejected.
    """
    systems = raw.get("systems")
    if not isinstance(systems, list) or not all(
            isinstance(row, dict) for row in systems):
        raise ValueError("Transport repair requires existing system objects")
    invalid = interaction_issues(raw)
    if not invalid:
        raise ValueError("Transport repair has no invalid input to correct")
    if not isinstance(corrections, dict):
        raise ValueError("Transport repair must return an object")
    patches = corrections.get("systems")
    if isinstance(patches, dict):
        patches = [patches]
    if patches is None and len(invalid) == 1:
        # A single-system local JSON response sometimes omits the systems
        # envelope. No system identity can be misattributed in that case.
        patches = [corrections]
    if not isinstance(patches, list):
        raise ValueError("Transport repair must return a systems array")
    if not patches:
        raise ValueError("Transport repair returned no corrections")
    if len(patches) != len(invalid):
        raise ValueError("Transport repair must address every invalid system")
    allowed = {"index", "interaction", "input_mode", "client_behavior"}
    result = [dict(row) for row in systems]
    seen: set[int] = set()
    for candidate in patches:
        if not isinstance(candidate, dict):
            raise ValueError("Transport repair system must be an object")
        index = candidate.get("index")
        if index is None and len(invalid) == 1 and len(patches) == 1:
            index = next(iter(invalid))
        if (type(index) is not int or index not in invalid
                or index in seen):
            raise ValueError("Transport repair index must be a unique invalid index")
        seen.add(index)
        original = systems[index]
        # Echoed original fields are harmless only if byte-for-byte identical
        # to the preserved source-owned system. Never discard a real change
        # to server gameplay or world targets as if it were metadata.
        extra = set(candidate) - allowed
        if any(candidate[field] != original.get(field) for field in extra):
            raise ValueError(
                "Transport repair may edit only protocol and client input"
            )
        interaction = candidate.get("interaction", original.get("interaction"))
        mode = candidate.get("input_mode", original.get("input_mode", "custom"))
        client = candidate.get("client_behavior", original.get("client_behavior", ""))
        if (interaction not in INTERACTIONS or mode not in INPUT_MODES
                or not isinstance(client, str)):
            raise ValueError(
                "Transport repair may edit only protocol and client input"
            )
        result[index].update(
            interaction=interaction, input_mode=mode,
            client_behavior=client,
        )
    if seen != set(invalid):
        raise ValueError("Transport repair must address every invalid system")
    merged = dict(raw, systems=result)
    remaining = interaction_issues(merged)
    if remaining:
        raise ValueError(
            "Transport repair did not satisfy protocol: " + str(remaining))
    return merged
