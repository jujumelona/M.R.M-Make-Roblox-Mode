"""Reconcile model-proposed omitted actions against the immutable effect ledger.

The model may paraphrase an effect already present in the authored plan.
Never treat that paraphrase as a NEW requirement merely because the words
differ. Conversely, do not suppress a genuinely different state transition.
Only *strong*, mechanically supported entailment is collapsed as duplicate.
Ambiguity remains a blocking, unverified scope finding upstream.

This module does NOT attest that an effect is implemented in source code.
"""
from __future__ import annotations

import re
from typing import Any

_WORD = re.compile(r"[a-z]+|[가-힣]+", re.I)
_STOP = frozenset("""
a an the this that these those it its their his her they them and or but
by for from to of in on at as with through after before when where then
is are was were be been being will would should can could must shall
player players player s buyer buyers server server owned own selected current
actual real validated valid corresponding resulting same one new requested
requestedly updated subsequently effective existing successfully successful
""".split())
_ACTIONS = frozenset("""
add remove increase decrease purchase sell upgrade attach detach persist
create destroy extract transfer launch travel equip unequip unlock lock
spawn grant revoke restore build damage heal colonize
""".split())
_ALIASES = {
    "added": "add", "adding": "add", "adds": "add",
    "removed": "remove", "removing": "remove", "removes": "remove",
    "increased": "increase", "increases": "increase", "increasing": "increase",
    "credited": "increase", "credits": "increase", "credit": "increase",
    "gained": "increase", "gains": "increase", "gain": "increase",
    "decreased": "decrease", "decreases": "decrease", "decreasing": "decrease",
    "debited": "decrease", "debits": "decrease", "debit": "decrease",
    "deducted": "decrease", "deducts": "decrease", "deduct": "decrease",
    "subtracted": "decrease", "reduces": "decrease", "reduced": "decrease",
    "purchased": "purchase", "purchasing": "purchase", "purchases": "purchase",
    "bought": "purchase", "buy": "purchase", "buys": "purchase",
    "paid": "purchase", "pay": "purchase",
    "sold": "sell", "selling": "sell", "sells": "sell",
    "upgraded": "upgrade", "upgrades": "upgrade", "upgrading": "upgrade",
    "attached": "attach", "attaches": "attach", "attaching": "attach",
    "detached": "detach", "detaches": "detach",
    "persisted": "persist", "persists": "persist", "saved": "persist",
    "stored": "persist", "created": "create", "creates": "create",
    "destroyed": "destroy", "destroys": "destroy",
    "extracted": "extract", "extracts": "extract",
    "transferred": "transfer", "transfers": "transfer",
    "launched": "launch", "launches": "launch",
    "traveled": "travel", "travels": "travel", "relocated": "travel",
    "equipped": "equip", "equips": "equip",
    "unlocked": "unlock", "unlocks": "unlock",
    "spawned": "spawn", "spawns": "spawn",
    "granted": "grant", "grants": "grant",
    "revoked": "revoke", "revokes": "revoke",
    "restored": "restore", "restores": "restore",
    "built": "build", "building": "build",
    "damaged": "damage", "damages": "damage",
    "healed": "heal", "heals": "heal",
    "colonized": "colonize", "colonizes": "colonize",
    "inventory": "inventory", "inventories": "inventory",
    "funds": "currency", "money": "currency", "coins": "currency",
    "payment": "price", "cost": "price", "costs": "price",
}

def _terms(text: str) -> set[str]:
    result: set[str] = set()
    for word in _WORD.findall(text.casefold()):
        token = _ALIASES.get(word, word)
        if token not in _STOP and len(token) >= 2:
            result.add(token)
    return result

def _documented_effect_rows(effects: list[dict[str, Any]]) -> list[set[str]]:
    rows = []
    for effect in effects:
        if not isinstance(effect, dict) or not isinstance(effect.get("behavior"), str):
            continue
        tokens = _terms(effect["behavior"])
        # Money debited for a priced item is a purchase, without requiring
        # the planner to redundantly say "buy". A sale (money increasing)
        # cannot be converted to a purchase through this inference.
        if ({"decrease", "price", "currency"} <= tokens):
            tokens.add("purchase")
        rows.append(tokens)
    return rows

