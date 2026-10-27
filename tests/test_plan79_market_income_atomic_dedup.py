"""Regression for uploaded plan (9): money earned from resource trade must
not become a second unbacked currency writer with three failed 9B retries.

Consolidation changes no original user source text, no P2P permissions and
never runs for independent mining payouts/quest rewards or trade of a weapon.
"""
from roblox_mod_ai.atomic_action_quotes import eligible_atomic_action_spans
from roblox_mod_ai.source_owned_microplanning import (
    complete_source_owned_actions, _combine_derived_market_income,
    _coverage_issues,
)


SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)


class NoModel:
    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Do not reprompt MiMo 9B for money-minting")


def a(quote, action, source=SOURCE):
    ids = {row["quote"]: row["id"]
           for row in eligible_atomic_action_spans(source)}
    return {"source_id": ids[quote], "action": action}


def original_actions():
    return [
        a("자원파밍", "Server mines ore nodes in the world and credits gathered resource inventory."),
        a("돈모으기", "Server adds earned money to the player's authoritative balance."),
        a("거래", "Server trades owned resources at a server-priced shop, deducts ore inventory and credits money to the player's balance."),
        a("우주선을 부위마다 만들어서", "Server assembles ship components and attaches sections to the ship hull."),
    ]


def test_plan79_income_is_the_same_atomic_sale_not_a_separate_money_minter():
    source_actions = original_actions()
    result = complete_source_owned_actions(
        NoModel(), SOURCE, initial_actions=source_actions
    )
    assert len(result) == 3
    assert result[0]["action"] == source_actions[0]["action"]
    assert result[-1]["action"] == source_actions[-1]["action"]
    assert result[1]["source_quote"] == "돈모으기 거래"
    assert "deducts" in result[1]["action"]
    assert "credits" in result[1]["action"]
    assert not _coverage_issues(SOURCE, result)


def test_vague_trade_completed_from_original_source_before_combination():
    actions = original_actions()
    actions[2] = a("거래", "Server records a trade and changes player balance.")
    fixed = complete_source_owned_actions(
        NoModel(), SOURCE, initial_actions=actions,
    )
    assert len(fixed) == 3
    assert fixed[1]["source_quote"] == "돈모으기 거래"
    assert "deducts" in fixed[1]["action"]
    assert "credits" in fixed[1]["action"]


def test_do_not_merge_separate_mining_income_origin():
    actions = original_actions()
    actions[1] = a("돈모으기", (
        "Server awards a verified bounty for defeating an enemy "
        "and credits money to the player's balance."
    ))
    # This action has an independent payout trigger; don't erase it even if
    # another action exchanges resources for money.
    result = _combine_derived_market_income(
        NoModel(), SOURCE, actions, max_actions=6,
    )
    assert result == actions


def test_do_not_forge_market_when_user_requests_peer_to_peer():
    original = "자원파밍 돈모으기 플레이어끼리 거래 우주선 부품 제작"
    rows = [
        a("자원파밍", "Server mines real ore nodes and adds ore inventory.", original),
        a("돈모으기", "Server credits earned game money.", original),
        a("플레이어끼리 거래", "Server transfers items between two players.", original),
    ]
    assert _combine_derived_market_income(
        NoModel(), original, rows, max_actions=6,
    ) == rows


def test_not_conflate_ship_part_purchase_with_resource_market_income():
    rows = original_actions()
    rows[2] = a("거래", "Server trades money to buy a ship component and grants an installed ship part.")
    assert _combine_derived_market_income(
        NoModel(), SOURCE, rows, max_actions=6,
    ) == rows
