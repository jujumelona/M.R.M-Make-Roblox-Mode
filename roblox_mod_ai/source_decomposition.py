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


def source_chunks(statement: str, *, max_chars: int = 11,
                  max_chunks: int = 48) -> list[str]:
    """Partition a clause by original word boundaries; never drop or invent words.

    Chunks are deliberately short so adjacent, separately implemented actions
    are not silently fused into a single model-generated module. Chunking
    remains lossless and uses only original word boundaries, not genre keywords. A short
    compositional clause receives at least two independently owned chunks.
    """
    source = clean(statement)
    words = source.split(" ")
    if len(words) < 2:
        return [source]
    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        if current and len(" ".join(current + [word])) > max_chars:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
        if _JOINER.search(word) and len(" ".join(current)) >= 7:
            pieces.append(" ".join(current))
            current = []
    if current:
        pieces.append(" ".join(current))
    # Force 2 separate implementation owners for a connector-based request.
    if len(pieces) == 1 and is_composite(source) and len(words) > 1:
        mid = max(1, len(words) // 2)
        pieces = [" ".join(words[:mid]), " ".join(words[mid:])]
    # Do not let one-word particles become a standalone mechanic. The previous
    # span consumes it instead, keeping all source characters covered.
    combined: list[str] = []
    for piece in pieces:
        if combined and _JOINER.fullmatch(piece):
            # Redistribute the last two meaningful words into a standalone
            # action span before attaching the dangling connector. Otherwise
            # a conjunction can force independent actions into one chunk.
            words = combined[-1].split(" ")
            if len(words) >= 4:
                combined[-1] = " ".join(words[:-2])
                combined.append(" ".join(words[-2:] + [piece]))
            else:
                combined[-1] += " " + piece
        elif combined and len(piece) < 3:
            combined[-1] += " " + piece
        else:
            combined.append(piece)
    if (len(combined) > max_chunks or
            clean(" ".join(combined)) != source or
            span_coverage(source, combined) < .99):
        raise ValueError("Host cannot source-anchor all requested text into bounded chunks")
    return combined


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
        if source_intent_conflicts(source, intent + " " + query):
            continue
        if (chunk_id not in allowed or chunk_id in result or
                not 5 <= len(intent) <= 180 or opaque_label or
                not 8 <= len(query) <= 160 or
                not re.search(r"[a-zA-Z]{3,}", query)):
            continue
        result[chunk_id] = {"intent": intent, "english_query": query}
    return result
