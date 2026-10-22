"""Source-grounded fallback for ambiguous cross-language system ownership.

Fast lexical scope remains the default. If it rejects every candidate from a
source-scoped local model completion, the host can ask for a small structured
attribution verdict. The answer is not trusted on its own: require an actual
substring from the unmodified user clause AND a verbatim supporting server
transition from the candidate. The existing complete semantic and engine
validators still run afterward. Never fabricate source ownership from a
translated retrieval query.
"""
from __future__ import annotations

from typing import Any


SOURCE_OWNERSHIP_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "bindings": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "owned": {"type": "boolean"},
                    "source_quote": {"type": "string", "maxLength": 200},
                    "server_quote": {"type": "string", "maxLength": 400},
                },
                "required": ["index", "owned", "source_quote", "server_quote"],
            },
        },
    },
    "required": ["bindings"],
}


class SourceOwnershipReviewError(ValueError):
    """The model's claimed attribution is ungrounded or incomplete."""


def ground_source_ownership(
    draft: dict[str, Any], verdict: Any, *, source_clause: str,
) -> tuple[dict[str, Any], list[str]]:
    """Return scoped systems only when every model claim is directly quoted.

    This is an evidence check, not a guarantee of semantic correctness.
    Systems are never rewritten, and rejection fails closed.
    """
    systems = draft.get("systems")
    if not isinstance(systems, list) or not 1 <= len(systems) <= 3:
        raise SourceOwnershipReviewError(
            "SOURCE_OWNER_REVIEW_INVALID: expected 1-3 candidate systems")
    if not isinstance(verdict, dict) or not isinstance(verdict.get("bindings"), list):
        raise SourceOwnershipReviewError(
            "SOURCE_OWNER_REVIEW_INVALID: model omitted bindings")
    bindings = verdict["bindings"]
    if len(bindings) != len(systems):
        raise SourceOwnershipReviewError(
            "SOURCE_OWNER_REVIEW_INVALID: every candidate needs a verdict")
    seen: set[int] = set()
    accepted: list[int] = []
    rejected: list[str] = []
    for entry in bindings:
        if not isinstance(entry, dict):
            raise SourceOwnershipReviewError(
                "SOURCE_OWNER_REVIEW_INVALID: binding must be an object")
        index = entry.get("index")
        if (type(index) is not int or index in seen
                or not 0 <= index < len(systems)):
            raise SourceOwnershipReviewError(
                "SOURCE_OWNER_REVIEW_INVALID: duplicate or unknown index")
        seen.add(index)
        if type(entry.get("owned")) is not bool:
            raise SourceOwnershipReviewError(
                "SOURCE_OWNER_REVIEW_INVALID: owned must be boolean")
        row = systems[index]
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise SourceOwnershipReviewError(
                "SOURCE_OWNER_REVIEW_INVALID: malformed candidate")
        if not entry["owned"]:
            rejected.append(row["name"])
            continue
        source_quote = entry.get("source_quote")
        server_quote = entry.get("server_quote")
        if (not isinstance(source_quote, str)
                or not source_quote.strip()
                or source_quote.strip() not in source_clause
                or not isinstance(server_quote, str)
                or len(server_quote.strip()) < 16
                or server_quote.strip().casefold()
                   not in str(row.get("server_behavior") or "").casefold()):
            raise SourceOwnershipReviewError(
                "SOURCE_OWNER_REVIEW_UNGROUNDED: claimed source ownership "
                "must quote the actual user clause and candidate server rule")
        accepted.append(index)
    if not accepted:
        raise SourceOwnershipReviewError(
            "SOURCE_OWNER_REVIEW_REJECTED: no candidate implements "
            "the current source clause")
    accepted_set = set(accepted)
    kept = [system for idx, system in enumerate(systems) if idx in accepted_set]
    # The full source intent / outcome / security contracts run after this.
    return dict(draft, systems=kept), rejected
