"""Bounded source-anchored decomposition recovery for smaller local models.

The host, not the LLM, owns the original text and the number of spans that
must be implemented. This removes the brittle instruction to make a 9B model
guess every exact quote and cover the whole long Korean prompt in one JSON call.
"""
from __future__ import annotations

import re
from typing import Any

from .request_contract import clean, is_composite, span_coverage
from .semantic_preservation import source_intent_conflicts

# These are general clause joiners, NOT a vocabulary of genres or mechanics.
_JOINER = re.compile(
    r"(?:해서|하고|하며|으면서|면서|으므로|있고|거나|등으로|그리고|또한|및|and|then)$",
    re.IGNORECASE,
)


def source_chunks(statement: str, *, max_chars: int = 22,
                  max_chunks: int = 48) -> list[str]:
    """Losslessly partition only at EXPLICIT clause connectors.

    max_chars is a hint for the subsequent model context, not permission to
    manufacture independent actions by cutting after N characters. In Korean
    this previously created fake obligations like "구매 등으로", or separated
    a verb from the object whose world state it must change.

    If a request offers no provable lexical boundary, return the entire
    source as one still-composite clause. A later semantic model must
    decompose it, rather than falsely certifying half-sentences.
    """
    source = clean(statement)
    if not source:
        return []
    if max_chunks < 1:
        raise ValueError("Host source partition has no available output slots")
    words = source.split(" ")
    if len(words) < 2:
        return [source]
    chunks: list[str] = []
    current: list[str] = []
    # Only full predicates/conjunctions are conservative text boundaries.
    # A means-connector ("등으로", "using") applies to the FOLLOWING action;
    # an adjective or suffix is not a separate implementation obligation.
    boundary = re.compile(
        r"(?:해서|하고|하며|으면서|면서|있고|거나|그리고|또한|및)$|"
        r"^(?:and|then)$", re.IGNORECASE)
    for idx, word in enumerate(words):
        current.append(word)
        # Never emit a dangling conjunction or a grammatical modifier as a
        # source-owned game system. A right-hand phrase must exist.
        if (idx + 1 < len(words) and
                boundary.search(word) and
                len(current) >= 2 and
                len(" ".join(words[idx+1:]).strip()) >= 3):
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    if (len(chunks) > max_chunks or
            clean(" ".join(chunks)) != source or
            span_coverage(source, chunks) < .99):
        raise ValueError("Host cannot source-anchor all requested text")
    return chunks


def classification_context(
    all_chunks: list[dict[str, str]],
    selected: list[dict[str, str]],
    clauses: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Keep each exact source span while adding bounded adjacent context.

    Arbitrary byte/word boundaries are NOT independent semantic clauses. A
    fragment like "can ... by purchasing" or a dangling conjunction needs
    adjacent text to describe its role without inventing a standalone system.
    Only the selected chunk IDs may appear in the model's response.
    """
    by_id = {item["id"]: item["statement"] for item in clauses}
    locations = {entry["chunk_id"]: index for index, entry in enumerate(all_chunks)}
    result = []
    for entry in selected:
        i = locations[entry["chunk_id"]]
        before = all_chunks[i-1] if i else None
        after = all_chunks[i+1] if i+1 < len(all_chunks) else None
        result.append({
            "chunk_id": entry["chunk_id"],
            "source_span": entry["source_span"],
            "previous": (before["source_span"][:100]
                         if before and before["clause_id"] == entry["clause_id"]
                         else ""),
            "next": (after["source_span"][:100]
                     if after and after["clause_id"] == entry["clause_id"]
                     else ""),
            "source_clause": by_id.get(entry["clause_id"], "")[:360],
        })
    return result


def valid_chunk_classification(raw: Any, expected: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Only complete, unique descriptions of EXACT requested chunk IDs pass."""
    if not isinstance(raw, dict) or not isinstance(raw.get("behaviors"), list):
        return {}
    allowed = {entry["chunk_id"] for entry in expected}
    result: dict[str, dict[str, str]] = {}
    for row in raw["behaviors"]:
        if not isinstance(row, dict):
            continue
        chunk_id = row.get("chunk_id")
        intent = clean(row.get("intent", ""))
        query = clean(row.get("english_query", ""))
        # A model-internal label (proposal 13: gameplay_mode_capability)
        # is not an implementation intent. Require described gameplay rather
        # than treating category names as proof that a request was decomposed.
        opaque_label = bool(re.fullmatch(
            r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", intent, re.IGNORECASE))
        source = next((item["source_span"] for item in expected
                       if item["chunk_id"] == chunk_id), "")
        if source_intent_conflicts(source, intent + " " + query, require_implementation=False):
            continue
        if (chunk_id not in allowed or chunk_id in result or
                not 5 <= len(intent) <= 180 or opaque_label or
                not 8 <= len(query) <= 160 or
                not re.search(r"[a-zA-Z]{3,}", query)):
            continue
        result[chunk_id] = {"intent": intent, "english_query": query}
    return result
