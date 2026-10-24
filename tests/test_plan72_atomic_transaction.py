"""Proposal 72: the planner cannot certify a purchase with no payment.

The previous 9B completion failed SOURCE_TRADE_ACTION_MISSING for the second
source facet (weapon/crew/ship purchases). We test the two-effect host
contract and its integration with the existing per-atom authoring path.
"""
import pytest

from roblox_mod_ai.atomic_transaction_repair import (
    require_transaction_repair, author_transaction_repair,
)
from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems


PURCHASE = {
    "source_quote": "구매",
    "action": "Purchase weapon upgrades using the player's earned credits",
}


class Router:
    supports_host_standard_transport = True

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def transaction(
    paid="the server deducts the verified price in credits from the player's owned balance",
    received="the server installs the purchased weapon upgrade into the player's owned weapon loadout",
):
    return {"payment_mutation": paid, "received_mutation": received}


def schema():
    return {"type": "object", "properties": {"systems": {
        "type": "array", "maxItems": 3,
        "items": {"type": "object"},
    }}, "required": ["systems"]}


def test_trade_error_selects_typed_effect_contract():
    assert require_transaction_repair({
        "server_behavior": ["SOURCE_TRADE_ACTION_MISSING: payment required"],
    })
    assert not require_transaction_repair({
        "server_behavior": ["SOURCE_SECTION_BUILD_MISSING: craft"],
    })


def test_typed_transaction_has_explicit_payment_and_delivery():
    router = Router(transaction())
    text = author_transaction_repair(
        router, PURCHASE, "Server upgrades the weapon's damage.",
    )
    assert "deducts the verified price" in text
    assert "installs the purchased weapon upgrade" in text
    assert "server-owned catalog cost" in text
    assert router.calls[0][1]["max_tokens"] == 225
    assert set(router.calls[0][1]["json_schema"]["required"]) == {
        "payment_mutation", "received_mutation",
    }
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    assert not source_intent_conflicts("구매", text)


@pytest.mark.parametrize("bad", [
    transaction(paid="the server shows a trade menu but does not change balances"),
    transaction(paid="the server upgrades the item without a payment"),
    transaction(paid="the server records a payment in the player's money balance"),
    transaction(received="the player sees the item in a menu and no inventory changes"),
    transaction(paid="no coins are deducted and the player pays nothing"),
    {"payment_mutation": "the server deducts owned credits",
     "received_mutation": None},
])
def test_no_money_exchange_or_no_reward_is_rejected(bad):
    with pytest.raises(ValueError, match="ATOMIC_TRANSACTION_"):
        author_transaction_repair(
            Router(bad), PURCHASE, "Server upgrades weapon damage.",
        )


def test_one_broken_atomic_purchase_does_not_regenerate_sibling(monkeypatch):
    from roblox_mod_ai import atomic_action_authoring as atomic

    # The first parent-verified action is cached; the second action alone
    # requires a transaction repair.
    mining_action = {
        "source_quote": "자원파밍",
        "action": "Harvest resources from a server-authoritative resource node",
    }
    mining_system = {
        "name": "HarvestOre",
        "server_behavior": (
            "Server validates a resource node, mines ore from its deposits "
            "and credits the mined resources to the player's owned inventory."
        ),
        "observable_result": (
            "The ore deposit depletes and the player's owned ore grows."
        ),
        "world_entities": ["OreDeposit"],
    }
    original = {
        "name": "UpgradeWeapon",
        "server_behavior": (
            "Server validates the selected weapon and increases its stats "
            "upon approval but does not debit any currency."
        ),
        "world_entities": ["Weapon"],
    }
    visible = {
        "observable_result": (
            "The player's owned weapon displays its improved attack power."
        )
    }
    router = Router(original, visible, transaction())
    existing = {(mining_action["source_quote"], mining_action["action"]):
                mining_system}

    # Force the old server field to fail the same source quote obligation.
    # The corrected field must pass the actual validator with no monkeypatch
    # to _field_issues or the transaction-specific repair.
    output = author_verified_atomic_systems(
        router, [mining_action, PURCHASE],
        source_clause="자원파밍 구매",
        original_prompt="자원파밍 구매 무기 업그레이드",
        json_schema=schema(), retained_verified=existing,
    )
    assert len(output) == 2
    assert output[0] == mining_system
    assert "deducts" in output[1]["server_behavior"]
    assert len(router.calls) == 3
    assert len(existing) == 2


def test_p2p_and_robux_do_not_bypass_source_semantics():
    with pytest.raises(ValueError, match="ATOMIC_TRANSACTION_UNREQUESTED_EFFECT"):
        author_transaction_repair(
            Router(transaction(
                paid="the buyer deducts coins from their owned currency balance",
                received=(
                    "the seller transfers the weapon upgrade to the buyer's "
                    "inventory through a peer-to-peer trade"
                ),
            )), PURCHASE, "Server upgrade",
        )
    from roblox_mod_ai.request_semantics import request_semantic_errors
    assert any("UNREQUESTED_MONETIZATION" in x for x in
               request_semantic_errors(
                   "Purchase ship upgrades using Robux via MarketplaceService",
                   "우주선 업그레이드 구매",
               ))


def test_wrong_upgrade_target_cannot_be_delivered():
    with pytest.raises(ValueError, match="DELIVERY_TARGET_MISMATCH"):
        author_transaction_repair(
            Router(transaction(
                received=(
                    "the server recruits a crew member and adds them to "
                    "the player's owned crew roster"
                ),
            )), PURCHASE, "Server upgrades weapon damage.",
        )


def test_free_upgrade_no_longer_qualifies_as_purchase():
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    assert any("SOURCE_PURCHASE_PAYMENT_MISSING" in issue for issue in
               source_intent_conflicts(
                   "무기 구매", "Server purchases a weapon and upgrades its stats.",
               ))
    assert any("SOURCE_TRADE_ACTION_MISSING" in issue for issue in
               source_intent_conflicts(
                   "무기 구매", "Server purchases a weapon and upgrades its stats.",
               ))



@pytest.mark.parametrize("server_behavior", [
    "Server approves a weapon purchase but does not deduct any credits.",
    "Server purchases a weapon without debiting the buyer's currency balance.",
    "Server executes a purchase; no funds are deducted.",
])
def test_negated_money_movement_is_not_accepted_as_payment(server_behavior):
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    assert any("SOURCE_PURCHASE_PAYMENT_MISSING" in issue
               for issue in source_intent_conflicts(
                   "무기 구매", server_behavior,
               ))


def test_real_debit_and_owned_upgrade_are_required_together():
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    result = (
        "Server validates the player's approved purchase and deducts "
        "the official price in credits from the player's owned balance "
        "and installs the purchased weapon into the owned loadout."
    )
    assert not source_intent_conflicts("무기 구매", result)
