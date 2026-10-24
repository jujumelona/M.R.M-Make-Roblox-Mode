"""Host-owned exact source anchors for multi-action gameplay decomposition.

A small multilingual model should select an immutable source span ID rather
than copy a Korean quote perfectly. The host always reconstructs that quote
from the original user requirement; it never fabricates missing mechanics.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .semantic_preservation import source_intent_conflicts


class SourceActionBindingError(ValueError):
    """An authored action could not be grounded in immutable user text."""


def indexed_source_spans(source: str, *, max_width: int = 4,
                         max_candidates: int = 48) -> list[dict[str, str]]:
    """Cover the ENTIRE source with bounded immutable phrase candidates.

    Previously width=1 was enumerated from word zero until the 48-candidate
    cap. A longer Korean/English clause then omitted ALL multiword phrases
    and often its final player actions. Give each window width a quota,
    sampling uniformly across the original token positions. For short text
    keep exhaustive windows for backward-compatible source IDs.
    """
    words = list(re.finditer(r"\S+", source))
    if not words:
        raise SourceActionBindingError("ATOMIC_SOURCE_TEXT_REQUIRED")
    if max_width < 1 or max_candidates < 1:
        raise SourceActionBindingError("ATOMIC_SOURCE_WINDOW_BOUNDS_INVALID")

    n = len(words)
    widths = list(range(1, min(max_width, n) + 1))
    all_count = sum(n - width + 1 for width in widths)
    candidates: list[tuple[int, int]] = []
    if all_count <= max_candidates:
        # Preserve original short-prompt IDs; tests and checkpoints use them.
        candidates = [(start, width)
                      for width in widths
                      for start in range(n - width + 1)]
    else:
        # First prove complete lexical coverage. Uniformly sampled sliding
        # windows can leave arbitrary middle words absent despite including
        # the beginning and end (observed in the 65-word regression).
        cover_width = widths[-1]
        if n > max_candidates * cover_width:
            raise SourceActionBindingError(
                "ATOMIC_SOURCE_TOO_LONG_FOR_SPAN_WINDOW: split the ORIGINAL "
                "source into smaller host-owned clauses; never drop words")
        candidates = [
            (start, min(cover_width, n - start))
            for start in range(0, n, cover_width)
        ]
        already = set(candidates)
        # Spend the remaining budget on shorter overlapping choices, with
        # even distribution across the entire text rather than its prefix.
        for width in list(reversed(widths)):
            remaining = max_candidates - len(candidates)
            if remaining <= 0:
                break
            available = n - width + 1
            quota = min(available, remaining)
            if quota <= 0:
                continue
            starts = ([0] if quota == 1 else
                      [i * (available - 1) // (quota - 1)
                       for i in range(quota)])
            for start in starts:
                candidate = (start, width)
                if candidate not in already:
                    candidates.append(candidate)
                    already.add(candidate)
        for width in list(reversed(widths)):
            for start in range(n - width + 1):
                if len(candidates) >= max_candidates:
                    break
                candidate = (start, width)
                if candidate not in already:
                    candidates.append(candidate)
                    already.add(candidate)
            if len(candidates) >= max_candidates:
                break

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for start, width in candidates:
        begin, finish = words[start].start(), words[start + width - 1].end()
        quote = source[begin:finish]
        if len(quote.strip()) < 2 or quote in seen:
            continue
        seen.add(quote)
        rows.append({"id": "s" + str(len(rows)), "quote": quote,
                     "start": begin, "end": finish})
        if len(rows) >= max_candidates:
            break
    return rows


# The short model may promote a conditional arrival phrase to a second
# launch action. Keep original source IDs stable while excluding such phrases
# from executable action ownership.
_SPACE_ARRIVAL_CONDITION = re.compile(
    r"우주(?:로|에)\s*(?:나가면|도착하면|진입하면|이동하면)|"
    r"\b(?:when|once|after)\s+(?:the\s+)?"
    r"(?:player|ship|craft|vehicle|you)\s+"
    r"(?:reach(?:es)?|enter(?:s)?|arriv(?:e|es)|travel(?:s)?|go(?:es)?)"
    r"\s+(?:to|into|in|at)?\s*(?:space|orbit)\b",
    re.I,
)
_INDEPENDENT_SPACE_DEPARTURE = re.compile(
    r"우주(?:로|에)\s*(?:나가(?:ㄹ|는|자|기|고)|나갈|출발|진입|이동|비행|발사)|"
    r"\b(?:launch|depart|travel|fly|enter|go)\s+(?:to|into)?\s*"
    r"(?:space|orbit)\b", re.I,
)
_CLAIM_SPACE_DEPARTURE = re.compile(
    r"\b(?:travel|launch|depart|fly|enter|go)\b.{0,65}"
    r"\b(?:space|orbit)\b|"
    r"\b(?:space|orbit)\b.{0,50}\b(?:launch|depart|travel)\b|"
    r"우주(?:로|에)\s*(?:출발|발사|진입|이동|나가)",
    re.I,
)


def action_claims_unowned_departure(source: str, action: str) -> bool:
    """A WHEN-ARRIVED condition is not an independent travel command."""
    source = str(source or "")
    if not _SPACE_ARRIVAL_CONDITION.search(source):
        return False
    remainder = _SPACE_ARRIVAL_CONDITION.sub(" ", source)
    return (not _INDEPENDENT_SPACE_DEPARTURE.search(remainder)
            and bool(_CLAIM_SPACE_DEPARTURE.search(str(action or ""))))


def eligible_atomic_action_spans(source: str) -> list[dict[str, str]]:
    """Exclude standalone conditions without renumbering source anchors."""
    spans = indexed_source_spans(source)
    if not _SPACE_ARRIVAL_CONDITION.search(source):
        return spans
    if _INDEPENDENT_SPACE_DEPARTURE.search(
        _SPACE_ARRIVAL_CONDITION.sub(" ", source)
    ):
        return spans
    return [
        row for row in spans
        if not _SPACE_ARRIVAL_CONDITION.fullmatch(row["quote"].strip())
    ]


def validate_atomic_system_ownership(
    actions: list[dict[str, str]], systems: Any, *, original_prompt: str,
) -> None:
    """Require each ONE-system author response to implement its OWN source.

    Independent source-ID calls already establish provenance by their call
    boundary. Filtering their names afterward with a broad retrieval query
    silently discarded legitimate foreign-language/novel gameplay. Check
    actual server/outcome semantics per child before preserving the bundle;
    full Luau, security and game tests still run later.
    """
    from .semantic_preservation import source_outcome_conflicts
    from .request_semantics import request_semantic_errors

    if (not isinstance(systems, list) or len(systems) != len(actions)
            or not all(isinstance(row, dict) for row in systems)):
        raise SourceActionBindingError("ATOMIC_SYSTEM_OWNER_COUNT_INVALID")
    for index, (action, system) in enumerate(zip(actions, systems)):
        server = str(system.get("server_behavior") or "")
        outcome = str(system.get("observable_result") or "")
        if len(server.strip()) < 24 or len(outcome.strip()) < 18:
            raise SourceActionBindingError(
                "ATOMIC_SYSTEM_GAMEPLAY_INCOMPLETE: " + str(index))
        # Both the exact user quote and the anchored authored interpretation
        # matter. A server may mention the parent facet while implementing an
        # unrelated second child. This rejects that silent coverage loss.
        errors = [
            *source_intent_conflicts(action["source_quote"], server),
            *source_intent_conflicts(action["action"], server),
            *source_outcome_conflicts(action["source_quote"], outcome),
            *source_outcome_conflicts(action["action"], outcome),
            *request_semantic_errors(system, original_prompt),
        ]
        if errors:
            raise SourceActionBindingError(
                "ATOMIC_SYSTEM_OWNED_ACTION_NOT_IMPLEMENTED: "
                + str(index) + ": " + "; ".join(dict.fromkeys(errors)))


def verify_or_bind_actions(router: Any, source: str, actions: Any,
                           *, missing_obligations=(),
                           require_complete: bool = True,
                           max_actions: int = 3) -> list[dict[str, str]]:
    """Preserve the model's action descriptions; rebind only invalid quotes.

    Do not repeat game design or silently substitute the whole clause for
    unrelated or invented actions. Require a complete, unique mapping to
    immutable source spans and independently re-run semantic conflict checks.
    """
    if not 2 <= max_actions <= 6:
        raise SourceActionBindingError("ATOMIC_ACTION_BOUND_INVALID")
    if not isinstance(actions, list) or not 2 <= len(actions) <= max_actions:
        raise SourceActionBindingError(
            "ATOMIC_ACTION_DECOMPOSITION_INVALID: 2-" +
            str(max_actions) + " actions required")
    normalized = []
    seen_actions = set()
    ungrounded = False
    quotes = set()
    eligible_spans = eligible_atomic_action_spans(source)
    source_ids = {row["id"]: row["quote"] for row in eligible_spans}
    for row in actions:
        if not isinstance(row, dict):
            raise SourceActionBindingError("ATOMIC_ACTION_DECOMPOSITION_INVALID: action object required")
        action = row.get("action")
        supplied_id = row.get("source_id")
        if not isinstance(action, str) or not 8 <= len(action.strip()) <= 220:
            raise SourceActionBindingError(
                "ATOMIC_ACTION_DECOMPOSITION_INVALID: action text required"
            )
        # Diagnose a conditional-only travel claim before checking candidate
        # membership. The model can return a stale source ID (s11), and the
        # bounded action reselector needs this specific repairable failure.
        if action_claims_unowned_departure(source, action):
            raise SourceActionBindingError(
                "ATOMIC_CONDITIONAL_PROMOTED_TO_ACTION: a 'when in space' "
                "precondition is not a second space travel mechanic"
            )
        if supplied_id is not None and supplied_id not in source_ids:
            raise SourceActionBindingError(
                "ATOMIC_ACTION_SOURCE_ID_NOT_IN_ORIGINAL_TEXT"
            )
        quote = (source_ids[supplied_id] if supplied_id is not None
                 else row.get("source_quote"))
        key = " ".join(action.casefold().split())
        if key in seen_actions:
            raise SourceActionBindingError("ATOMIC_ACTION_DECOMPOSITION_INVALID: duplicate gameplay action")
        seen_actions.add(key)
        valid_quote = (isinstance(quote, str) and len(quote.strip()) >= 2
                       and quote.strip() in source and quote.strip() not in quotes)
        ungrounded |= not valid_quote
        if valid_quote:
            quotes.add(quote.strip())
        normalized.append({"source_quote": quote.strip() if valid_quote else "",
                           "action": action.strip()})

    if ungrounded:
        # A valid action/source owner is immutable. Only missing/duplicated
        # quotations are rebound; otherwise even correct earlier facets
        # become mutable after a single bad model copy.
        missing = [i for i, row in enumerate(normalized)
                   if not row["source_quote"]]
        occupied = {row["source_quote"] for row in normalized
                    if row["source_quote"]}
        candidates = [row for row in eligible_spans
                      if row["quote"] not in occupied]
        by_id = {row["id"]: row["quote"] for row in candidates}
        if len(by_id) < len(missing):
            raise SourceActionBindingError("ATOMIC_SOURCE_NO_DISTINCT_CANDIDATES")
        schema = {"type": "object", "properties": {"bindings": {
            "type": "array", "minItems": len(missing), "maxItems": len(missing),
            "items": {"type": "object", "properties": {
                "action_index": {"type": "integer", "enum": missing},
                "source_id": {"type": "string", "enum": list(by_id)},
            }, "required": ["action_index", "source_id"], "additionalProperties": False}}},
            "required": ["bindings"], "additionalProperties": False}
        response = router.complete_json(
            "SOURCE OWNERSHIP REPAIR ONLY. Match only the listed UNBOUND "
            "existing gameplay actions to original user-text span IDs. "
            "Return JSON {bindings:[{action_index,source_id}]}. Never "
            "rewrite an action or change an already verified binding. "
            "Do not invent a quote or game system. Each listed action index "
            "must occur once and each selected span must be distinct. "
            "JSON only.\n" + json.dumps({
                "original_source": source,
                "unbound_actions": [{"action_index": i, "action": normalized[i]["action"]}
                                    for i in missing],
                "retained_verified_owners": [
                    {"action_index": i, "source_quote": row["source_quote"]}
                    for i, row in enumerate(normalized) if row["source_quote"]],
                "candidate_source_spans": [
                    {"id": row["id"], "quote": row["quote"]} for row in candidates],
                "coverage_issues_for_context_only": list(missing_obligations)[:3],
            }, ensure_ascii=False),
            role="planner", temperature=0.0, max_tokens=400,
            json_schema=schema,
        )
        bindings = response.get("bindings") if isinstance(response, dict) else None
        if not isinstance(bindings, list) or len(bindings) != len(missing):
            raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INCOMPLETE")
        seen_indexes, seen_ids = set(), set()
        for binding in bindings:
            if not isinstance(binding, dict):
                raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INVALID")
            index, identifier = binding.get("action_index"), binding.get("source_id")
            if (type(index) is not int or index not in missing
                    or index in seen_indexes or identifier not in by_id
                    or identifier in seen_ids):
                raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INVALID")
            seen_indexes.add(index)
            seen_ids.add(identifier)
            normalized[index]["source_quote"] = by_id[identifier]
        if seen_indexes != set(missing):
            raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INCOMPLETE")

    # A source-anchored action cannot silently introduce monetization or an
    # unrequested participant. This is checked BEFORE model server authoring;
    # previously an unrelated action label could pass source ID binding.
    from .request_semantics import request_semantic_errors
    for row in normalized:
        unsolicited = request_semantic_errors(row["action"], source)
        if unsolicited:
            raise SourceActionBindingError(
                "ATOMIC_SOURCE_UNREQUESTED_ACTION: " +
                "; ".join(unsolicited),
            )
    if len({row["source_quote"] for row in normalized}) != len(normalized):
        raise SourceActionBindingError("ATOMIC_SOURCE_QUOTES_NOT_DISTINCT")
    for row in normalized:
        if row["source_quote"] not in source:
            raise SourceActionBindingError("ATOMIC_SOURCE_QUOTE_NOT_ANCHORED")
        if source_intent_conflicts(row["source_quote"], row["action"],
                                   require_implementation=False):
            raise SourceActionBindingError(
                "ATOMIC_SOURCE_ACTION_SEMANTIC_MISMATCH: " + row["source_quote"])
    if require_complete and source_intent_conflicts(
            source, " ".join(row["action"] for row in normalized),
            require_implementation=False):
        raise SourceActionBindingError(
            "ATOMIC_SOURCE_COLLECTIVE_ACTIONS_DROPPED")
    return normalized
