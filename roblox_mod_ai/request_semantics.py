"""Source-request constraints shared by research, design and source acceptance.

Buying/trading in a game does not imply Roblox platform monetization. These
checks target the concrete uploaded misinterpretation, not arbitrary gameplay.
"""
from __future__ import annotations

import re
from typing import Any

_MONETIZATION = re.compile(
    r"\b(?:robux|marketplaceservice|game\s*passes?|developer\s+products?|"
    r"real[- ]money|paid\s+access)\b|로벅스|로부스|현금\s*결제|유료\s*결제|게임\s*패스",
    re.IGNORECASE,
)


def _positive_monetization(text: str) -> bool:
    text = re.sub(r"(?i)\b(don|doesn|isn|aren|wasn|weren|shouldn|mustn|can|won)['’]t\b",
                  lambda match: {"don": "do", "doesn": "does", "isn": "is", "aren": "are",
                                 "wasn": "was", "weren": "were", "shouldn": "should",
                                 "mustn": "must", "can": "can", "won": "will"}[match.group(1).lower()] + " not", text)
    for mention in _MONETIZATION.finditer(text):
        before = text[max(0, mention.start() - 30):mention.start()]
        after = text[mention.end():mention.end() + 28]
        if re.search(r"\b(?:no|without|never|avoid|disable|prohibit)\b(?:\W+\w+){0,3}\W*$|"
                     r"\b(?:do|does|must|should|will)\s+not\b(?:\W+\w+){0,3}\W*$", before, re.I):
            continue
        if re.match(r"(?:을|를|는|은|가|이)?\s*(?:사용하지|쓰지|없이|금지|불가|없|안\s*쓰|아닌|아니라|말고)|"
                    r"\s+(?:(?:is|are)\s+)?(?:not\s+(?:used|allowed|required|enabled)|disabled|forbidden)", after, re.I):
            continue
        return True
    return False



# Peer-to-peer trades add a new actor, two mutable inventories, an atomicity
# requirement and exploit cases. Do not silently introduce that scope when
# the request merely says "trade / 거래" in a resource economy.
_EXPLICIT_PEER_TRADE = re.compile(
    r"플레이어\s*(?:간|끼리|들\s*끼리)|유저\s*(?:간|끼리)|"
    r"사용자\s*(?:간|끼리)|(?:서로|상호)\s*(?:거래|교환)|"
    r"\bpeer\s+trades?\b|"
    r"\b(?:p2p|peer[- ]to[- ]peer|player[- ]to[- ]player)\b|"
    r"\bplayers?\s+(?:can\s+)?trade\s+(?:with\s+)?(?:each\s+other|one\s+another)\b|"
    r"\bplayers\s+(?:can\s+)?(?:trade|exchange)\b|"
    r"\bplayers?\b.{0,65}\btrade\b.{0,60}\beach\s+other\b",
    re.I,
)
_PEER_TRADE_OUTPUT = re.compile(
    r"\bplayer[- ]to[- ]player\s+(?:trade|trading|exchange)\b|"
    r"\b(?:p2p|peer[- ]to[- ]peer)\s+(?:trade|trading|exchange)\b|"
    r"\b(?:two|both|other)\s+players?'?\s*(?:inventor(?:y|ies)|trade|offers?)\b|"
    r"\b(?:trades?|exchanges?)\s+(?:with|between)\s+(?:other\s+)?players?\b|"
    # A P2P offer may avoid the words 'player' and 'inventory' entirely.
    # The generated plan 79 said 'seller's owned currency to the buyer' and
    # slipped past the old pattern. A buyer/seller TRANSFER is still two-party
    # gameplay, not the server market the user asked for.
    r"\b(?:seller['’]s?|buyer['’]s?)\b.{0,230}"
    r"\b(?:transfer\w*|trad\w*|exchang\w*|owned\s+by)\b.{0,230}"
    r"\b(?:buyer['’]s?|seller['’]s?)\b|"
    r"\b(?:seller['’]s?|buyer['’]s?)\b.{0,230}"
    r"\b(?:buyer['’]s?|seller['’]s?)\b.{0,230}"
    r"\b(?:transfer\w*|mark\w*\s+the\s+item\s+as\s+owned)\b|"
    r"\bother\s+player['’]s\s+inventor(?:y|ies)\b|"
    r"\bseller['’]s\s+(?:owned\s+)?(?:inventor(?:y|ies)|resources?|items?)\b"
    r".{0,240}\bbuyer['’]s\s+(?:currency\s+)?(?:balance|credits?|inventor(?:y|ies))\b|"
    r"\bbuyer['’]s\s+(?:currency\s+)?(?:balance|credits?|inventor(?:y|ies))\b"
    r".{0,240}\bseller['’]s\s+(?:owned\s+)?(?:inventor(?:y|ies)|resources?|items?)\b|"
    r"플레이어\s*(?:간|끼리)\s*(?:거래|교환)|유저\s*(?:간|끼리)\s*(?:거래|교환)",
    re.I,
)


# Another common representation of unsolicited bilateral gameplay is a
# source-acceptance claim about an asset moving from a seller to a buyer.
# This is different from an NPC/broker crediting the authenticated seller.
# Check the effect itself rather than particular item, planet or genre names.
_BILATERAL_ASSET_EFFECT = re.compile(
    r"\b(?:ownership|owner)\b.{0,90}\bchanges?\b.{0,100}"
    r"\bfrom\s+(?:the\s+)?seller\b.{0,80}"
    r"\bto\s+(?:the\s+)?buyer\b|"
    r"\btransfer\w*\b.{0,100}\bseller['’]s\b.{0,100}\bbuyer\b|"
    r"\bseller['’]s\s+(?:currency|money|coins?|credits?)\s+"
    r"(?:balance\s+)?decreases?\b.{0,150}"
    r"\bbuyer['’]s\s+(?:currency|money|coins?|credits?)\s+"
    r"(?:balance\s+)?increases?\b",
    re.I | re.S,
)


