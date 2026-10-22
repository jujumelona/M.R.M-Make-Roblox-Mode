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
    words = list(re.finditer(r"\S+", source))
    if not words:
        raise SourceActionBindingError("ATOMIC_SOURCE_TEXT_REQUIRED")
    # Contiguous WORD windows, with byte offsets retained. This generalizes
    # to Korean, English and mixed requests without a list of gameplay verbs.
    rows = []
    seen = set()
    for width in range(1, min(max_width, len(words)) + 1):
        for start in range(len(words) - width + 1):
            span = source[words[start].start():words[start + width - 1].end()]
            if len(span.strip()) < 2 or span in seen:
                continue
            seen.add(span)
            rows.append({"id": "s" + str(len(rows)), "quote": span,
                         "start": words[start].start(),
                         "end": words[start + width - 1].end()})
            if len(rows) >= max_candidates:
                return rows
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
    for row in actions:
        if not isinstance(row, dict):
            raise SourceActionBindingError("ATOMIC_ACTION_DECOMPOSITION_INVALID: action object required")
        action = row.get("action")
        quote = row.get("source_quote")
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
        candidates = indexed_source_spans(source)
        by_id = {row["id"]: row["quote"] for row in candidates}
        schema = {"type": "object", "properties": {"bindings": {
            "type": "array", "minItems": len(normalized), "maxItems": len(normalized),
            "items": {"type": "object", "properties": {
                "action_index": {"type": "integer", "minimum": 0, "maximum": len(normalized)-1},
                "source_id": {"type": "string", "enum": list(by_id)},
            }, "required": ["action_index", "source_id"], "additionalProperties": False}}},
            "required": ["bindings"], "additionalProperties": False}
        response = router.complete_json(
            "SOURCE OWNERSHIP ONLY. Match EACH existing gameplay action to ONE "
            "exact ORIGINAL user-text span ID from candidates. Return JSON "
            "{bindings:[{action_index,source_id}]}. Do not rewrite the action, "
            "do not invent a quote, translate source spans, or add game systems. "
            "Each action index occurs once; choose distinct spans when the "
            "actions are independent. A descriptive error label is never "
            "the original user text. JSON only.\n" + json.dumps({
                "original_source": source,
                "actions": [{"action_index": i, "action": row["action"]}
                            for i, row in enumerate(normalized)],
                "candidate_source_spans": [
                    {"id": row["id"], "quote": row["quote"]} for row in candidates],
                "coverage_issues_for_context_only": list(missing_obligations)[:3],
            }, ensure_ascii=False),
            role="planner", temperature=0.0, max_tokens=400,
            json_schema=schema,
        )
        bindings = response.get("bindings") if isinstance(response, dict) else None
        if not isinstance(bindings, list) or len(bindings) != len(normalized):
            raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INCOMPLETE")
        seen_indexes, seen_ids = set(), set()
        for binding in bindings:
            if not isinstance(binding, dict):
                raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INVALID")
            index, identifier = binding.get("action_index"), binding.get("source_id")
            if (type(index) is not int or index < 0 or index >= len(normalized)
                    or index in seen_indexes or identifier not in by_id
                    or identifier in seen_ids):
                raise SourceActionBindingError("ATOMIC_SOURCE_ID_MAPPING_INVALID")
            seen_indexes.add(index)
            seen_ids.add(identifier)
            normalized[index]["source_quote"] = by_id[identifier]
        if len(seen_indexes) != len(normalized):
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
