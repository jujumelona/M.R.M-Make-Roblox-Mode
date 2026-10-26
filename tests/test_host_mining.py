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
        # A real RobloxProposal always has a complete module roster. Adapter
        # ownership must be checked against it rather than an unbound mock.
        modules=[server, client],
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


def make_world_prompt_plan():
    """Exact ingress shape from uploaded proposal (19)/failure_logs (7)."""
    from types import SimpleNamespace
    server, _remote_client, _proposal = make_plan()
    server.module_id = "dyn_5d76621aae86"
    server.description = (
        "The server owns the resource economy. When a player mines a resource "
        "node, the server validates the player's proximity and active mining "
        "action, then credits the player's in-game currency with the node's "
        "resource yield and marks the node depleted. The server tracks resource "
        "inventory, currency balance, and node depletion state as authoritative "
        "game data. Currency is earned only through mining and is never "
        "granted by client-side requests."
    )
    design = {
        "host_actions": {},
        "host_world_actions": {
            "ResourceNode03886011": {
                "service": "ResourceMiningEconomy0388601Server",
                "action_text": "Resource Mining Economy",
            },
        },
        "world_objects": [
            {"name": "ResourceNode03886011", "class": "Part"},
            {"name": "AlienEnemy1F017B11", "class": "Part"},
            {"name": "Settlement7C25E211", "class": "Part"},
        ],
        "remotes": {},
    }
    proposal = SimpleNamespace(
        requested_prompt="Space mode resource mining, trading and building",
        game_design={"dynamic_design": design},
        modules=[server],
    )
    return server, proposal


def test_uploaded_proposal_world_prompt_mining_uses_host_luau_not_model():
    """The failing service was world_prompt, not the RemoteFunction test fixture."""
    from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
    from roblox_mod_ai.luau_service_contract import service_contract_checks

    server, proposal = make_world_prompt_plan()
    assert not proposal.game_design["dynamic_design"]["host_actions"]
    generated = LuauCodeGenerator(router=NoModel()).generate_module_code(server, proposal)
    assert generated == render_host_mining(server, proposal)
    assert generated.count("function Service.start(") == 1
    assert generated.count("function Service.handleAction(") == 1
    assert 'local NODE_NAMES = {"ResourceNode03886011"}' in generated
    assert 'GetState(player, "RMMInventory")' in generated
    assert "node.remaining -= 1" in generated
    assert "coins.Value += 1" in generated
    assert "OnServerEvent" not in generated
    assert "OnServerInvoke" not in generated
    assert "prompt.Triggered" not in generated
    checks = service_contract_checks(server.name, generated, require_start=True, needs_action=True)
    assert all(c["passed"] for c in checks), checks

    bootstrap = render_dynamic_server_bootstrap(proposal)
    assert 'workspace:WaitForChild("ResourceNode03886011", 20)' in bootstrap
    assert "prompt.Triggered:Connect(function(player)" in bootstrap
    assert "service.handleAction(player, services, part)" in bootstrap
    assert "remote.OnServerInvoke" not in bootstrap
    analyzer = LuauStaticAnalyzer()
    for code, filepath in (
        (generated, server.file_path),
        (bootstrap, "src/server/RMMServerBootstrap.server.luau"),
    ):
        errors = [d for d in analyzer.analyze_source(code, filepath)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.message) for d in errors]


def test_world_prompt_contract_rejects_missing_or_ambiguous_world_wiring():
    server, proposal = make_world_prompt_plan()
    design = proposal.game_design["dynamic_design"]
    assert render_host_mining(server, proposal) is not None
    design["host_world_actions"]["ResourceNode03886011"]["service"] = "OtherService"
    assert render_host_mining(server, proposal) is None
    design["host_world_actions"]["ResourceNode03886011"]["service"] = server.name
    design["host_world_actions"]["AlienEnemy1F017B11"] = {"service": server.name}
    assert render_host_mining(server, proposal) is None
    design["host_world_actions"].pop("AlienEnemy1F017B11")
    design["host_actions"]["OtherMineRemote"] = {
        "service": server.name, "kind": "RemoteFunction"}
    assert render_host_mining(server, proposal) is None


def test_remote_and_world_input_are_distinct_not_fake_client():
    server, proposal = make_world_prompt_plan()
    from roblox_mod_ai.spec import RobloxModuleSpec
    client = RobloxModuleSpec(
        module_id="dyn_miningunexpected",
        name="ResourceMiningEconomy0388601Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ResourceMiningEconomy0388601Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Displays earned mining resources and currency.",
        depends_on=[],
    )
    proposal.modules.append(client)
    assert render_host_mining(server, proposal) is not None
    assert render_host_mining(client, proposal) is None
