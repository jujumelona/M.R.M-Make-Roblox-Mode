"""Source-anchored ownership for oversized small-model facet responses.

The original source ledger, not a model's choice of system names, defines
which feature a generated system can belong to. Filter clearly foreign named
systems BEFORE Luau/Roblox validation; never invent gameplay or turn an
unrouted player action into a passive service.
"""
from __future__ import annotations

import re
from typing import Any


_COMMON = {
    "roblox", "game", "gameplay", "system", "implement", "implementing",
    "create", "creating", "using", "use", "support", "enable", "allow",
    "with", "from", "into", "after", "then", "and", "for", "that",
    "the", "this", "other", "to", "on", "in", "a", "of", "or",
    "player", "players", "requested", "mechanic", "mechanics",
    "dedicated", "custom", "multiple", "various",
}


def _ordered_terms(value: str) -> list[str]:
    """Normalize intent and system names without a domain-specific vocabulary.

    Keep order: small models often describe the *actual* source action first
    and then append adjacent progression context. A flat bag-of-words makes
    those copied adjuncts equally authoritative and misroutes valid mechanics.
    """
    words = re.findall(r"[A-Za-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", value))
    result: list[str] = []
    for raw in words:
        word = raw.lower()
        if word in _COMMON or len(word) < 3:
            continue
        if word.endswith("ation") and len(word) > 8:
            word = word[:-5]
        elif word.endswith("ing") and len(word) > 5:
            word = word[:-3]
        elif word.endswith("ed") and len(word) > 5:
            word = word[:-2]
        elif word.endswith("er") and len(word) > 5:
            word = word[:-2]
        elif word.endswith("s") and len(word) > 4:
            word = word[:-1]
        if word.endswith("e") and len(word) > 4:
            word = word[:-1]
        if word and word not in result:
            result.append(word)
    return result


def _terms(value: str) -> set[str]:
    return set(_ordered_terms(value))


def _source_match_score(owned: set[str], intent: list[str]) -> float:
    """Favor direct source intent over contextual words copied from neighbors."""
    return sum(1.0 / (position + 1) for position, term
               in enumerate(intent) if term in owned)


def scope_semantic_systems(
    raw: dict[str, Any], *, facet: dict[str, Any], all_facets: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Keep only unambiguously source-owned systems from an oversized answer.

    One-system output remains unchanged: normal Roblox/security validators own
    its truth and executability. A multi-system response needs demonstrable
    *name* alignment with the specific ledger facet, stronger than every
    competing facet. Descriptions are excluded from scoring because failed
    local models copy the phrase "space mode" into every unrelated mechanic.
    Ambiguous items are never silently reassigned; if none survives, error.
    """
    systems = raw.get("systems")
    if not isinstance(systems, list) or len(systems) <= 1:
        return raw, []
    target_id = facet.get("id")
    ordered_labels = {
        item.get("id"): _ordered_terms(str(item.get("search_query") or ""))
        for item in all_facets if isinstance(item, dict) and item.get("id")
    }
    labels = {fid: set(words) for fid, words in ordered_labels.items()}
    target = labels.get(target_id, set())
    # A generic shared noun is not proof of ownership. One matching term
    # suffices only if it is unique to this source facet; otherwise require
    # independent evidence from at least two words in the system name.
    foreign_vocabulary = set().union(
        *(words for fid, words in labels.items() if fid != target_id)
    )
    if not target:
        # Multilingual/untranslated ledger facets sometimes contain only a
        # source_span (no English search_query). A single named mechanic with
        # distinct Phase0/Phase1 entries is still clearly ONE facet; keep both
        # unchanged rather than treating normal phases as foreign systems.
        # Distinct names without a comparable source intent remain ambiguous.
        names = [s.get("name") if isinstance(s, dict) else None
                 for s in systems]
        if all(isinstance(name, str) and name.strip() for name in names):
            families = {re.sub(r"(?:Phase|Stage)\d+$", "", name, flags=re.I)
                        for name in names}
            if len(families) == 1:
                return raw, []
        raise ValueError(
            "SCOPED_SYSTEM_UNATTRIBUTED: source facet has no comparable "
            "English intent and unrelated system names cannot be attributed"
        )
    kept: list[dict[str, Any]] = []
    discarded: list[str] = []
    for index, system in enumerate(systems):
        if not isinstance(system, dict):
            raise ValueError("SCOPED_SYSTEM_INVALID: model systems must be objects")
        name = system.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("SCOPED_SYSTEM_INVALID: every system needs a name")
        owned_terms = _terms(name)
        overlap = owned_terms & target
        own_score = _source_match_score(owned_terms, ordered_labels[target_id])
        foreign_score = max(
            (_source_match_score(owned_terms, words)
             for fid, words in ordered_labels.items() if fid != target_id),
            default=0.0,
        )
        independently_supported = (
            len(overlap) >= 2 or bool(overlap - foreign_vocabulary)
        )
        # Equal raw token counts used to reject valid compound systems because
        # other facets' queries repeat source context (e.g. building mentioned
        # in a trade description). Earlier, direct source terms resolve the tie.
        # Do not accept an unowned action merely because a shared word appears.
        if independently_supported and own_score > foreign_score + 1e-9:
            kept.append(system)
        else:
            discarded.append(name)
    if not kept:
        raise ValueError(
            "SCOPED_SYSTEM_UNATTRIBUTED: no distinct named system belongs to "
            f"source facet {target_id}; offered: " + ", ".join(discarded[:16])
        )
    # No transformation of action content, ownership, acceptance or transport.
    # Every kept entry must still pass the full original validators unchanged.
    return dict(raw, systems=kept), discarded
