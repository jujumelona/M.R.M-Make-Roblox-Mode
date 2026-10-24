"""Regression: mined resources must finance the requested earned-currency economy.

Real failed generation #43 mined ore into RMMInventory.resources but minted no
Coins. All new players started at 0 and peer barter could only redistribute
coins that did not exist. The host composes existing audited market + barter
without inventing money, assets, prices or a second Remote.
"""
from test_host_peer_barter import make_plan
from roblox_mod_ai.host_peer_barter import (
    _needs_earned_currency_market, render_host_peer_barter,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer


def test_resource_to_coins_mining_trade_progression_is_reachable():
    server, client, plan = make_plan()
    plan.requested_prompt = (
        "우주모드 자원파밍 돈모으기 거래로 우주선을 부위마다 만들고 "
        "무기 선원 성능을 돈으로 구매 업그레이드"
    )
    assert _needs_earned_currency_market(plan)
    scode = render_host_peer_barter(server, plan)
    ccode = render_host_peer_barter(client, plan)
    assert scode and ccode
    assert 'Market.handleAction(player, services, select(2, ...))' in scode
    assert 'Barter.handleAction(player, services, ...)' in scode
    assert 'coins.Value += quantity * PRICE_PER_ORE' in scode
    assert 'inventory.resources -= quantity' in scode
    assert 'coins.Value > 2147483647 - quantity * PRICE_PER_ORE' in scode
    assert 'remote:InvokeServer("sell", 1)' in ccode
    assert 'remote:InvokeServer(table.unpack(args, 1, args.n))' in ccode
    assert scode.rstrip().endswith("return Service")
    for source, path in (
        (scode, "src/server/Trader.luau"),
        (ccode, "src/client/Trader.client.luau"),
    ):
        errors = [d for d in LuauStaticAnalyzer().analyze_source(source, path)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.line_number, d.message) for d in errors]


def test_explicitly_peer_only_trade_does_not_mint_new_currency():
    server, client, plan = make_plan()
    assert not _needs_earned_currency_market(plan)
    code = render_host_peer_barter(server, plan)
    assert code and 'Market.handleAction' not in code


def test_earning_requires_resource_and_currency_and_transaction_source():
    server, client, plan = make_plan()
    for prompt in (
        "Trade equipment between two players",
        "Mine ores and build spacecraft; no money economy",
        "Buy weapons using existing credits, but no mining",
    ):
        plan.requested_prompt = prompt
        assert not _needs_earned_currency_market(plan)
