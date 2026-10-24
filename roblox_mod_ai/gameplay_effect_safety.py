"""Conservative cross-gameplay Luau money and transaction safety checks.

The host must not certify code as functional when it only adjusts a local
copy of a currency balance, or when a payment is irreversibly deducted before
a following return false. This is static evidence, not a Studio playtest.
"""
from __future__ import annotations

import re
from .dynamic_wiring import _mask_strings, _without_comments
from .gameplay_source_evidence import authored_action_body

_ASSIGNED_FROM_WALLET = re.compile(
    r"\blocal\s+(coins|credits|money|balance)\s*="
    r"[^\n]*\bleaderstats\s*\.\s*Coins\s*\.\s*Value\b", re.I,
)
_WALLET_DEBIT = re.compile(
    r"\b(?P<var>coins|credits|money|balance)\s*"
    r"(?:-=\s*[^\n]+|=\s*(?P=var)\s*-\s*[^\n]+)", re.I,
)
_WALLET_WRITE = re.compile(
    r"\bleaderstats\s*\.\s*Coins\s*\.\s*Value\s*"
    r"(?:-=\s*[^\n]+|=\s*(?!=)[^\n]+)", re.I,
)
_DEBIT_ASSIGN = re.compile(
    r"\bleaderstats\s*\.\s*Coins\s*\.\s*Value\s*"
    r"(?:-=\s*[^\n]+|=\s*(?!=)[^\n]*-\s*[^\n]+)", re.I,
)
_REJECTION = re.compile(r"\bif\b[^\n]*\breturn\s+false\b", re.I)
_ROLLBACK = re.compile(
    r"\bleaderstats\s*\.\s*Coins\s*\.\s*Value\s*(?:\+=|=\s*[^-\n]+)"
)


def game_effect_safety_errors(source: str, *, routed_action: bool = True) -> list[str]:
    """Find only demonstrated payment-integrity defects in executable source."""
    if not isinstance(source, str) or not source.strip():
        return []
    raw = authored_action_body(source) if routed_action else source
    if not raw:
        return []
    code = _mask_strings(_without_comments(raw))
    errors: list[str] = []
    local_vars = {m.group(1).lower() for m in _ASSIGNED_FROM_WALLET.finditer(code)}
    debited_vars = {m.group("var").lower() for m in _WALLET_DEBIT.finditer(code)}
    if local_vars & debited_vars and not _WALLET_WRITE.search(code):
        errors.append(
            "WALLET_SHADOW_DEBIT: locally reduced earned coin balance never "
            "written back to the server-owned player wallet"
        )
    # Payment must not precede an unrelated rejection without a refund.
    for payment in _DEBIT_ASSIGN.finditer(code):
        rest = code[payment.end():]
        if _REJECTION.search(rest) and not _ROLLBACK.search(rest):
            errors.append(
                "NONATOMIC_PAYMENT: coin balance is deducted before a "
                "later server rejection with no rollback"
            )
            break
    return errors
