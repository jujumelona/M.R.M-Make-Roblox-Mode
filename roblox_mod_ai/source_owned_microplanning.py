"""Source-complete, small-output action decomposition for local planning models.

Never ask a 9B model for a 1,400-token multi-system architecture. It chooses
immutable original-source span IDs and SHORT action labels. The host checks
each attribution, adds only uncovered requested actions, then asks for a
separate short server/outcome contract for every verified action.

No heuristic genre actions or fabricated gameplay are inserted as defaults.
"""
from __future__ import annotations

import json
from typing import Any

from .atomic_action_quotes import (
    SourceActionBindingError, eligible_atomic_action_spans,
    verify_or_bind_actions,
)
from .semantic_preservation import (
    source_intent_conflicts, distinct_upgrade_action_gaps,
)

_MAX_ACTIONS = 6

_ACTION = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "action": {"type": "string", "minLength": 8, "maxLength": 150},
    },
    "required": ["source_id", "action"],
    "additionalProperties": False,
}


def _schema(*, minimum: int, maximum: int, allowed: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"actions": {
            "type": "array", "minItems": minimum, "maxItems": maximum,
            "items": {"type": "object", "properties": {
                **_ACTION["properties"],
                "source_id": {"type": "string", "enum": allowed},
            }, "required": _ACTION["required"], "additionalProperties": False},
        }},
        "required": ["actions"], "additionalProperties": False,
    }


def _call(router: Any, prompt: str, *, candidate_ids: list[str],
          minimum: int, maximum: int, tokens: int) -> list[dict[str, str]]:
    response = router.complete_json(
        prompt, role="planner", temperature=0.0,
        max_tokens=tokens,
        json_schema=_schema(
            minimum=minimum, maximum=maximum, allowed=candidate_ids,
        ),
    )
    rows = response.get("actions") if isinstance(response, dict) else None
    if (not isinstance(rows, list) or not minimum <= len(rows) <= maximum
            or any(not isinstance(row, dict) for row in rows)):
        raise SourceActionBindingError("ATOMIC_SOURCE_ACTION_REPLY_INVALID")
    return rows


def _coverage_issues(source: str, bound: list[dict[str, str]]) -> list[str]:
    # At action-plan stage there is no Luau yet. Nevertheless every planned
    # action must CLAIM its concrete authoritative effect; accepting vague
    # labels here would drop farming, earning or trades whose absence the
    # source validator can detect only in implementation mode.
    claims = [row["action"] for row in bound]
    return [
        *source_intent_conflicts(
            source, ". ".join(claims), require_implementation=True,
        ),
        *distinct_upgrade_action_gaps(source, claims),
    ]


def needs_compound_microplanning(source: str) -> bool:
    """Use small atomic planning only when the SOURCE requires several
    independently testable effects. Single-action sources keep their normal
    route; we never fabricate a second action just to fill a schema.
    """
    issues = source_intent_conflicts(
        source, "", require_implementation=True,
    )
    return len({item.split(":", 1)[0] for item in issues}) >= 2


