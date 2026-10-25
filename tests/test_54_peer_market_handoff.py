"""54: the peer-described trade generated from a vague earning-money request
must reuse the same source-verified ore + alien-mineral broker as direct trade.

Do not substitute author descriptions for the original user's authorization.
"""
from tests.test_host_trading import make_trade
from tests.test_report41_host_space_actions import fixture
from roblox_mod_ai.host_peer_barter import render_host_peer_barter
from roblox_mod_ai.host_trading import market_templates_for_plan, render_host_trading


def _plan(space: bool):
    server, client, plan = make_trade()
    # Reproduce the actual repeated 54-series producer name and peer-phrased
    # planner description that used to bypass report53's market routing.
    server.name="ServerPriceTrade4533282Server"
    client.name="ServerPriceTrade4533282Client"
    server.description=("Validate the trade request against the server-owned "
        "catalog and seller-owned inventory, then transfer the seller's "
        "owned currency to the buyer and mark the item as owned by the buyer. "
        "Reject requests for unowned inventory.")
    plan.requested_prompt=("우주모드 인데 자원파밍 돈모으기 거래 등으로 "
        "우주선을 부위마다 만들고 다른행성의 특수 광물을 채굴")
    actions=plan.game_design["dynamic_design"]["host_actions"]
    actions["ServerPriceTrade4533282Action"]=actions.pop("ResourceTrading0388602Action")
    actions["ServerPriceTrade4533282Action"]["service"]=server.name
    if space:
        planet=fixture()
        d=plan.game_design["dynamic_design"]
        pd=planet.game_design["dynamic_design"]
        for key in ("module_remotes", "host_typed_actions", "remotes",
                    "module_world_objects", "host_vehicle_identity_bindings",
                    "host_arrival_materializations"):
            d[key]=pd[key]
        d["world_objects"].extend(pd["world_objects"])
        plan.modules.extend(planet.modules)
    return server,client,plan


def test_real_peer_wording_handoff_uses_space_market_when_planet_owned():
    server,client,plan=_plan(True)
    ss=render_host_peer_barter(server,plan)
    cc=render_host_peer_barter(client,plan)
    assert ss and cc
    assert ss==market_templates_for_plan(plan)[0]
    assert 'PRICE_PER_ALIEN_MINERAL=15' in ss
    assert 'GetState(player,"RMMPlanetProgress")' in ss
    assert 'planet.minerals=balance-quantity' in ss
    assert 'coins.Value+=payout' in ss
    assert 'makeButton("SellAlienMineral"' in cc
    assert 'makeButton("SellOre"' in cc
    assert 'ServerPriceTrade4533282Action' in cc
    assert 'remote:InvokeServer(1)' not in cc


def test_market_without_planet_keeps_ore_only_contract():
    server,client,plan=_plan(False)
    ss=render_host_peer_barter(server,plan)
    cc=render_host_peer_barter(client,plan)
    assert ss and cc
    assert "RMMPlanetProgress" not in ss
    assert "SellAlienMineral" not in cc
    assert 'remote:InvokeServer(1)' in cc


def test_false_positive_planet_description_cannot_enable_market():
    server,client,plan=_plan(False)
    # AI-authored words are not verified game-world or producer evidence.
    server.description += " extract other planet mineral colonization"
    assert "RMMPlanetProgress" not in render_host_peer_barter(server,plan)
