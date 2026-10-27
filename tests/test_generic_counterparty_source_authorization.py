"""Reproduce a source-invented counterparty dependency before Luau coding.

Counterparty accounts, world placeholders and Remote services must not appear
unless the actual user request authorizes cross-player asset transfers.
"""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.request_semantics import (
    assert_source_action_authorizations,
    request_semantic_errors,
    source_action_authorizations,
)


MARKET = "자원을 채굴하고 돈을 모아 장비를 거래·구매·업그레이드한다"
BILATERAL = "플레이어끼리 소유한 자원을 직접 거래하고 두 사람의 장부를 변경한다"
FAKE_SERVER = (
    "Validate against the authenticated player's currency and inventory. "
    "On success, deduct the agreed currency from the player, credit the "
    "counterparty, and apply the agreed item exchange to both inventories."
)
FAKE_ACCEPTANCE = (
    "The player's owned currency decreases and the counterparty's "
    "inventory is credited with the transferred asset."
)


def test_unrequested_counterparty_mutation_is_a_design_error_not_a_coder_task():
    issues = request_semantic_errors(
        {"systems": [{
            "server_behavior": FAKE_SERVER,
            "observable_result": FAKE_ACCEPTANCE,
            "world_entities": ["PlayerCurrency", "CounterpartyInventory"],
        }]}, MARKET,
    )
    assert any("UNREQUESTED_PEER_TRADE" in s for s in issues)
    assert not request_semantic_errors({"systems": [{
        "server_behavior": FAKE_SERVER,
        "observable_result": FAKE_ACCEPTANCE,
    }]}, BILATERAL)


def test_preflight_does_not_accept_bilateral_module_hidden_outside_acceptance():
    design = {
        "source_action_authorizations": source_action_authorizations(MARKET),
        "acceptance": {"req-001": "The seller obtains a fixed server price."},
    }
    proposal = SimpleNamespace(
        requested_prompt=MARKET,
        game_design={"dynamic_design": design},
        modules=[SimpleNamespace(
            module_id="dyn_trade_server",
            name="AssetExchangeServer",
            description=FAKE_SERVER,
        )],
    )
    with pytest.raises(ValueError, match="SOURCE_ACCEPTANCE_UNAUTHORIZED"):
        assert_source_action_authorizations(proposal)
    proposal.modules[0].description = (
        "Server validates a player's owned resources and credits the same "
        "authenticated player's wallet using the agreed market rate."
    )
    assert_source_action_authorizations(proposal) is None


@pytest.mark.parametrize("claim", [
    "Credit the counterparty after deducting a player's coins",
    "Exchange both inventories and reject insufficient inventory",
    "Transfer currency to the other player on success",
])
def test_actor_flow_aliases_do_not_bypass_source_permissions(claim):
    errors = request_semantic_errors({"server_behavior": claim}, MARKET)
    assert any("UNREQUESTED_PEER_TRADE" in issue for issue in errors)
