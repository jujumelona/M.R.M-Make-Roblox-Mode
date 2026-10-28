"""Generic, source-constrained repair of one failed gameplay state mutation.

The model supplies small independent operands instead of rewriting a whole
server method description. The host never invents a world object, economy,
state name, effect, or gameplay action. The existing source and outcome
validators remain the acceptance authority.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .request_semantics import request_semantic_errors
from .semantic_preservation import source_intent_conflicts

# This is intentionally an action-independent vocabulary. It is a *minimum*
# positive-write check, not proof of correct Luau or runtime persistence.
_WRITE = re.compile(
    r"\b(?:set|sets|updat\w*|writ\w*|record\w*|persist\w*|sav\w*|"
    r"creat\w*|construct\w*|build\w*|establish\w*|found\w*|"
    r"claim\w*|mark\w*|assign\w*|add\w*|grant\w*|"
    r"delet\w*|remov\w*|reduc\w*|increas\w*|decreas\w*|"
    r"debit\w*|credit\w*|transfer\w*|damag\w*|mov\w*|"
    r"teleport\w*|launch\w*|equip\w*|install\w*|"
    r"harvest\w*|extract\w*|collect\w*|recruit\w*)\b|"
    r"기록|저장|생성|건설|설립|소유|증가|감소|차감|이동|채굴|획득|설치|공격",
    re.I,
)
_NEGATED = re.compile(
    r"\b(?:not|never|without|cannot|can't|doesn't|does not|"
    r"only|merely)\b.{0,80}\b(?:write|record|persist|"
    r"create|establish|change|update|grant|damage|"
    r"build|move|set|claim)\b",
    re.I,
)
_QUALIFIER_ONLY = re.compile(
    r"^(?:the )?(?:server )?(?:checks?|validates?|"
    r"verifies?|requires?|ensures?|displays?|shows?|"
    r"prompts?|announces?)\b", re.I,
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "validated_input": {"type": "string", "minLength": 20, "maxLength": 190},
        "state_mutation": {"type": "string", "minLength": 24, "maxLength": 220},
        "rejected_input": {"type": "string", "minLength": 18, "maxLength": 145},
    },
    "required": ["validated_input", "state_mutation", "rejected_input"],
    "additionalProperties": False,
}


def author_state_mutation_repair(
    router: Any, action: dict[str, str], previous_server: str,
    *, original_prompt: str, diagnostics: list[str],
) -> str:
    """Compile one *model-authored* effect and recheck its original source.

    A successful reply must name a positive write to actual gameplay state,
    not an authorization check, an already-existing state, or a UI message.
    """
    reply = router.complete_json(
        "Repair ONE already source-authorized server action using three "
        "SHORT independent fields. validated_input: existing authoritative "
        "input/target and its authorization precondition; state_mutation: "
        "an AFFIRMATIVE new state change the server actually commits (not a "
        "prerequisite, status label, or UI); rejected_input: what invalid "
        "requests the server rejects without modifying state. Copy no code. "
        "Preserve the exact original source-owned gameplay effect; do not "
        "substitute a different action or invent a new mechanic. "
        "Use concrete state names and target roles established in the action. "
        "Never merely say a request is accepted or that a state already "
        "exists. Do not use generated UI as the state mutation. JSON only.\n"
        + json.dumps({
            "source_quote": action["source_quote"],
            "source_owned_action": action["action"],
            "invalid_server_behavior": previous_server[:450],
            "exact_validator_errors": diagnostics[:8],
        }, ensure_ascii=False),
        role="planner", temperature=0.0, max_tokens=325,
        json_schema=_SCHEMA,
    )
    if not isinstance(reply, dict) or set(reply) != set(_SCHEMA["required"]):
        raise ValueError("ATOMIC_STATE_REPAIR_INVALID_FIELDS")
    guard, write, reject = (
        reply["validated_input"], reply["state_mutation"],
        reply["rejected_input"],
    )
    for key, value in (("validated_input", guard),
                       ("state_mutation", write),
                       ("rejected_input", reject)):
        shape = _SCHEMA["properties"][key]
        if (not isinstance(value, str)
                or not shape["minLength"] <= len(value.strip()) <= shape["maxLength"]):
            raise ValueError("ATOMIC_STATE_REPAIR_INVALID_" + key.upper())
    if (_WRITE.search(write) is None or _NEGATED.search(write)
            or _QUALIFIER_ONLY.search(write)):
        raise ValueError("ATOMIC_STATE_REPAIR_NO_COMMITTED_EFFECT")
    # The new mutation, not the surrounding old prose, must carry the
    # requested action. No genre-specific string is inserted by the host.
    for source in (action["source_quote"], action["action"]):
        gaps = source_intent_conflicts(source, write)
        if gaps:
            raise ValueError("ATOMIC_STATE_REPAIR_SOURCE_GAP: " + "; ".join(gaps)[:280])
    candidate = (
        "For the original requested action, the server validates "
        + guard.strip().rstrip(".; ") + "; on authorization, the server "
        + write.strip().rstrip(".; ") + "; invalid requests are rejected: "
        + reject.strip().rstrip(".; ") + "."
    )
    forbidden = request_semantic_errors(candidate, original_prompt)
    if forbidden:
        raise ValueError(
            "ATOMIC_STATE_REPAIR_UNREQUESTED_EFFECT: "
            + "; ".join(forbidden)[:320]
        )
    for source in (action["source_quote"], action["action"]):
        gaps = source_intent_conflicts(source, candidate)
        if gaps:
            raise ValueError("ATOMIC_STATE_REPAIR_INCOMPLETE: " + "; ".join(gaps)[:280])
    return candidate
