"""Player counterparty requests must have consent and a shared server ledger."""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_peer_trade import render_host_peer_trade
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService


class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Host peer trading should not ask the model for full files")


def make_plan():
    def m(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_" + name, name=name, kind=kind,
            file_path=("src/server/" + name + ".luau"
                       if kind == ModuleKind.SERVER_MODULE
                       else "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc, depends_on=[])
    mine = m("ResourceMiningEconomy0388601Server", ModuleKind.SERVER_MODULE,
             "Server validates mining at a resource node and credits earned currency.")
    trade = m("ResourceTrading0388603Server", ModuleKind.SERVER_MODULE,
              "The server owns the trading system. When a player attempts to trade a resource, "
              "the server validates the player's inventory, trade offer and trade counterparty.")
    client = m("ResourceTrading0388603Client", ModuleKind.CLIENT_SCRIPT,
               "Client displays the trading interface and the resulting trade outcome.")
    design = {"world_objects": [{"name": "ResourceNode03886011", "class": "Part"}],
              "host_actions": {
                  "ResourceMiningEconomy0388601Action": {
                      "service": mine.name, "kind": "RemoteFunction"},
                  "ResourceTrading0388603Action": {
                      "service": trade.name, "kind": "RemoteFunction"}}}
    return trade, client, SimpleNamespace(modules=[mine, trade, client],
        game_design={"dynamic_design": design}, requested_prompt="Trade earned ore with other players")


def test_peer_trade_wired_without_model_and_no_client_balance_trust():
    server, client, proposal = make_plan()
    generator = LuauCodeGenerator(router=NoModel())
    sc = generator.generate_module_code(server, proposal)
    cc = generator.generate_module_code(client, proposal)
    assert sc == render_host_peer_trade(server, proposal)
    assert cc == render_host_gameplay(client, proposal)
    assert "offer.buyer ~= player.UserId" in sc
    assert "sellerInv.resources < 1" in sc
    assert "buyerCoins.Value < PRICE" in sc
    assert "offers[value] = nil" in sc
    assert "sellerInv.resources -= 1" in sc
    assert "buyerInv.resources = buyerResources + 1" in sc
    assert "buyerCoins.Value -= PRICE" in sc
    assert "sellerCoins.Value += PRICE" in sc
    assert "remote:InvokeServer(\"offer\", recipient.UserId)" in cc
    assert "remote:InvokeServer(\"accept\", id)" in cc
    assert "local Service = {}" in sc
    assert sc.rstrip().endswith("return Service")


def test_no_peer_trade_without_real_producer_and_authenticated_remote():
    server, client, proposal = make_plan()
    proposal.modules = [server, client]
    assert render_host_peer_trade(server, proposal) is None
    proposal = make_plan()[2]
    proposal.game_design["dynamic_design"]["host_actions"]["ResourceTrading0388603Action"]["kind"] = "RemoteEvent"
    assert render_host_peer_trade(server, proposal) is None


def test_both_roles_pass_static_luau_checks():
    server, client, proposal = make_plan()
    analyzer = LuauStaticAnalyzer()
    for mod in (server, client):
        code = render_host_peer_trade(mod, proposal)
        errors = [d for d in analyzer.analyze_source(code, mod.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(e.rule, e.line_number, e.message) for e in errors]