def request_semantic_errors(value: Any, original_prompt: str) -> list[str]:
    """Reject unsolicited platform monetization with a repairable diagnosis."""
    def values(item: Any):
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for child in item.values():
                yield from values(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                yield from values(child)

    errors: list[str] = []
    if (not _positive_monetization(original_prompt)
            and any(_positive_monetization(text) for text in values(value))):
        errors.append(
            "UNREQUESTED_MONETIZATION: the original user did not request Robux, "
            "game passes or real-money products. Implement buying/trading with "
            "the game's earned currency and owned items. Do not introduce "
            "MarketplaceService or a Robux balance API."
        )
    if (not _EXPLICIT_PEER_TRADE.search(original_prompt)
            and any(_PEER_TRADE_OUTPUT.search(text) or _BILATERAL_ASSET_EFFECT.search(text)
                    for text in values(value))):
        errors.append(
            "UNREQUESTED_PEER_TRADE: user requested trading without authorizing "
            "two-party item exchange. Do not invent P2P counters, double-profile "
            "writes or peer-owned inventory. Keep trade within a server-priced "
            "catalog until the source explicitly requires player-to-player trading."
        )
    return errors


# Authorization is source-derived exactly ONCE during design compilation.
# Code-generation adapters consume this immutable, validated data contract;
# they must not re-read prompt wording to select market/P2P behavior.
_RESOURCE_SOURCE = re.compile(
    r"자원|광물|채굴|파밍|\b(?:ore|resources?|mining|mine)\b", re.I,
)
_CURRENCY_SOURCE = re.compile(
    r"돈|화폐|코인|\b(?:money|coins?|credits?|currency)\b", re.I,
)
_EARNING_SOURCE = re.compile(
    r"모으|벌|얻|판매|팔|거래|\b(?:earn|sell|trade|exchange)\b", re.I,
)
_PEER_ONLY_SOURCE = re.compile(
    r"플레이어끼리|유저끼리|player.to.player|between players", re.I,
)
_MARKET_SOURCE = re.compile(
    r"판매|팔|돈모으|earn|sell|market", re.I,
)


def source_action_authorizations(original_prompt: str) -> dict[str, Any]:
    """Parse requested actor/asset capabilities before assigning code routes.

    This is a source provenance claim, not a declaration of implementation.
    Missing authorization MUST NOT be inferred from a model-generated
    module description. All game genres use the same typed authorization API.
    """
    if not isinstance(original_prompt, str) or not original_prompt.strip():
        raise ValueError("SOURCE_AUTHORIZATIONS_REQUIRE_ORIGINAL_REQUEST")
    market = (
        bool(_RESOURCE_SOURCE.search(original_prompt))
        and bool(_CURRENCY_SOURCE.search(original_prompt))
        and bool(_EARNING_SOURCE.search(original_prompt))
        and not (bool(_PEER_ONLY_SOURCE.search(original_prompt))
                 and not bool(_MARKET_SOURCE.search(original_prompt)))
    )
    return {
        "schema": "rmm/source-action-authorizations-v1",
        "peer_asset_exchange": bool(
            _EXPLICIT_PEER_TRADE.search(original_prompt)
            or re.search(r"\bbetween\s+players\b", original_prompt, re.I)
        ),
        "earned_resource_market": market,
    }


def assert_source_action_authorizations(proposal: Any) -> None:
    """Fail closed on stale/tampered source claims before generating Luau."""
    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design") or {}
    if not design:
        return
    claims = design.get("source_action_authorizations")
    if claims is None:
        # Legacy/diagnostic plans without a barter or market route must be
        # allowed to reach their normal compiler/failure-recovery stages.
        # Missing permission never authorizes a two-party exchange: the
        # barter adapter refuses it. A legacy source claiming a bilateral
        # service must be re-planned instead of falling into unsupervised
        # cross-player mutations.
        from .host_peer_barter import is_bilateral_asset_exchange
        remote_services = {
            row.get("service") for row in (design.get("host_actions") or {}).values()
            if isinstance(row, dict)
        }
        if any(
            m.name in remote_services and is_bilateral_asset_exchange(
                str(getattr(m, "description", "") or "")
            )
            for m in getattr(proposal, "modules", [])
        ):
            raise ValueError(
                "SOURCE_AUTHORIZATIONS_MISSING: source-owned peer trade needs "
                "recompilation before generating cross-player action code"
            )
        return
    if not isinstance(claims, dict):
        raise ValueError("SOURCE_AUTHORIZATIONS_INVALID")
    expected = source_action_authorizations(proposal.requested_prompt)
    if claims != expected:
        raise ValueError(
            "SOURCE_AUTHORIZATIONS_INVALID: compiled gameplay permissions "
            "do not match the original request; rebuild the source-ledger plan"
        )
    # Model-written acceptance statements and module responsibilities cannot
    # certify a capability that was not authorized by the user. Otherwise a
    # compiled market sale can pass a contradictory two-player exchange test.
    claims_to_audit = {
        "acceptance": design.get("acceptance") or {},
        "module_behaviors": design.get("module_behaviors") or {},
    }
    errors = request_semantic_errors(
        claims_to_audit, proposal.requested_prompt,
    )
    if errors:
        raise ValueError(
            "SOURCE_ACCEPTANCE_UNAUTHORIZED: " + " | ".join(errors)
        )