def complete_source_owned_actions(
    router: Any, source: str, *, initial_actions: Any = None,
    max_actions: int = _MAX_ACTIONS,
) -> list[dict[str, str]]:
    """Bind 2-3 first actions, append ONLY missing independent source effects.

    Early attempts can be incomplete without being thrown away. The final
    bundle *must* pass the exact existing whole-clause semantic validator.
    """
    if not 2 <= max_actions <= _MAX_ACTIONS:
        raise SourceActionBindingError("ATOMIC_ACTION_BOUND_INVALID")
    spans = eligible_atomic_action_spans(source)
    by_id = {s["id"]: s["quote"] for s in spans}
    if len(spans) < 2:
        raise SourceActionBindingError("ATOMIC_SOURCE_SPANS_INSUFFICIENT")
    if initial_actions is None:
        initial_actions = _call(
            router,
            "From the ORIGINAL source clause choose 2-3 DISTINCT requested "
            "player/server actions. Return ONLY JSON {actions:[{source_id,action}]}. "
            "Each action is a SHORT sentence stating its own authoritative "
            "server-side state change and target, and source_id selects "
            "a matching exact source-text anchor. Do not write Luau code, "
            "invent genre mechanics, or treat a condition as an action. "
            "Preserve different requested upgrade targets separately. JSON only.\n"
            + json.dumps({
                "source": source,
                "source_spans": [
                    {"id": s["id"], "quote": s["quote"]} for s in spans
                ],
            }, ensure_ascii=False),
            candidate_ids=list(by_id), minimum=2, maximum=3, tokens=340,
        )
    raw = list(initial_actions)
    bound = verify_or_bind_actions(
        router, source, raw, require_complete=False, max_actions=max_actions,
    )
    failed_proposals: set[str] = set()
    while len(raw) < max_actions:
        gaps = _coverage_issues(source, bound)
        if not gaps:
            return verify_or_bind_actions(
                router, source, raw, max_actions=max_actions,
            )
        occupied = {row["source_quote"] for row in bound}
        candidates = [
            {"id": s["id"], "quote": s["quote"]}
            for s in spans if s["quote"] not in occupied
        ]
        if not candidates:
            raise SourceActionBindingError("ATOMIC_SOURCE_NO_DISTINCT_CANDIDATES")
        # Two attempts to supply ONE missing effect. A failed reply never
        # replaces previously bound actions or sends them back for rewriting.
        appended = False
        for _ in range(2):
            additions = _call(
                router,
                "The accepted actions below remain FROZEN. Source coverage "
                "is missing specific requested mechanics. Supply EXACTLY ONE "
                "NEW source-owned action implementing the FIRST missing "
                "mechanic. The action must explicitly name the server-owned "
                "state it changes (such as an owned inventory, currency, "
                "component or target world object). Choose an unused "
                "source_id that actually supports it. Do not repeat an "
                "existing subsystem as another requested subsystem. "
                "Do not include accepted actions "
                "in the reply. Return ONLY JSON {actions:[{source_id,action}]}. "
                "No server code or invented game systems. JSON only.\n"
                + json.dumps({
                    "original_source": source,
                    "accepted_actions": bound,
                    "missing_source_obligations": gaps[:4],
                    "available_source_spans": candidates,
                    "invalid_actions_to_avoid": list(failed_proposals)[-3:],
                }, ensure_ascii=False),
                candidate_ids=[s["id"] for s in candidates],
                minimum=1, maximum=1, tokens=180,
            )
            proposed = additions[0]
            proposed_signature = json.dumps(proposed, sort_keys=True,
                                             ensure_ascii=False)
            if proposed_signature in failed_proposals:
                continue
            try:
                checked = verify_or_bind_actions(
                    router, source, [*raw, proposed],
                    require_complete=False, max_actions=max_actions,
                )
            except SourceActionBindingError:
                failed_proposals.add(proposed_signature)
                continue
            after = _coverage_issues(source, checked)
            # Semantic coverage must ACTUALLY improve. Adding a duplicate
            # upgrade word or renaming an existing action is not progress.
            if len(after) >= len(gaps) or set(after) >= set(gaps):
                failed_proposals.add(proposed_signature)
                continue
            raw.append(proposed)
            bound = checked
            appended = True
            break
        if not appended:
            raise SourceActionBindingError(
                "ATOMIC_SOURCE_MISSING_ACTION_UNRESOLVED: " +
                "; ".join(gaps[:3]),
            )
    remaining = _coverage_issues(source, bound)
    if remaining:
        raise SourceActionBindingError(
            "ATOMIC_SOURCE_MAX_ACTIONS_INCOMPLETE: " +
            "; ".join(remaining[:4]),
        )
    return verify_or_bind_actions(
        router, source, raw, max_actions=max_actions,
    )
