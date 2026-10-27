"""The 2026-10-27 plan79 second atomic child failed three 9B attempts.

A verified resource-market sale is already source-owned. It must compile
as one debit+credit, not trigger another invented earned-money server API.
The result is still an unexecuted plan, never proof of game code correctness.
"""
from roblox_mod_ai.compact_atomic_authoring import host_verified_resource_market
from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems
from roblox_mod_ai.atomic_action_quotes import validate_atomic_system_ownership


SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
    "부위마다 만들어서 만들수있고"
)
ACTION = {
    "source_quote": "돈모으기 거래",
    "action": (
        "Server executes a resource trade at an approved server price: "
        "it deducts owned resource inventory and credits earned money "
        "to the same player's authoritative balance."
    ),
}


class NoModel:
    supports_host_standard_transport = True

    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("No new MiMo 9B call for verified market settlement")


def test_source_owned_market_money_compiles_without_small_model():
    system = host_verified_resource_market(ACTION, original_prompt=SOURCE)
    assert system is not None
    assert system["world_entities"] == []
    assert "deducts" in system["server_behavior"]
    assert "credits earned money" in system["server_behavior"]
    validate_atomic_system_ownership(
        [ACTION], [system], original_prompt=SOURCE,
    )
    authored = author_verified_atomic_systems(
        NoModel(), [ACTION],
        source_clause=SOURCE,
        original_prompt=SOURCE,
        json_schema={"type": "object", "properties": {
            "systems": {"type": "array", "items": {"type": "object"}},
        }},
        retained_verified={},
    )
    assert len(authored) == 1
    assert authored[0] == system


def test_not_a_free_currency_mint_or_unrequested_p2p_trade():
    peer = "자원파밍 돈모으기 플레이어끼리 거래"
    assert host_verified_resource_market(
        ACTION, original_prompt=peer,
    ) is None
    assert host_verified_resource_market(
        dict(ACTION, action="Server adds requested money to the player balance"),
        original_prompt=SOURCE,
    ) is None
    assert host_verified_resource_market(
        dict(ACTION, source_quote="돈모으기"),
        original_prompt=SOURCE,
    ) is None


def test_no_money_or_resource_in_source_means_no_market_compilation():
    for src in (
        "거래와 상점 구축",
        "자원파밍하고 우주선을 만든다",
        "돈모으기만 하는 게임",
    ):
        assert host_verified_resource_market(
            ACTION, original_prompt=src,
        ) is None