def already_planned_action(action: str, effects: list[dict[str, Any]]) -> bool:
    """Strong duplicate proof, not fuzzy scoring or a model verdict.

    Every significant term and *each* change verb must be represented.
    Each change verb must be supported by an effect mentioning the same
    subject, preventing a purchase for one item plus an inventory grant
    for an unrelated item from being accidentally combined.
    """
    if not isinstance(action, str) or not action.strip():
        return False
    desired = _terms(action)
    rows = _documented_effect_rows(effects)
    if not rows:
        return False
    available = set().union(*rows)
    if not desired <= available:
        return False
    verbs = desired & _ACTIONS
    if not verbs or len(desired) < 3:
        return False
    # Use specific nouns as an entity anchor; common words referring to
    # storage, money and the general operation are not entity identity.
    generic = {
        "inventory", "currency", "balance", "price", "state", "status",
        "data", "record", "level", "quantity", "amount", "performance",
    }
    anchors = desired - verbs - generic - {"not", "never", "without"}
    if not anchors:
        # Without a subject identity, lexical overlap alone is not proof.
        return False
    for verb in verbs:
        if not any(
            verb in row and (row & anchors)
            and (not ({"not", "never", "without"} & desired)
                 or ({"not", "never", "without"} & row))
            for row in rows
        ):
            return False
    return True

def reconcile_omitted_actions(
    omissions: list[str], effects: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return (still_missing, definitely_already_planned), in source order."""
    missing, duplicates = [], []
    for action in omissions:
        if already_planned_action(action, effects):
            duplicates.append(action)
        else:
            missing.append(action)
    return missing, duplicates

# The model is a *discoverer* of possible omissions, not an authority that
# can extend the original user request. Claims require independent grounding
# in the literal original-language request before becoming blocking omissions.
# This intentionally does not use genre, item, or user-prompt-specific terms.
_GENERIC_CLAIM = frozenset({
    "player", "server", "game", "item", "items", "world", "resource",
    "owned", "state", "inventory", "balance", "price", "quantity", "amount",
    "selected", "request", "rejected", "requests", "change", "changes",
    "effect", "effects", "result", "successful", "success", "action",
    "required", "corresponding", "visible", "visibly", "validated",
    "original", "new", "current", "provided", "theirs",
})

def original_request_supports_action(action: str, original: str) -> bool:
    """Strict positive provenance for a new claimed user obligation.

    A local model cannot create an action by describing a plausible gameplay
    detail not directly present in the original request. Exact original
    phrases are sufficient. Paraphrases require both an action and multiple
    matching subject identifiers. Cross-language guesses are retained as
    unverified diagnostic claims, not authoritative missing requirements.
    """
    if not isinstance(action, str) or not isinstance(original, str):
        return False
    condensed = re.sub(r"\s+", " ", action).strip().casefold()
    normalized_original = re.sub(r"\s+", " ", original).strip().casefold()
    if not condensed or not normalized_original:
        return False
    if condensed in normalized_original:
        return True
    expected = _terms(original)
    claimed = _terms(action)
    asserted_actions = claimed & _ACTIONS
    if not asserted_actions or not (asserted_actions & (expected & _ACTIONS)):
        return False
    anchors = claimed - _ACTIONS - _GENERIC_CLAIM
    confirmed = anchors & expected
    # Two independent subject/content anchors protect against generic
    # "build a thing" / "pay a cost" hallucinations.
    return bool(len(confirmed) >= 2 and len(confirmed) * 3 >= len(anchors) * 2)

def reconcile_original_scope_claims(
    actions: list[str], original: str, effects: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """(grounded uncovered, documented duplicates, ungrounded suggestions).

    Unanchored claims remain visible for human diagnosis. They cannot
    invalidate the already approved, source-anchored effect ledger.
    """
    missing, duplicates, ungrounded = [], [], []
    for action in actions:
        if already_planned_action(action, effects):
            duplicates.append(action)
        elif original_request_supports_action(action, original):
            missing.append(action)
        else:
            ungrounded.append(action)
    return missing, duplicates, ungrounded
