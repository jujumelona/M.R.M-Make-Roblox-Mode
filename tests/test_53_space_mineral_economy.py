"""Report 53: server-owned alien mineral mining / brokerage integration.

These tests validate emitted Luau contracts, not multiplayer Studio physics.
"""
from tests.test_host_trading import make_trade
from tests.test_report41_host_space_actions import fixture
from roblox_mod_ai.host_trading import render_host_trading
from roblox_mod_ai.host_space_actions import render_host_space_action
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer


def _space_market():
    server,client,plan=make_trade()
    space=fixture()
    pd=plan.game_design["dynamic_design"]
    sd=space.game_design["dynamic_design"]
    for key in ("module_remotes","host_typed_actions","remotes",
                "module_world_objects","host_vehicle_identity_bindings",
                "host_arrival_materializations"):
        pd[key]=sd[key]
    pd["world_objects"].extend(sd["world_objects"])
    plan.modules.extend(space.modules)
    return server,client,plan


def test_alien_mineral_sale_is_opt_in_and_server_authoritative():
    server,client,plan=_space_market()
    lua=render_host_trading(server,plan)
    ui=render_host_trading(client,plan)
    assert lua and ui
    for fragment in (
        'request.resource~="alien_mineral"',
        'request.quantity',
        'if key~="resource" and key~="quantity"',
        'GetState(player,"RMMPlanetProgress")',
        'planet.planetOwned~=true or planet.colonized~=true',
        'local PRICE_PER_ALIEN_MINERAL=15',
        'planet.minerals=balance-quantity',
        'coins.Value+=payout',
        'trades.alienMineralsSold=',
        'player:SetAttribute("RMMPlanetMinerals",planet.minerals)',
        'remainingMinerals=kind=="alien_mineral" and planet.minerals',
    ):
        assert fragment in lua,fragment
    assert lua.index('planet.minerals=balance-quantity') < lua.index('coins.Value+=payout')
    assert 'makeButton("SellOre"' in ui
    assert 'makeButton("SellAlienMineral"' in ui
    assert 'local scroll=Instance.new("ScrollingFrame")' in ui
    assert 'resource="alien_mineral",quantity=1' in ui
    assert 'coins.Value+=' not in ui


def test_ordinary_mining_market_has_no_speculative_planet_sale():
    server,client,plan=make_trade()
    lua=render_host_trading(server,plan)
    ui=render_host_trading(client,plan)
    assert lua and ui
    assert "RMMPlanetProgress" not in lua
    assert "SellAlienMineral" not in ui
    assert 'remote:InvokeServer(1)' in ui


def test_alien_mineral_stock_recovers_with_persisted_server_clock():
    space=fixture()
    mod=next(m for m in space.modules if m.name.startswith("ExtractOtherPlanetMineral")
             and m.name.endswith("Server"))
    lua=render_host_space_action(mod,space)
    assert lua is not None
    for token in (
        'state.mineralRefillAt',
        'os.time()',
        'state.mineralRefillAt=wallNow+120',
        'if wallNow<refillAt then',
        'stock=100',
        'state.mineralRemaining=stock-args.quantity',
        'player:SetAttribute("RMMPlanetMinerals",state.minerals)',
        'refillAt=state.mineralRefillAt',
    ):
        assert token in lua,token
    assert lua.index('if args.quantity>stock then') < lua.index('state.minerals=amount+args.quantity')


def test_space_market_luau_static_analysis():
    server,client,plan=_space_market()
    analyzer=LuauStaticAnalyzer()
    for m in (server,client):
        lua=render_host_trading(m,plan)
        assert lua
        errors=[(d.rule,d.line_number,d.message) for d in
                analyzer.analyze_source(lua,m.file_path) if d.severity=="ERROR"]
        assert not errors,errors
