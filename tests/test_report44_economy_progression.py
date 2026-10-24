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


def test_paid_first_weapon_purchase_unblocks_real_weapon_upgrade_dependency():
    from test_plan83_rank_protocol import fixture, Router
    from roblox_mod_ai.host_level_upgrade import render_rank_protocol
    proposal, server, client, remote = fixture(target="owned_weapon", owned=True)
    proposal.requested_prompt = (
        "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장할 수 있다"
    )
    server_code = render_rank_protocol(server, proposal, Router())
    client_code = render_rank_protocol(client, proposal, Router())
    assert 'local ACQUIRE_FIRST=true' in server_code
    assert 'if not acquired and not ACQUIRE_FIRST' in server_code
    assert 'coins.Value-=COST' in server_code
    assert 'inventory.items[TARGET]=1' in server_code
    assert 'ranks[TARGET]=nextRank' in server_code
    assert server_code.index('coins.Value-=COST') < server_code.index('inventory.items[TARGET]=1')
    assert 'result.acquired' in client_code
    assert 'remote:InvokeServer("owned_weapon")' in client_code


def test_owned_weapon_upgrade_only_never_grants_unrequested_asset():
    from test_plan83_rank_protocol import fixture, Router
    from roblox_mod_ai.host_level_upgrade import render_rank_protocol
    proposal, server, client, remote = fixture(target="owned_weapon", owned=True)
    proposal.requested_prompt = "Upgrade an already owned weapon using earned coins"
    code = render_rank_protocol(server, proposal, Router())
    assert 'local ACQUIRE_FIRST=false' in code
    assert 'return {success=false,reason="not_owned"}' in code


def test_first_purchase_only_for_canonical_weapon_item_and_own_price():
    from roblox_mod_ai.host_level_upgrade import _allows_paid_first_ownership
    from types import SimpleNamespace
    proposal = SimpleNamespace(requested_prompt="무기 구매")
    assert not _allows_paid_first_ownership(proposal, "owned_weapon",
                                            "Apply damage upgrade", True)
    assert not _allows_paid_first_ownership(proposal, "crew",
                                            "Purchase weapon upgrade", True)
    assert not _allows_paid_first_ownership(proposal, "owned_weapon",
                                            "Purchase weapon upgrade", False)
    assert _allows_paid_first_ownership(proposal, "owned_weapon",
                                        "Validate purchase weapon upgrade", True)


def test_server_state_exchange_is_not_rejected_for_missing_trade_keyword():
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    source = "Trade mined resources for earned credits"
    server = (
        "The server validates the player's owned resource quantity and "
        "the server-fixed sale price, debits the resource and credits "
        "earned game currency to the authenticated player's wallet."
    )
    errors = source_intent_conflicts(source, server)
    assert not any("SOURCE_TRADE_ACTION_MISSING" in x for x in errors), errors
    missing = "The server validates both values but updates neither balance."
    assert any("SOURCE_TRADE_ACTION_MISSING" in x
               for x in source_intent_conflicts(source, missing))
