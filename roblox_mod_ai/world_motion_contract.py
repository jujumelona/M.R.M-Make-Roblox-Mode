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
    r"우주선|\b(?:spacecraft|spaceship|ship|rocket|shuttle|vessel|vehicle|craft)\b",
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
    r".{0,70}\b(?:ship|spacecraft|spaceship|vehicle|vessel|craft)\b|"
    r"\b(?:ship|spacecraft|spaceship|vehicle|vessel|craft)\b.{0,60}"
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


# A semantic movement effect is not tied to an arbitrary English word order.
# Small models may say "relocation of the craft" or "sets spacecraft's CFrame"
# instead of "launches the spacecraft". Both express the same plan; neither
# proves that the generated Luau has actually moved an object.
_CRAFT = r"(?:spacecraft|spaceship|ship|rocket|shuttle|vessel|vehicle|craft)"
_CRAFT_ARG = (
    r"(?:(?:the|a|an|owned|assembled|existing|player['’]s|pilot['’]s)\s+){0,5}"
    + _CRAFT + r"\b"
)
# A physical change on the surface does not satisfy departure to SPACE.
_SPACE_DESTINATION = re.compile(r"\b(?:space|orbit|orbital)\b|우주|궤도", re.I)
_MOVE_EFFECTS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\b(?:launch\w*|mov(?:e|es|ed|ing)|teleport\w*|relocat\w*|"
    r"transport\w*|transfer\w*|warp\w*|transition\w*|depart\w*)\s+"
    + _CRAFT_ARG,
    r"\b(?:relocation|movement|teleportation|transfer|transport|transition)"
    r"\s+of\s+" + _CRAFT_ARG,
    r"\b(?:sets?|changes?|updates?|assigns?|appl(?:y|ies))\b"
    r".{0,100}?" + _CRAFT_ARG +
    r"(?:['’]s)?\s+(?:new\s+)?(?:world\s+)?(?:position|cframe|location)\b",
    _CRAFT_ARG + r"(?:['’]s)?\s+(?:new\s+)?(?:world\s+)?"
    r"(?:position|cframe|location)\b.{0,130}?"
    r"\b(?:appl(?:y|ies)|sets?|updates?|changes?|relocat\w*)\b",
    r"\b(?:applies?|sets?|updates?)\s+(?:it|the\s+(?:new\s+)?"
    r"(?:position|cframe|location))\s+to\s+" + _CRAFT_ARG,
    _CRAFT_ARG +
    r"(?:\s+(?:itself|successfully|automatically|then|"
    r"with\s+(?:the\s+)?players?\s+aboard)){0,3}\s+"
    r"(?:(?:is|are|was|were|has\s+been|will\s+be)\s+)?"
    r"(?:launch\w*|mov(?:e|es|ed|ing)|teleport\w*|relocat\w*|"
    r"transport\w*|transfer\w*|warp\w*|transition\w*|depart\w*)\b",
))
_NEGATED_CRAFT_MOVE = re.compile(
    r"\bwithout\s+(?:actually\s+)?"
    r"(?:relocat\w*|mov\w*|launch\w*|transport\w*)\s+" + _CRAFT_ARG
    + r"|\b(?:while|but)\s+(?:the\s+)?" + _CRAFT +
    r"\s+remains?\s+(?:docked|unmoved|stationary)\b",
    re.I,
)


def has_vehicle_motion_effect(server_behavior: str) -> bool:
    for sentence in re.split(r"[.;!?\n]+", server_behavior):
        if (not _SPACE_DESTINATION.search(sentence)
                or _NEGATED_CRAFT_MOVE.search(sentence)):
            continue
        if any(pattern.search(sentence) for pattern in _MOVE_EFFECTS):
            return True
    return False



_ARRIVAL_EFFECT = re.compile(
    r"\b(?:mov(?:e|es|ed|ing)|appear\w*|arriv\w*|relocat\w*|"
    r"launch\w*|warp\w*|teleport\w*)\b", re.I,
)


def has_vehicle_arrival_evidence(outcome: str) -> bool:
    """Visible arrival of the craft, not a passenger's solo arrival.

    Clauses are split at commas/semicolons so "ship stays docked, player
    arrives in space" cannot combine unrelated subjects into proof.
    """
    for clause in re.split(r"[,;.!?\n]+", str(outcome or "")):
        actor = _VEHICLE.search(clause)
        arrival = _ARRIVAL_EFFECT.search(clause)
        if not actor or not arrival or not _SPACE_DESTINATION.search(clause):
            continue
        if arrival.start() <= actor.start() or _NEGATED_CRAFT_MOVE.search(clause):
            continue
        if re.search(
            r"\b(?:player|pilot|passenger|character)\s+"
            r"(?:appears?|arrives?|mov(?:e|es|ed|ing)|teleport\w*)\b",
            clause[actor.end():arrival.end()], re.I,
        ):
            continue
        return True
    return False


def motion_contract_errors(
    contract: dict[str, str] | None,
    systems: list[dict[str, Any]],
) -> list[str]:
    """Check a complete server/outcome pair, not a Studio execution proof.

    Avoid combining a movement verb from one subsystem with a craft noun
    from another subsystem to manufacture evidence of a launch.
    """
    if contract is None:
        return []
    pairs = [
        (str(item.get("server_behavior") or ""),
         str(item.get("observable_result") or ""))
        for item in systems if isinstance(item, dict)
    ]
    vehicle_motion = any(has_vehicle_motion_effect(server) for server, _ in pairs)
    arrival = any(
        has_vehicle_arrival_evidence(outcome)
        for _, outcome in pairs
    )
    ejection = any(
        _LEAVES.search(server) or _LEAVES.search(outcome)
        for server, outcome in pairs
    )
    errors = []
    if not vehicle_motion:
        errors.append(
            "VEHICLE_TRANSITION_MISSING: source requires the vehicle itself "
            "to change world location; changing the player's mode or ejecting "
            "the player is not vehicle travel"
        )
    if ejection:
        errors.append(
            "VEHICLE_OCCUPANCY_REVERSED: players must remain aboard the "
            "departing craft rather than be ejected into the destination"
        )
    if not arrival:
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
