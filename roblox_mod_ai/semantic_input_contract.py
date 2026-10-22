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
        if (isinstance(interaction, str) and interaction in INPUT_MODES
                and isinstance(mode, str) and mode in INTERACTIONS):
            row = dict(row, interaction=mode, input_mode=interaction)
            changed.append(index)
        normalized.append(row)
    return (dict(raw, systems=normalized) if changed else raw), changed



def bind_host_standard_transport(raw: dict[str, Any]) -> tuple[dict[str, Any], list[int]]:
    """Compile an existing semantic plan into host-owned Roblox ingress.

    The small model owns *what* the action does, never RemoteEvent vs
    RemoteFunction, input widget choice or client transport prose. Treat its
    protocol fields as hints, not instructions. Correct a malformed protocol
    deterministically without requesting another model call or changing
    server_behavior, visible results, names, targets, or choices.

    A genuinely passive 'none' action remains passive; world-prompt actions
    with a single declared object remain proximity interactions. Other
    player actions use the same typed Remote ABI. Never infer game genre.
    """
    systems = raw.get("systems")
    if not isinstance(systems, list):
        return raw, []
    changed: list[int] = []
    normalized: list[Any] = []
    for index, original in enumerate(systems):
        if not isinstance(original, dict):
            normalized.append(original)
            continue
        row = dict(original)
        mode = row.get("input_mode")
        interaction = row.get("interaction")
        world = row.get("world_entities", [])
        choices = row.get("action_choices", [])
        # A server-only scheduled/background mechanic is a gameplay
        # property, not a Remote enum. It must be explicitly marked and
        # cannot carry choices that require a player's decision.
        autonomous = row.pop("autonomous", False) is True
        if autonomous and not choices:
            mode, interaction = "custom", "none"
        # Explicitly requested world prompts need one host-owned Part.
        # No object or multiple objects means an actionable typed selection
        # UI instead; it must NEVER attach to an arbitrary part.
        elif (mode == "world_prompt" and isinstance(world, list)
                and len(world) == 1 and not choices):
            mode, interaction = "world_prompt", "event"
        elif mode == "host_button" and not world and not choices:
            mode, interaction = "host_button", "request_response"
        else:
            # All other player input uses the host typed form. A 'none'
            # action remains passive only when the model specifically
            # declared it and no explicit choices contradict that intent.
            mode = "custom"
            if choices or interaction not in INTERACTIONS:
                interaction = "request_response"
            elif interaction == "none":
                pass
        row["input_mode"] = mode
        row["interaction"] = interaction
        if mode == "custom" and interaction != "none":
            # The LocalScript is emitted deterministically by the host.
            # Remove model-authored UI prose, which can invent unrelated
            # mechanics and is not the networking source of truth.
            row["client_behavior"] = (
                "Host-owned typed action form submits validated selection "
                "and quantity fields over the routed Roblox Remote for " +
                str(row.get("name") or "the requested gameplay action") + "."
            )
        elif mode in {"world_prompt", "host_button"}:
            row["client_behavior"] = (
                "Host-owned " + mode + " activates the requested gameplay "
                "server action and displays its observable result."
            )
        else:
            # Autonomous server mechanics have no client controller. The
            # slim production schema never supplies client_behavior.
            row["client_behavior"] = ""
        if row != original:
            changed.append(index)
        normalized.append(row)
    return dict(raw, systems=normalized), changed


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
        if not isinstance(interaction, str) or interaction not in INTERACTIONS:
            errors.append("interaction must be none, event or request_response")
        if not isinstance(mode, str) or mode not in INPUT_MODES:
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
        # A custom ingress requires game-specific client input. Catch this
        # here so it enters the metadata/client-only repair pathway rather
        # than regenerating valid authoritative server gameplay. Host-owned
        # world prompts and zero-argument buttons are intentionally exempt.
        if (isinstance(interaction, str)
                and interaction in {"event", "request_response"}
                and mode == "custom"
                and (not isinstance(row.get("client_behavior"), str)
                     or len(row["client_behavior"].strip()) < 24)):
            errors.append("custom player input needs substantive client_behavior")
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
        # JSON schemas often materialize omitted optional collection fields
        # as empty lists. These are semantically identical to an absent
        # world_entities/action_choices default and MUST NOT turn a valid
        # repair into an infinite retry. Other extra keys remain forbidden.
        default_empty = {"world_entities", "action_choices"}
        if any(
            candidate[field] != (
                original.get(field, []) if field in default_empty
                else original.get(field)
            )
            for field in extra
        ):
            raise ValueError(
                "Transport repair may edit only protocol and client input"
            )
        interaction = candidate.get("interaction", original.get("interaction"))
        mode = candidate.get("input_mode", original.get("input_mode", "custom"))
        client = candidate.get("client_behavior", original.get("client_behavior", ""))
        if (not isinstance(interaction, str)
                or interaction not in INTERACTIONS
                or not isinstance(mode, str) or mode not in INPUT_MODES
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


# When an already-correct transport lacks ONLY a custom input description,
# the repair output must NOT contain another full system / protocol / world
# definition. This entirely removes the class of JSON field drift seen in
# plan_failure_logs (14) and (15).
CLIENT_INPUT_ONLY_SCHEMA = {
    "type": "object",
    "properties": {
        "client_behavior": {"type": "string", "maxLength": 1200},
    },
    "required": ["client_behavior"],
}


def apply_client_input_completion(
    raw: dict[str, Any], completion: Any, *, index: int,
) -> dict[str, Any]:
    """Complete only the missing user interaction; keep all game state immutable.

    The original system name is the source-authorized action identity. Require
    that identity to appear in the proposed input description rather than
    silently accepting a UI for some unrelated action. This is a lightweight
    check in addition to later gameplay and Luau validation, not proof that
    the action actually works.
    """
    import re

    systems = raw.get("systems")
    if (not isinstance(systems, list) or type(index) is not int
            or not 0 <= index < len(systems)
            or not isinstance(systems[index], dict)):
        raise ValueError("Client-only repair requires an existing system index")
    issues = interaction_issues(raw)
    if issues != {
        index: ["custom player input needs substantive client_behavior"]
    }:
        raise ValueError("Client-only repair requires exactly one missing custom UI")
    if not isinstance(completion, dict) or set(completion) != {"client_behavior"}:
        raise ValueError("Client-only repair may edit only client_behavior")
    client = completion["client_behavior"]
    if not isinstance(client, str) or not 24 <= len(client.strip()) <= 1200:
        raise ValueError("Client-only repair must describe actual player input")
    # A missing UI for "Trade" must not be replaced by "Repair console".
    # Match meaningful system identity words without an English genre list.
    name = str(systems[index].get("name") or "")
    words = [
        token.casefold() for token in re.findall(
            r"[A-Za-z]{4,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
        )
        if token.casefold() not in {
            "system", "service", "server", "client", "action",
            "request", "player", "validated", "mode", "module",
        }
    ]
    client_words = [
        token.casefold() for token in re.findall(r"[A-Za-z]{3,}", client)
    ]

    def stem(word: str) -> str:
        for ending in ("ation", "ing", "ment", "ed", "es", "s"):
            if word.endswith(ending) and len(word) >= len(ending) + 4:
                return word[:-len(ending)]
        return word

    if words and not any(
        stem(identity)[:4] == stem(word)[:4]
        for identity in words for word in client_words
    ):
        raise ValueError(
            "Client-only repair describes an unrelated user action"
        )
    # A generic "an animation will play" is NOT an interactive input path.
    if not re.search(
        r"\b(?:click|press|select|choose|pick|enter|type|tap|"
        r"target|submit|drag|open|activate|input|touch|"
        r"key(?:board)?|button|menu|interact|confirm)\w*\b",
        client, re.I,
    ):
        raise ValueError("Client-only repair lacks a player input action")
    result = [dict(row) for row in systems]
    result[index]["client_behavior"] = client.strip()
    fixed = dict(raw, systems=result)
    if interaction_issues(fixed):
        raise ValueError("Client-only repair did not resolve input contract")
    return fixed
