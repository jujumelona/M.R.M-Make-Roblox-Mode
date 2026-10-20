"""Trading is a real server transaction, not a coder-generated empty shell."""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_trading import render_host_trading
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService

def make_plan():
    miner = RobloxModuleSpec(
        module_id="dyn_332e450bdd43",
        name="ResourceMiningEconomy0388601Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ResourceMiningEconomy0388601Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("Server validates mining actions within resource node range "
                     "and updates the player's currency balance."),
        depends_on=[],
    )
    mining_client = RobloxModuleSpec(
        module_id="dyn_b1828fd6910d",
        name="ResourceMiningEconomy0388601Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ResourceMiningEconomy0388601Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Displays mining rewards and player currency for each resource node.",
        depends_on=[],
    )
    plan = SimpleNamespace(
        requested_prompt="Mine ore and sell it for spaceship credits",
        game_design={"dynamic_design": {
            "host_actions": {"ResourceMiningEconomy0388601Action": {
                "service": miner.name, "kind": "RemoteFunction"}},
            "world_objects": [{"name": "ResourceNode03886011", "class": "Part"}],
        }},
    )
    return miner, mining_client, plan



class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Host market mechanic must not invoke small model")


def make_trade():
    miner, mining_client, plan = make_plan()
    trade_server = RobloxModuleSpec(
        module_id="dyn_d0ee1816f2eb",
        name="ResourceTrading0388602Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ResourceTrading0388602Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server owns resource trading. When a player requests a "
                     "trade, the server validates the player's resource quantity "
                     "and credits currency from the trade price."),
        depends_on=[],
    )
    trade_client = RobloxModuleSpec(
        module_id="dyn_d4d781144c59",
        name="ResourceTrading0388602Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ResourceTrading0388602Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=("The client displays the player's resource quantities and "
                     "currency. When a trade is confirmed the client updates UI."),
        depends_on=["mod_network_bridge"],
    )
    design = plan.game_design["dynamic_design"]
    design["host_actions"]["ResourceTrading0388602Action"] = {
        "service": trade_server.name, "kind": "RemoteFunction"}
    plan.modules = [miner, mining_client, trade_server, trade_client]
    return trade_server, trade_client, plan


def test_mining_and_trading_complete_without_model_file_generation():
    server, client, proposal = make_trade()
    gen = LuauCodeGenerator(router=NoModel())
    s = gen.generate_module_code(server, proposal)
    c = gen.generate_module_code(client, proposal)
    assert s == render_host_trading(server, proposal)
    assert c == render_host_trading(client, proposal)
    assert s.count("function Service.handleAction(") == 1
    assert s.rstrip().endswith("return Service")
    assert "GetState(player, \"RMMInventory\")" in s
    assert "inventory.resources -= quantity" in s
    assert "coins.Value += quantity * PRICE_PER_ORE" in s
    assert "type(quantity) ~= \"number\"" in s
    assert "inventory.resources < quantity" in s
    assert "brokerStock += quantity" in s
    assert "remote:InvokeServer(1)" in c
    assert "Coins.Value +=" not in c


def test_trade_cannot_invent_unearned_resources():
    server, client, proposal = make_trade()
    proposal.game_design["dynamic_design"]["world_objects"] = []
    assert render_host_trading(server, proposal) is None
    assert render_host_trading(client, proposal) is None
    proposal.game_design["dynamic_design"]["world_objects"] = [
        {"name": "ResourceNode03886011", "class": "Part"}]
    proposal.game_design["dynamic_design"]["host_actions"].pop("ResourceTrading0388602Action")
    assert render_host_trading(server, proposal) is None


def test_trading_source_static_checks():
    server, client, proposal = make_trade()
    analyzer = LuauStaticAnalyzer()
    for module in (server, client):
        generated = render_host_trading(module, proposal)
        errors = [d for d in analyzer.analyze_source(generated, module.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.line_number, d.message) for d in errors]
