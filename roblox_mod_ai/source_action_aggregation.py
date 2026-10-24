"""Bounded, source-checked accumulation of independently authored gameplay actions.

One local-model retry may produce a valid harvesting action while a preceding
retry produced ship construction and trade.  A retry is *not* authorization
to discard earlier source-owned actions. Keep only semantically admissible
candidates, then accept a minimum complete subset (max three actions).
Never synthesize server effects, silently certify incomplete requirements, or
carry actions across source facets.
"""
from __future__ import annotations

from itertools import combinations
import re
from typing import Any

from .request_semantics import request_semantic_errors
from .semantic_preservation import source_intent_conflicts, source_outcome_conflicts


def _candidate_identity(row: dict[str, Any]) -> str:
    # The action is identified by its authored server effect; a changed
    # display name must not let identical model output consume pool slots.
    return re.sub(r"\s+", " ", str(row["server_behavior"]).casefold()).strip()


def _same_effect_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Collapse paraphrases of one action, not distinct gameplay effects.

    In plan 69 the model emitted two differently named craft builders with
    identical observed outcomes and the same craft target. Keeping both
    consumed candidate budget without adding a requested action.
    """
    def normalized(value: Any) -> str:
        return re.sub(r"\\s+", " ", str(value or "").casefold()).strip()

    if (normalized(a.get("observable_result")) !=
            normalized(b.get("observable_result"))):
        return False
    if (not normalized(a.get("observable_result"))
            or sorted(map(normalized, a.get("world_entities") or [])) !=
               sorted(map(normalized, b.get("world_entities") or []))):
        return False
    words = lambda row: set(re.findall(
        r"[a-z]{3,}", normalized(row.get("server_behavior")),
    ))
    left, right = words(a), words(b)
    return bool(left and right and len(left & right) / len(left | right) >= .40)


def collect_source_action_candidates(
    previous: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    original_request: str,
    max_candidates: int = 12,
) -> list[dict[str, Any]]:
    """Keep bounded, distinct and locally safe drafts; never modify content."""
    result: list[dict[str, Any]] = []
    identities: set[str] = set()
    for item in [*previous, *incoming]:
        if not isinstance(item, dict):
            continue
        server = item.get("server_behavior")
        outcome = item.get("observable_result")
        name = item.get("name")
        if (not isinstance(name, str) or not name.strip()
                or not isinstance(server, str) or len(server.strip()) < 40
                or not isinstance(outcome, str) or len(outcome.strip()) < 24):
            continue
        if request_semantic_errors({"systems": [item]}, original_request):
            # In particular reject unsolicited Robux and player-to-player
            # transactions even when a model says they are 'trade'.
            continue
        identity = _candidate_identity(item)
        if identity in identities or any(
            _same_effect_duplicate(item, retained) for retained in result
        ):
            continue
        identities.add(identity)
        result.append(item)
        if len(result) >= max_candidates:
            break
    return result


def choose_complete_source_actions(
    source_requirements: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    max_actions: int = 3,
) -> list[dict[str, Any]] | None:
    """Select the smallest verifiably complete action set, or fail closed.

    This uses the SAME semantic server/outcome validators as the host,
    on the complete subset rather than mislabelling each partial action
    as a complete feature. Unrecognized intents remain unverified and are
    still subject to source audit and host implementation validation.
    """
    requirements = [
        str(row.get("statement") or "")
        for row in source_requirements if isinstance(row, dict)
    ]
    if not requirements or not all(requirements):
        return None
    for size in range(1, min(max_actions, len(candidates)) + 1):
        for rows in combinations(candidates, size):
            if len({str(row.get("name") or "").casefold() for row in rows}) != size:
                continue
            combined_server = " ".join(str(row["server_behavior"]) for row in rows)
            combined_outcome = " ".join(str(row["observable_result"]) for row in rows)
            if all(
                not source_intent_conflicts(source, combined_server)
                and not source_outcome_conflicts(source, combined_outcome)
                for source in requirements
            ):
                return list(rows)
    return None
