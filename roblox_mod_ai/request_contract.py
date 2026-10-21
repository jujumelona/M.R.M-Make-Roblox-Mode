"""Host-side audit of user-request decomposition.

A keyword hit is evidence of a *candidate* game system, not coverage of the
whole request. Compound clauses require individually source-anchored behavior
spans; this contract is checked again when a saved plan is loaded or built.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .semantic_preservation import source_intent_conflicts


def clean(text: str) -> str:
    return " ".join(str(text).split()).strip()


def clauses(prompt: str) -> list[str]:
    # These are presentation separators only; never assume their absence means
    # the user asked for a single gameplay behavior.
    pieces = re.split(r"(?:\s*[,;，；\n]\s*|\s+(?:그리고|및|또한|and)\s+)", prompt)
    return [part for item in pieces if (part := clean(item))]


def is_composite(statement: str) -> bool:
    """Conservative uncertainty detector, not a game-genre keyword taxonomy."""
    text = clean(statement)
    # Short requests can also combine separate actions without punctuation:
    # "구매해서 조립하고 우주로 간다" must NOT be certified by "구매".
    action_connectors = re.findall(
        r"[가-힣]{2,}(?:해서|하고|하며|으며|면서|거나|고|며)(?=\s|$)",
        text,
    )
    return (len(text) >= 85 or len(action_connectors) >= 2 or
            (len(text) >= 52 and bool(re.search(
                r"(?:할\s*수\s*있고|할\s*수\s*있으며|하(?:고|면서)|그러고|그렇게해서|그리고|및|등으로|and|then)",
                text, flags=re.IGNORECASE))))


def span_coverage(statement: str, spans: list[str]) -> float:
    """Fraction of non-whitespace clause characters covered by real source spans."""
    text = clean(statement)
    covered = [False] * len(text)
    for span in spans:
        span = clean(span)
        if not span:
            continue
        positions = [m.start() for m in re.finditer(re.escape(span), text)]
        if not positions:
            return 0.0
        # Repeated phrases must correspond to distinct positions where possible.
        pos = max(positions, key=lambda idx: sum(not covered[i]
                  for i in range(idx, idx + len(span))))
        for i in range(pos, pos + len(span)):
            covered[i] = True
    significant = [i for i, ch in enumerate(text) if ch.isalnum()]
    return (sum(covered[i] for i in significant) / len(significant)
            if significant else 0.0)


def validate_model_behaviors(clause: str, behaviors: list[dict[str, Any]]) -> bool:
    """Only accept atomic, distinct, exact-source behaviors covering the clause."""
    if not isinstance(behaviors, list) or not 2 <= len(behaviors) <= 24:
        return False
    source = clean(clause)
    seen: set[str] = set()
    spans: list[str] = []
    for item in behaviors:
        if not isinstance(item, dict):
            return False
        span = clean(item.get("source_span", ""))
        intent = clean(item.get("intent", ""))
        query = clean(item.get("english_query", ""))
        if (len(span) < 3 or len(span) > 100 or
                len(span) >= len(source) * .75 or span not in source or
                len(intent) < 5 or len(intent) > 180 or
                not re.search(r"[A-Za-z]{3,}", query) or len(query) > 160 or
                span in seen or source_intent_conflicts(span, intent + " " + query)):
            return False
        seen.add(span)
        spans.append(span)
    return span_coverage(source, spans) >= .78



def implementation_facets(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return distinct implementation obligations, excluding duplicate genre labels.

    Keyword facets (e.g. 'shop') are retrieval/classification hints. Once the
    same exact user requirement is owned by a source-anchored atomic intent,
    counting that keyword again as a separately authored gameplay requirement
    makes small-model architecture validation reject otherwise fully covered
    designs. Never discard an uncovered generic facet, an atom, or query-only
    model research; those remain independently accountable.
    """
    facets = ledger.get("facets", [])
    if not isinstance(facets, list):
        return []
    # Query expansion only gathers API/documentation evidence. It must
    # never add an independent gameplay obligation or server state writer,
    # even when the plan was persisted by an older RMM version.
    facets = [f for f in facets
              if isinstance(f, dict) and not f.get("model_query_only")]
    if ledger.get("decomposition_method") not in ("source_anchored_model", "source_anchored_host"):
        return facets
    requirements = {
        entry["id"]: clean(entry.get("statement", ""))
        for entry in ledger.get("requirements", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    atom_owned: set[str] = set()
    facet_by_id = {
        f["id"]: f for f in facets
        if isinstance(f, dict) and isinstance(f.get("id"), str)
    }
    for atom in ledger.get("atomic_intents", []):
        if not isinstance(atom, dict):
            continue
        rid, fid = atom.get("requirement_id"), atom.get("facet_id")
        facet = facet_by_id.get(fid)
        if (rid in requirements and facet and
                clean(atom.get("source_span", "")) == requirements[rid] and
                clean(facet.get("source_span", "")) == requirements[rid] and
                rid in facet.get("requirements", [])):
            atom_owned.add(rid)
    result: list[dict[str, Any]] = []
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        owners = facet.get("requirements", [])
        taxonomy_duplicate = (
            not facet.get("source_span") and
            not facet.get("model_query_only") and
            isinstance(owners, list) and bool(owners) and
            set(owners).issubset(atom_owned)
        )
        if not taxonomy_duplicate:
            result.append(facet)
    return result


def ledger_complete(prompt: str, ledger: dict[str, Any]) -> bool:
    """Recheck saved plans independent of the planner's 'unmatched' bookkeeping."""
    if not isinstance(ledger, dict) or ledger.get("original_prompt") != prompt:
        return False
    if ledger.get("request_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest():
        return False
    requirements = ledger.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        return False
    ids: set[str] = set()
    fragments = clauses(prompt)
    statements = []
    for item in requirements:
        if not isinstance(item, dict) or item.get("source") != "user_prompt":
            return False
        rid, statement = item.get("id"), clean(item.get("statement", ""))
        if not isinstance(rid, str) or not re.fullmatch(r"req-\d{3,}", rid):
            return False
        if rid in ids or not statement or not any(statement in c for c in fragments):
            return False
        ids.add(rid)
        statements.append(statement)
    for fragment in fragments:
        pieces = [s for s in statements if s in fragment]
        if not pieces:
            return False
        if is_composite(fragment):
            if (len(pieces) < 2 or span_coverage(fragment, pieces) < .78 or
                    ledger.get("decomposition_method") not in ("source_anchored_model", "source_anchored_host")):
                return False
        elif fragment not in pieces and span_coverage(fragment, pieces) < .95:
            return False
    intents = ledger.get("atomic_intents", [])
    if ledger.get("decomposition_method") in ("source_anchored_model", "source_anchored_host"):
        if not intents or not isinstance(intents, list):
            return False
        mapped = {x.get("requirement_id") for x in intents if isinstance(x, dict)}
        # Model-extracted source spans each have an independent acceptance facet.
        if not mapped.issubset(ids):
            return False
        facet_ids = {x.get("id") for x in ledger.get("facets", []) if isinstance(x, dict)}
        if any(x.get("facet_id") not in facet_ids for x in intents):
            return False
        # A host fallback carries the *literal source*, not a verified model
        # interpretation. Persisted plans must not be able to relabel an
        # unclassified requirement as independently model-certified.
        if ledger.get("decomposition_method") == "source_anchored_host":
            fallback_ids = set(ledger.get("classification_unverified") or [])
            if not fallback_ids:
                return False
            fallback_intents = [x for x in intents
                                if x.get("classification_origin") == "host_source_only"]
            if {x.get("chunk_id") for x in fallback_intents} != fallback_ids:
                return False
            if any(
                not clean(x.get("source_span", "")) or
                clean(x.get("source_span", "")) not in str(x.get("intent", "")) or
                not str(x.get("english_query", "")).startswith("Roblox gameplay scripting for ")
                for x in fallback_intents
            ):
                return False
    if ledger.get("decomposition_pending"):
        return False
    return not ledger.get("unmatched_requirements") and not ledger.get("unimplemented_facets")
