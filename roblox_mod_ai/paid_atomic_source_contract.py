"""Preserve an already paid, source-bound action across compact authoring.

The 36th failure passed source binding for a ship purchase whose *same*
atomic action both upgraded ship performance and debited owned currency.
A second free-form model completion then omitted the debit and exhausted
three repair rounds. The immutable action is the authorized semantic input:
do not ask the 9B model to rewrite its proven payment/delivery effects.
This compiles *source semantics only*, NEVER evidence of a catalog, a real
state provider, executable Luau or Studio execution.
"""
from __future__ import annotations

import re
from typing import Any

from .atomic_transaction_repair import (
    _DEBIT, _PAYMENT_ASSET, _DELIVERY, _NEGATIVE,
    _PURCHASE_INTENT,
)
from .semantic_preservation import source_intent_conflicts
from .request_semantics import request_semantic_errors


def preserved_paid_server_behavior(
    action: dict[str, str], *, original_prompt: str,
) -> str | None:
    """Reify only explicit source-owned *paid* effects, preserving their text.

    Do NOT synthesize a missing purchase price, payment asset, world target or
    effect. A 'buyer purchases an upgrade' label is NOT a debit; a purchase
    whose separate sibling handles payment is NOT a paid atomic action.
    """
    if not isinstance(action, dict) or not isinstance(original_prompt, str):
        return None
    quote = action.get("source_quote")
    owned = action.get("action")
    if not isinstance(quote, str) or not isinstance(owned, str):
        return None
    if (not quote or quote not in original_prompt
            or not _PURCHASE_INTENT.search(quote)):
        return None
    debit = _DEBIT.search(owned)
    if (not debit or not _PAYMENT_ASSET.search(
                owned[debit.start():debit.end() + 110])
            or not _DELIVERY.search(owned)
            or _NEGATIVE.search(owned)):
        return None
    # Require a positive, OWNED asset mutation and a real acquisition/
    # upgrade effect in the SAME model-authored action. The same receipt is
    # rechecked by the public source and user-authorization validators.
    if (source_intent_conflicts(quote, owned)
            or request_semantic_errors(owned, original_prompt)):
        return None
    # Preserve the precise original payment and target. Host boilerplate
    # supplies only generic server security obligations, not new gameplay.
    server = (
        "For the requested purchase, the server validates the authenticated "
        "buyer's item selection, actual owned balance and the server-owned "
        "price or recipe; it rejects unauthorized, duplicate, invalid or "
        "insufficient-payment requests without mutation; after validation, "
        + owned.strip().rstrip(".; ") + "."
    )
    if len(server) > 600:
        return None
    if (source_intent_conflicts(quote, server)
            or source_intent_conflicts(owned, server)
            or request_semantic_errors(server, original_prompt)):
        return None
    return server
