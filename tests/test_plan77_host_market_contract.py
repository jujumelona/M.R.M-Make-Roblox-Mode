"""Original-space-plan regression: source-owned resource trade must not enter a
P2P planning loop. The host may compile a market settlement only if the source
authorizes both input/output assets and trading, and must pass existing gates.
"""
from roblox_mod_ai.atomic_action_quotes import eligible_atomic_action_spans
from roblox_mod_ai.source_owned_microplanning import (
    _recover_explicit_market_exchange, _coverage_issues,
    complete_source_owned_actions,
)


class NoPlannerCalls:
    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Host-authorized market recovery must not re-prompt the 9B model")


SOURCE = "자원파밍 돈모으기 거래 등으로 우주선을 부위마다 만들어서 만들수있고"


def _source_id(text, part):
    return next(row["id"] for row in eligible_atomic_action_spans(text)
                if row["quote"] == part)


def _harvest():
    return {"source_id": _source_id(SOURCE, "자원파밍"),
            "action": "Server mines resource nodes and credits collected resources to owned inventory."}


def _assembly():
    return {"source_id": _source_id(SOURCE, "우주선을 부위마다 만들어서"),
            "action": "Server assembles ship sections onto the spacecraft hull and updates installed parts."}


def test_market_contract_replaces_missing_trade_without_p2p_or_small_model():
    initial = [_harvest(), _assembly()]
    fixed = complete_source_owned_actions(NoPlannerCalls(), SOURCE, initial_actions=initial)
    assert len(fixed) == 3
    assert fixed[0]["action"] == initial[0]["action"]
    assert fixed[1]["action"] == initial[1]["action"]
    assert fixed[2]["source_quote"] == "거래"
    assert "deducts owned resource inventory" in fixed[2]["action"]
    assert "credits earned currency" in fixed[2]["action"]
    assert not _coverage_issues(SOURCE, fixed)


def test_market_contract_rewrites_only_vague_trade_if_action_budget_full():
    initial = [_harvest(),
               {"source_id": _source_id(SOURCE, "거래"),
                "action": "Server changes the player's balance to complete a trade."},
               _assembly()]
    fixed = complete_source_owned_actions(
        NoPlannerCalls(), SOURCE, initial_actions=initial, max_actions=3,
    )
    assert len(fixed) == 3
    assert fixed[0]["action"] == initial[0]["action"]
    assert fixed[2]["action"] == initial[2]["action"]
    assert fixed[1]["source_quote"] == "거래"
    assert "deducts owned resource inventory" in fixed[1]["action"]
    assert not _coverage_issues(SOURCE, fixed)


def test_host_never_assumes_market_for_unspecified_trade_or_explicit_p2p():
    router = NoPlannerCalls()
    for source in (
        "거래 채팅",
        "플레이어끼리 거래하고 자원으로 돈모으기",
        "우주선 부품 구매",
    ):
        result = _recover_explicit_market_exchange(
            router, source, [], ["SOURCE_TRADE_ACTION_MISSING: missing"],
            max_actions=6, evidence=[],
        )
        assert result is None


def test_host_only_uses_source_owned_quote_and_never_creates_price():
    from roblox_mod_ai.request_semantics import request_semantic_errors
    fixed = complete_source_owned_actions(
        NoPlannerCalls(), SOURCE,
        initial_actions=[_harvest(), _assembly()],
    )
    market = fixed[2]
    assert market["source_quote"] in SOURCE
    assert market["source_quote"] == "거래"
    assert not request_semantic_errors(market, SOURCE)
    assert "Robux" not in market["action"]
    assert "100" not in market["action"]
