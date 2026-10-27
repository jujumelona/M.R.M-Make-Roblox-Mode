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


def test_nonphysical_state_variables_never_become_workspace_parts():
    from roblox_mod_ai.semantic_world_entities import assert_physical_world_entities
    from roblox_mod_ai.host_architecture import expand_semantic_facet, HostArchitectureError

    for name in (
        "PlayerCurrency", "PlayerInventory", "CounterpartyCurrency",
        "CounterpartyInventory", "TradeRequest", "CrewPerformanceState",
        "ResourceBalance",
    ):
        with pytest.raises(ValueError, match="WORLD_ENTITY_LOGICAL_STATE_NOT_PHYSICAL"):
            assert_physical_world_entities([name])
    # Physical scene objects remain legitimate, regardless of gameplay.
    assert_physical_world_entities([
        "ResourceNode", "ShipHull", "InventoryChest", "TradeRequestBoard",
        "CurrencyMachine", "AlienNPC",
    ])
    raw = {"systems": [{
        "name": "Transfer",
        "server_behavior": ("Server validates the owned resources before "
                            "paying the player and updating the owned balance."),
        "client_behavior": "Player requests a payout and views the balance.",
        "observable_result": "Owned balance is updated.",
        "interaction": "request_response", "input_mode": "custom",
        "world_entities": ["PlayerCurrency"],
    }]}
    with pytest.raises(HostArchitectureError, match="WORLD_ENTITY_LOGICAL_STATE_NOT_PHYSICAL"):
        expand_semantic_facet(
            raw, facet_id="intent-transfer", requirement_ids=["req-001"],
            source_requirements=[{
                "id": "req-001", "statement": "Earn credits from resources",
            }],
            reserved_modules=set(), reserved_remotes=set(),
            reserved_objects=set(),
        )


def test_same_player_two_balance_bookkeeping_is_not_mistaken_for_p2p():
    single_actor = (
        "Validate the player's trade request against authoritative inventory "
        "and money state, transfer resources or credits, then commit both "
        "balances to the server-owned economy."
    )
    assert not request_semantic_errors(
        {"server_behavior": single_actor},
        "Trade earned game resources for credits",
    )
