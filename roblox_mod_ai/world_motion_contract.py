"""Source-grounded world-transition ownership for scoped gameplay actions.

A pronoun such as "then go into space" may refer to a previously assembled
vehicle. The model must not reinterpret that as abandoning the vehicle.
This contract is a small *mechanics* obligation, not a hard-coded game design,
an invented 3D asset, or evidence that the Roblox game ran.
"""
from __future__ import annotations

import re
from typing import Any


_DEPART = re.compile(
    r"우주(?:로|에)\s*(?:나가|나갈|나간|출발|진입|이동)|"
    r"\b(?:launch|depart|travel|fly|enter)\b.{0,55}\b(?:space|orbit)\b",
    re.I,
)
_VEHICLE = re.compile(
    r"우주선|\b(?:spacecraft|spaceship|ship|rocket|shuttle|vessel|vehicle)\b",
    re.I,
)
_MOTION = re.compile(
    r"\b(?:launch\w*|mov(?:e|es|ed|ing)|teleport\w*|"
    r"relocat\w*|transport\w*|transfer\w*|warp\w*|"
    r"fly|flies|flown|travel\w*|depart\w*)\b",
    re.I,
)
_WORLD_TARGET = re.compile(r"\b(?:space|orbit|orbital|destination|zone|planet)\b|우주|궤도|행성", re.I)
_LEAVES = re.compile(
    r"\b(?:player|passenger|pilot|crew|character)\b.{0,65}"
    r"\b(?:leav(?:e|es|ing)|exits?|eject\w*|disembark\w*)\b"
    r".{0,70}\b(?:ship|spacecraft|spaceship|vehicle|vessel)\b|"
    r"\b(?:ship|spacecraft|spaceship|vehicle|vessel)\b.{0,60}"
    r"\b(?:empty|no longer carrying|abandons?|without (?:the )?player)\b|"
    r"\b(?:eject\w*|disembark\w*)\b",
    re.I,
)


def source_motion_contract(
    source_clause: str, adjacent_context: list[str] | tuple[str, ...] = (),
) -> dict[str, str] | None:
    """Infer an unambiguous vehicle departure from the user's own clauses.

    A conditional 'when you reach space' belongs to other mechanics, and
    bare 'go to space' without a named craft must not invent a vehicle.
    """
    source = str(source_clause or "")
    if re.search(r"우주로\s*나가면", source):
        return None
    if not _DEPART.search(source):
        return None
    context = " ".join([source, *(str(x) for x in adjacent_context)])
    if not _VEHICLE.search(context):
        return None
    return {
        "kind": "vehicle_world_transition",
        "actor": "owned spacecraft / vehicle",
        "destination": "playable space / orbit",
        "occupant_rule": "players remain aboard the vehicle",
        "effect": "server moves the vehicle and its occupants to the destination",
    }


def motion_contract_errors(
    contract: dict[str, str] | None,
    systems: list[dict[str, Any]],
) -> list[str]:
    """Reject inverse actor roles before invoking costly Luau codegen."""
    if contract is None:
        return []
    server = " ".join(str(x.get("server_behavior", "")) for x in systems)
    outcome = " ".join(str(x.get("observable_result", "")) for x in systems)
    # The vehicle must be the thing moved, not merely a precondition that
    # authorizes a player's ejection. Keep the evidence within one sentence.
    vehicle_motion = False
    # Syntactic proximity alone is unsafe: "checks ship, then launches
    # player" mentions the ship close to a launch verb but moves the wrong
    # actor. The motion must take the craft as its DIRECT object, or the
    # craft must be the subject of its own movement.
    vehicle_as_object = re.compile(
        r"\b(?:launch\w*|mov(?:e|es|ed|ing)|teleport\w*|"
        r"relocat\w*|transport\w*|warp\w*|"
        r"travel\w*|depart\w*)\b"
        r"\s+(?:(?:the|a|an|owned|assembled|player['’]s)\s+){0,3}"
        r"(?:ship|spaceship|spacecraft|vessel|rocket|shuttle|vehicle)\b",
        re.I,
    )
    vehicle_as_subject = re.compile(
        r"\b(?:ship|spaceship|spacecraft|vessel|rocket|shuttle|vehicle)\b"
        r"\s+(?:(?:itself|successfully|automatically|then|"
        r"with\s+(?:the\s+)?players?\s+aboard)\s+){0,3}"
        r"(?:is\s+)?(?:launch\w*|mov(?:e|es|ed|ing)|teleport\w*|"
        r"relocat\w*|transport\w*|warp\w*|"
        r"travel\w*|depart\w*)\b",
        re.I,
    )
    for sentence in re.split(r"[.;!?\n]+", server):
        if not _WORLD_TARGET.search(sentence):
            continue
        if vehicle_as_object.search(sentence) or vehicle_as_subject.search(sentence):
            vehicle_motion = True
            break
    errors = []
    if not vehicle_motion:
        errors.append(
            "VEHICLE_TRANSITION_MISSING: source requires the vehicle itself "
            "to change world location; changing the player's mode or ejecting "
            "the player is not vehicle travel"
        )
    if _LEAVES.search(server) or _LEAVES.search(outcome):
        errors.append(
            "VEHICLE_OCCUPANCY_REVERSED: players must remain aboard the "
            "departing craft rather than be ejected into the destination"
        )
    if not (_VEHICLE.search(outcome) and _WORLD_TARGET.search(outcome)):
        errors.append(
            "VEHICLE_TRAVEL_RESULT_MISSING: show the craft arriving in the "
            "destination world, not only a player status flag"
        )
    return errors


def vehicle_motion_code_errors(code: str) -> list[str]:
    """Necessary static checks; do not equate these with Studio playtest."""
    from .dynamic_wiring import _mask_strings, _without_comments

    executable = _mask_strings(_without_comments(code))
    # Accept Model:PivotTo, part.CFrame, and character/vehicle MoveTo;
    # require an actual movement statement involving a craft variable.
    movement = re.compile(
        r"\b(?:ship|spaceship|spacecraft|vehicle|vessel|rocket|shuttle)\w*"
        r"(?:(?:\.|:)\w+|\[[^]]+\]){0,3}"
        r"(?:\s*:\s*(?:PivotTo|MoveTo|SetPrimaryPartCFrame)\s*\("
        r"|\s*\.\s*CFrame\s*=)|"
        r"\b(?:PivotTo|MoveTo|SetPrimaryPartCFrame)\s*\("
        r".{0,110}\b(?:ship|spacecraft|vehicle)\w*",
        re.I,
    )
    return ([] if movement.search(executable) else [
        "VEHICLE_WORLD_MOVEMENT_CODE_MISSING: no server-side craft movement "
        "statement; a player status flag or character-only teleport is insufficient"
    ])
