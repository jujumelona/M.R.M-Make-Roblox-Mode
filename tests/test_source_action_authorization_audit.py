"""Semantic authorization regression grounded in generated request receipts.

An acceptance criterion cannot assert cross-player effects when the user's
source asks for marketplace trading only. The rule is independent of genre.
"""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.request_semantics import (
    request_semantic_errors,
    source_action_authorizations,
    assert_source_action_authorizations,
)

REQUEST = "자원파밍 돈모으기 거래로 장비를 업그레이드한다"
UNAUTHORIZED_ACCEPTANCE = (
    "The seller's currency balance decreases, the buyer's currency balance "
    "increases, and the traded item's ownership changes from the seller "
    "to the buyer."
)
AUTHORIZED_ACCEPTANCE = (
    "The server subtracts the user's verified inventory quantity and credits "
    "earned currency to the same authenticated user at a server-fixed price."
)


def test_market_claim_must_not_silently_become_peer_asset_transfer():
    errors = request_semantic_errors(
        {"req": UNAUTHORIZED_ACCEPTANCE}, REQUEST,
    )
    assert any("UNREQUESTED_PEER_TRADE" in msg for msg in errors)
    assert not request_semantic_errors(
        {"req": AUTHORIZED_ACCEPTANCE}, REQUEST,
    )


def test_source_authorization_preflight_rejects_invented_acceptance():
    design = {
        "source_action_authorizations": source_action_authorizations(REQUEST),
        "acceptance": {"req-001": UNAUTHORIZED_ACCEPTANCE},
        "module_behaviors": {},
    }
    p = SimpleNamespace(requested_prompt=REQUEST, modules=[],
                        game_design={"dynamic_design": design})
    with pytest.raises(ValueError, match="SOURCE_ACCEPTANCE_UNAUTHORIZED"):
        assert_source_action_authorizations(p)
    design["acceptance"]["req-001"] = AUTHORIZED_ACCEPTANCE
    assert_source_action_authorizations(p) is None


def test_user_authorized_bilateral_exchange_may_have_bilateral_acceptance():
    request = "Players can trade items with each other"
    p = SimpleNamespace(
        requested_prompt=request, modules=[],
        game_design={"dynamic_design": {
            "source_action_authorizations": source_action_authorizations(request),
            "acceptance": {"req-001": UNAUTHORIZED_ACCEPTANCE},
        }},
    )
    assert_source_action_authorizations(p)
