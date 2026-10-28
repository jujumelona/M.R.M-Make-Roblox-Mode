"""Host-constrained semantic repair of source-owned purchase/trade actions.

The local model provides two *specific state mutations* rather than re-writing
an entire gameplay paragraph. The host controls the fixed input validation
contract; it does not guess catalog items, price values or currencies.
Nothing here certifies that the later Luau implementation executes.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Both a spend AND receipt must be described. A statement such as
# "purchases the crew and upgrades the ship" is NOT payment.
_DEBIT = re.compile(
    r"\b(?:deduct\w*|debit\w*|subtract\w*|spend\w*|"
    r"consum\w*|charg\w*|pay(?:s|ing)?|paid|"
    r"reduc\w*|decreas\w*)\b|차감|지불|소비|감소|공제", re.I,
)
_PAYMENT_ASSET = re.compile(
    r"\b(?:coins?|credits?|currency|cash|money|balance|funds?|"
    r"resources?|ores?|minerals?|materials?|tokens?)\b|"
    r"돈|화폐|코인|자원|광물|재료|잔액", re.I,
)
_DELIVERY = re.compile(
    r"\b(?:grant\w*|deliver\w*|assign\w*|recruit\w*|"
    r"hire\w*|equip\w*|install\w*|upgrad\w*|"
    r"improv\w*|increase\w*|add\w*|credit\w*|"
    r"construct\w*|build\w*|transfer\w*|"
    r"obtain\w*|receive\w*)\b|장착|영입|고용|강화|"
    r"지급|적립|획득|추가|설치|업그레이드", re.I,
)
_NEGATIVE = re.compile(
    r"\b(?:never|without|cannot|can't|not|no)\b.{0,60}"
    r"\b(?:deduct|spend|credit|transfer|deliver|grant|upgrade|"
    r"debit|consume|install)\w*\b|"
    r"\b(?:balance|inventory|state)\b.{0,35}"
    r"\b(?:unchanged|unmodified)\b", re.I,
)
_OWNED_TARGETS = {
    "weapon": re.compile(r"\b(?:weapon|gun|armament)s?\b|무기", re.I),
    "crew": re.compile(r"\b(?:crew|crewmember|sailor)s?\b|선원", re.I),
    "ship": re.compile(r"\b(?:ship|spacecraft|spaceship|vessel|engine|thruster)s?\b|우주선", re.I),
}
_PURCHASE_INTENT = re.compile(
    r"\b(?:trad(?:e|es|ing)|exchang(?:e|es|ing)|barter\w*|"
    r"sell\w*|sold|buy\w*|bought|purchas\w*|hire\w*)\b|"
    r"거래|구매|판매|교환|매입|고용", re.I,
)


def require_transaction_repair(issues: dict[str, list[str]]) -> bool:
    """Trigger ONLY the explicitly failed trade obligation."""
    return any(
        str(error).startswith("SOURCE_TRADE_ACTION_MISSING:")
        for error in issues.get("server_behavior", [])
    )


def author_transaction_repair(
    router: Any, action: dict[str, str], previous_server: str,
    *, prior_rejections: list[str] | None = None,
) -> str:
    """Compile a trade/purchase action from two model-owned effect fields.

    Fails closed on missing, negated, or non-mutating effects. Downstream
    validators recheck source fidelity and unwanted P2P/Robux behavior.
    """
    source = str(action.get("source_quote") or "")
    owned = str(action.get("action") or "")
    if not _PURCHASE_INTENT.search(source + " " + owned):
        raise ValueError("ATOMIC_TRANSACTION_SOURCE_NOT_OWNED")
    reply = router.complete_json(
        "Repair exactly ONE source-owned purchase or trade. Return JSON "
        "{payment_mutation,received_mutation} and nothing else. "
        "payment_mutation describes how the server actually SUBTRACTS owned "
        "money/materials from the authenticated buyer, using the price or "
        "recipe established by the server; received_mutation describes "
        "the owned item, recruited crew, equipped upgrade or ship component "
        "the same player actually receives. Provide ONE concrete state "
        "mutation in EACH field, in English. No menu, placeholder, "
        "animation, free reward, Robux or invented second player. "
        "No Luau code. JSON only.\n" +
        json.dumps({
            "original_source_quote": source,
            "owned_action": owned,
            "rejected_server_behavior": previous_server[:450],
            "prior_transaction_rejections": (prior_rejections or [])[-2:],
        }, ensure_ascii=False),
        role="planner", temperature=0.0, max_tokens=225,
        json_schema={
            "type": "object",
            "properties": {
                "payment_mutation": {
                    "type": "string", "minLength": 24, "maxLength": 180,
                },
                "received_mutation": {
                    "type": "string", "minLength": 24, "maxLength": 180,
                },
            },
            "required": ["payment_mutation", "received_mutation"],
            "additionalProperties": False,
        },
    )
    if not isinstance(reply, dict):
        raise ValueError("ATOMIC_TRANSACTION_REPLY_NOT_OBJECT")
    paid = reply.get("payment_mutation")
    gained = reply.get("received_mutation")
    if (not isinstance(paid, str) or not 24 <= len(paid.strip()) <= 180
            or not isinstance(gained, str)
            or not 24 <= len(gained.strip()) <= 180):
        raise ValueError("ATOMIC_TRANSACTION_EFFECT_FIELDS_INVALID")
    # A word like "payment" is not a debit. Require an affirmative debit
    # verb tied to a currency/material within the SAME short effect field;
    # neither "record payment" nor UI transfer counts as spending.
    debit = _DEBIT.search(paid)
    if (debit is None or not _PAYMENT_ASSET.search(
            paid[debit.start():debit.end() + 100])):
        raise ValueError("ATOMIC_TRANSACTION_NO_AUTHORIZED_PAYMENT")
    if not _DELIVERY.search(gained):
        raise ValueError("ATOMIC_TRANSACTION_NO_DELIVERED_EFFECT")
    if _NEGATIVE.search(paid) or _NEGATIVE.search(gained):
        raise ValueError("ATOMIC_TRANSACTION_NEGATED_EFFECT")
    # A valid debit for a SHIP must not authorize an unrelated CREW receipt.
    # Verify each target named in the owned original source action, not the
    # host's genre guess or an unrelated sibling action.
    for name, pattern in _OWNED_TARGETS.items():
        if pattern.search(owned) and not pattern.search(gained):
            raise ValueError(
                "ATOMIC_TRANSACTION_DELIVERY_TARGET_MISMATCH: " + name
            )
    # The host owns the common Remote/validation obligations. The model must
    # still supply BOTH mutable effects and the owning gameplay target.
    candidate = (
        "For the requested purchase or trade, the server validates the "
        "authenticated player's chosen item, the server-owned catalog cost "
        "and available owned balance; it rejects invalid, insufficient or "
        "duplicate requests without mutation; on accepted request, "
        + paid.strip().rstrip(".; ") + "; then "
        + gained.strip().rstrip(".; ") + "."
    )
    from .request_semantics import request_semantic_errors
    issues = request_semantic_errors(candidate, source + " " + owned)
    if issues:
        raise ValueError(
            "ATOMIC_TRANSACTION_UNREQUESTED_EFFECT: " +
            "; ".join(issues)[:500]
        )
    return candidate
