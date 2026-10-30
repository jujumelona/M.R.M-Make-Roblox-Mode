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
    r"(?:(?:the|a|an|owned|assembled|existing|entire|whole|player['’]s|pilot['’]s)\s+){0,5}"
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


# "Destination world" is a valid referent only when paired with a real
# physical vehicle relocation in the server behavior.
_DESTINATION_WORLD = re.compile(
    r"\b(?:destination|target)\s+(?:world|region|zone|location)\b", re.I,
)
_CRAFT_LOCATION_CHANGE = re.compile(
    r"\b(?:physically|visibly)\s+chang(?:e|es|ed|ing)\s+"
    r"(?:its\s+)?(?:world\s+)?location\b|"
    r"\bchang(?:e|es|ed|ing)\s+(?:its\s+)?"
    r"(?:world\s+)?(?:position|location)\s+to\b", re.I,
)
_CRAFT_ARRIVED_PRESENT = re.compile(
    r"\b(?:physically|visibly)\s+present\b", re.I,
)
_NEGATED_OCCUPANT_EXIT = re.compile(
    r"\b(?:no|never|not|without|does\s+not|do\s+not|"
    r"doesn['’]t|don['’]t|must\s+not|cannot|can['’]t)\b"
    r".{0,70}?\b(?:eject\w*|disembark\w*|exit\w*|leav\w*)\b|"
    r"\b(?:reject\w*|refus\w*|prevent\w*|forbid\w*)\b"
    r".{0,70}?\b(?:eject\w*|disembark\w*)\b", re.I,
)


def has_vehicle_arrival_evidence(outcome: str) -> bool:
    """Require a visible craft at a destination, not just a player/status flag."""
    for clause in re.split(r"[,;.!?\n]+", str(outcome or "")):
        actor = _VEHICLE.search(clause)
        if not actor or _NEGATED_CRAFT_MOVE.search(clause):
            continue
        if not (_SPACE_DESTINATION.search(clause)
                or _DESTINATION_WORLD.search(clause)):
            continue
        arrival = _ARRIVAL_EFFECT.search(clause)
        if arrival and arrival.start() > actor.start():
            if not re.search(
                r"\b(?:player|pilot|passenger|character)\s+"
                r"(?:appears?|arrives?|mov(?:e|es|ed|ing)|teleport\w*)\b",
                clause[actor.end():arrival.end()], re.I,
            ):
                return True
        location_change = _CRAFT_LOCATION_CHANGE.search(clause)
        if location_change and location_change.start() > actor.start():
            return True
        visible_at_destination = _CRAFT_ARRIVED_PRESENT.search(clause)
        if (visible_at_destination
                and visible_at_destination.start() > actor.start()
                and _DESTINATION_WORLD.search(clause)):
            return True
    return False


def has_actual_occupant_ejection(text: str) -> bool:
    """Treat 'no passenger is ejected' as prevention, not actual ejection."""
    for clause in re.split(r"[,;.!?\n]+", str(text or "")):
        # A conditional *rejected* attempt to remove passengers is not an
        # actual ejection. Distinguish "the player exits" from "a request
        # that would empty the crew list is rejected" without making a
        # genre-specific exception or suppressing other independent clauses.
        rejected_exit = re.search(
            r"\b(?:invalid|unauthorized|prohibited|unsafe)\b.{0,180}"
            r"\b(?:request|input|action)\b.{0,120}"
            r"\b(?:would|could|attempt(?:s|ed)?\s+to)\b.{0,120}"
            r"\b(?:leave|exit|eject\w*|disembark\w*|empty)\b.{0,140}"
            r"\b(?:reject\w*|block\w*|deny|denied|refus\w*)\b",
            clause, re.I,
        )
        matches = list(_LEAVES.finditer(clause))
        for match in matches:
            # Reject only the conditional's own exit, not another actual
            # passenger exit in the same clause or a later independent event.
            if (rejected_exit is not None
                    and rejected_exit.start() <= match.start()
                    and match.end() <= rejected_exit.end()):
                continue
            # The negation must govern this match, not a different sentence.
            window = clause[max(0, match.start() - 90):match.end()]
            if not _NEGATED_OCCUPANT_EXIT.search(window):
                return True
    return False


def motion_contract_errors(
    contract: dict[str, str] | None,
    systems: list[dict[str, Any]],
) -> list[str]:
    """Require a consistent server/action pair; never join unrelated systems."""
    if contract is None:
        return []
    pairs = [
        (str(item.get("server_behavior") or ""),
         str(item.get("observable_result") or ""))
        for item in systems if isinstance(item, dict)
    ]
    moving = [
        (server, result) for server, result in pairs
        if has_vehicle_motion_effect(server)
    ]
    vehicle_motion = bool(moving)
    arrival = any(
        has_vehicle_arrival_evidence(result)
        for _server, result in moving
    )
    ejection = any(
        has_actual_occupant_ejection(server)
        or has_actual_occupant_ejection(result)
        for server, result in pairs
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
        # An owned vehicle may be called craft, raft or a generated name;
        # do not reject an actual craft:PivotTo just because the identifier
        # omits the English token 'ship'. Object identity is checked by the
        # independent materialized world/ownership contract.
        r"\b(?:ship|spaceship|spacecraft|vehicle|vessel|rocket|shuttle|craft)\w*"
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
