"""End-to-end dispatch regressions for the uploaded mining-generation failure."""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService


class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Common mining gameplay must not invoke the 9B model")


def make_plan():
    server = RobloxModuleSpec(
        module_id="dyn_332e450bdd43",
        name="ResourceMiningEconomy0388601Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ResourceMiningEconomy0388601Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server owns the mining economy. When a player performs a "
                     "mining action, it validates the range to a resource node "
                     "and awards currency."),
        depends_on=[],
    )
    client = RobloxModuleSpec(
        module_id="dyn_b1828fd6910d",
        name="ResourceMiningEconomy0388601Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ResourceMiningEconomy0388601Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=("The client displays currency when mining a resource node "
                     "and shows depletion."),
        depends_on=["mod_network_bridge"],
    )
    design = {"host_actions": {"ResourceMiningEconomy0388601Action": {
                  "service": server.name, "kind": "RemoteFunction"}},
              "world_objects": [{"name": "ResourceNode03886011", "class": "Part"}]}
    proposal = SimpleNamespace(
        requested_prompt="Mine resources and earn currency to build a spaceship",
        game_design={"dynamic_design": design},
    )
    return server, client, proposal


def test_host_implements_the_first_failed_server_without_model():
    server, client, proposal = make_plan()
    gen = LuauCodeGenerator(router=NoModel())
    code = gen.generate_module_code(server, proposal)
    assert code == render_host_mining(server, proposal)
    assert code.count("function Service.start(") == 1
    assert code.count("function Service.handleAction(") == 1
    assert code.rstrip().endswith("return Service")
    assert 'local NODE_NAMES = {"ResourceNode03886011"}' in code
    assert "local node = getNode(part)" in code
    assert "targetPart" not in code
    assert "(root.Position - part.Position).Magnitude > MAX_RANGE" in code
    assert "now - recent[player] < COOLDOWN" in code
    assert "node.remaining -= 1" in code
    assert "coins.Value += 1" in code
    assert "GetState(player, \"RMMInventory\")" in code
    assert 'SetAttribute("ResourceDepleted"' in code
    assert "LocalPlayer" not in code
    assert "player:Kick" not in code
    assert "return Service" in code


def test_mining_client_has_reachable_input_with_server_authority():
    _server, client, proposal = make_plan()
    gen = LuauCodeGenerator(router=NoModel())
    code = gen.generate_module_code(client, proposal)
    assert code == render_host_mining(client, proposal)
    assert "button.Activated:Connect" in code
    assert "remote:InvokeServer(target)" in code
    assert 'WaitForChild("ResourceMiningEconomy0388601Action")' in code
    assert "Coins.Value +=" not in code
    assert 'local NODE_NAMES = {"ResourceNode03886011"}' in code


def test_planned_resource_nodes_are_scoped_to_this_mining_mechanic():
    server, client, proposal = make_plan()
    proposal.game_design["dynamic_design"]["world_objects"].append(
        {"name": "ResourceNode7C25E241", "class": "Part"})
    for module in (server, client):
        generated = render_host_mining(module, proposal)
        assert generated is not None
        assert '"ResourceNode03886011"' in generated
        assert '"ResourceNode7C25E241"' not in generated


def test_no_host_substitution_without_real_node_and_route():
    server, client, proposal = make_plan()
    proposal.game_design["dynamic_design"]["world_objects"] = []
    assert render_host_mining(server, proposal) is None
    assert render_host_mining(client, proposal) is None
    proposal.game_design["dynamic_design"]["world_objects"] = [
        {"name": "ResourceNode03886011", "class": "Part"}]
    proposal.game_design["dynamic_design"]["host_actions"] = {}
    assert render_host_mining(server, proposal) is None


def test_host_mining_luau_static_checks_pass():
    server, client, proposal = make_plan()
    analyzer = LuauStaticAnalyzer()
    for module in (server, client):
        source = render_host_mining(module, proposal)
        diagnostics = analyzer.analyze_source(source, module.file_path)
        errors = [d for d in diagnostics if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.line_number, d.message) for d in errors]
