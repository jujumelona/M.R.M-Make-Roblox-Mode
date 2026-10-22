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
        priorities = list(reversed(widths))
        base, extra = divmod(max_candidates, len(priorities))
        for index, width in enumerate(priorities):
            available = n - width + 1
            quota = min(available, base + (index < extra))
            if quota <= 0:
                continue
            if quota == 1:
                starts = [0 if available == 1 else (available - 1) // 2]
            else:
                starts = [i * (available - 1) // (quota - 1)
                          for i in range(quota)]
            candidates.extend((start, width) for start in starts)

        # If some widths offered fewer candidates than their quota, fill
        # unused slots from real source windows, never invented strings.
        already = set(candidates)
        for width in priorities:
            for start in range(n - width + 1):
                if len(candidates) >= max_candidates:
                    break
                if (start, width) not in already:
                    candidates.append((start, width))
                    already.add((start, width))
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


def verify_or_bind_actions(router: Any, source: str, actions: Any,
                           *, missing_obligations=()) -> list[dict[str, str]]:
    """Preserve the model's action descriptions; rebind only invalid quotes.

    Do not repeat game design or silently substitute the whole clause for
    unrelated or invented actions. Require a complete, unique mapping to
    immutable source spans and independently re-run semantic conflict checks.
    """
    if not isinstance(actions, list) or not 2 <= len(actions) <= 3:
        raise SourceActionBindingError(
            "ATOMIC_ACTION_DECOMPOSITION_INVALID: 2-3 actions required")
    normalized = []
    seen_actions = set()
    ungrounded = False
    quotes = set()
    source_ids = {row["id"]: row["quote"] for row in indexed_source_spans(source)}
    for row in actions:
        if not isinstance(row, dict):
            raise SourceActionBindingError("ATOMIC_ACTION_DECOMPOSITION_INVALID: action object required")
        action = row.get("action")
        supplied_id = row.get("source_id")
        if supplied_id is not None and supplied_id not in source_ids:
            raise SourceActionBindingError("ATOMIC_ACTION_SOURCE_ID_NOT_IN_ORIGINAL_TEXT")
        quote = (source_ids[supplied_id] if supplied_id is not None
                 else row.get("source_quote"))
        if not isinstance(action, str) or not 8 <= len(action.strip()) <= 220:
            raise SourceActionBindingError("ATOMIC_ACTION_DECOMPOSITION_INVALID: action text required")
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
        candidates = [row for row in indexed_source_spans(source)
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

    if len({row["source_quote"] for row in normalized}) != len(normalized):
        raise SourceActionBindingError("ATOMIC_SOURCE_QUOTES_NOT_DISTINCT")
    for row in normalized:
        if row["source_quote"] not in source:
            raise SourceActionBindingError("ATOMIC_SOURCE_QUOTE_NOT_ANCHORED")
        if source_intent_conflicts(row["source_quote"], row["action"],
                                   require_implementation=False):
            raise SourceActionBindingError(
                "ATOMIC_SOURCE_ACTION_SEMANTIC_MISMATCH: " + row["source_quote"])
    if source_intent_conflicts(
            source, " ".join(row["action"] for row in normalized),
            require_implementation=False):
        raise SourceActionBindingError(
            "ATOMIC_SOURCE_COLLECTIVE_ACTIONS_DROPPED")
    return normalized
