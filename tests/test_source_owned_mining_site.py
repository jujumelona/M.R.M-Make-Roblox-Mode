"""Uploaded proposal (18) / failure_logs (2)(1) source-owned mining regression.

A valid MiningSite03886011 was already in the authored Workspace and explicitly
bound to the server and client. Prefix heuristics missed it, so the 9B coder
wrote an invalid client script. This test verifies server/client dispatch and
no duplicate world objects, without relying on a specific filename convention.
"""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
from roblox_mod_ai.host_mining_nodes import mining_world_nodes
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.luau_service_contract import service_contract_checks
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class NoCoder:
    def complete(self, *args, **kwargs):
        raise AssertionError("9B coder must not generate mining service/client")

    def complete_json(self, *args, **kwargs):
        raise AssertionError("9B coder must not generate mining interface")


def uploaded_mining_plan():
    owner = RobloxModuleSpec(
        module_id="dyn_bfe3b28c21e3",
        name="SpaceModeResourceMiningAn0388601Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/SpaceModeResourceMiningAn0388601Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server owns the economy loop: mining a static world object yields "
            "a fixed amount of game currency, currency is accumulated in a "
            "server-owned player balance, and the balance is the only authoritative "
            "source of funds for all later purchases and upgrades. Mining is "
            "validated server-side: only the player whose validated mining action "
            "is in progress receives the yield, the yield is applied once per "
            "completed mining action, and duplicate or overlapping mining actions "
            "are rejected."
        ),
    )
    client = RobloxModuleSpec(
        module_id="dyn_7df03d9673f1",
        name="SpaceModeResourceMiningAn0388601Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/SpaceModeResourceMiningAn0388601Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=(
            "The client shows the mining action's progress and the resulting currency "
            "gain, then displays the player's current balance. No client-side balance "
            "is trusted for purchases or upgrades."
        ),
        depends_on=["mod_network_bridge"],
    )
    remote = "SpaceModeResourceMiningAn0388601Action"
    return RobloxProposal(
        requested_prompt="우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 부위마다 만들수있고",
        game_title="SpaceMine",
        description="Grounded authored resource mining",
        modules=[owner, client],
        game_design={"dynamic_design": {
            "host_actions": {remote: {"service": owner.name, "kind": "RemoteFunction"}},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {owner.module_id: [remote], client.module_id: [remote]},
            "module_world_objects": {
                owner.module_id: ["MiningSite03886011"],
                client.module_id: ["MiningSite03886011"],
            },
            "world_objects": [
                {"name": "MiningSite03886011", "class": "Part",
                 "position": [24, 2, 24], "size": [4, 4, 4]},
                {"name": "AlienEnemy1F017B11", "class": "Part",
                 "position": [36, 2, 24], "size": [4, 4, 4]},
                {"name": "SpecialMineral1F017B12", "class": "Part",
                 "position": [48, 2, 24], "size": [4, 4, 4]},
            ],
        }},
    )


def test_uploaded_existing_mining_site_is_reused_not_silently_duplicated():
    p = uploaded_mining_plan()
    prior = deepcopy(p.game_design["dynamic_design"])
    assert mining_world_nodes(p, p.modules[0]) == ["MiningSite03886011"]
    assert ensure_mining_world_contract(p) == []
    assert p.game_design["dynamic_design"] == prior


def test_failed_mining_client_and_server_both_use_host_not_malformed_coder():
    p = uploaded_mining_plan()
    generator = LuauCodeGenerator(NoCoder())
    for module in p.modules:
        module.code = "-- stale malformed Luau from previous model attempt"
    result = generator.generate_all_modules(p)
    assert len(result) == 2
    server, client = [m.code for m in result]
    assert server == render_host_mining(p.modules[0], p)
    assert client == render_host_mining(p.modules[1], p)
    assert 'local NODE_NAMES = {"MiningSite03886011"}' in server
    assert 'local NODE_NAMES = {"MiningSite03886011"}' in client
    assert "SpecialMineral1F017B12" not in server
    assert "AlienEnemy1F017B11" not in server
    assert "coins.Value += 1" in server
    assert 'GetState(player, "RMMInventory")' in server
    assert "(root.Position - part.Position).Magnitude > MAX_RANGE" in server
    assert "node.remaining -= 1" in server
    assert "remote:InvokeServer(target)" in client
    assert "button.Activated:Connect" in client
    assert "ServerScriptService" not in client
    checks = service_contract_checks(p.modules[0].name, server, require_start=True,
                                     needs_action=True)
    assert all(row["passed"] for row in checks), checks


def test_exact_remote_and_world_part_are_preserved_in_rojo(tmp_path):
    p = uploaded_mining_plan()
    rojo = RobloxProjectGenerator(tmp_path).generate_rojo_project_json(p)
    world = rojo["tree"]["Workspace"]
    assert world["MiningSite03886011"]["$className"] == "Part"
    assert world["SpecialMineral1F017B12"]["$className"] == "Part"
    assert sum(name.startswith("ResourceNode") for name in world) == 0
    assert rojo["tree"]["ReplicatedStorage"]["Remotes"][
        "SpaceModeResourceMiningAn0388601Action"]["$className"] == "RemoteFunction"
    bootstrap = render_dynamic_server_bootstrap(p)
    assert "remote.OnServerInvoke = function(player, ...)" in bootstrap
    assert 'WaitForChild("SpaceModeResourceMiningAn0388601Action", 20)' in bootstrap


def test_no_client_server_luau_syntax_errors_in_uploaded_mining_shape():
    p = uploaded_mining_plan()
    analyzer = LuauStaticAnalyzer()
    gen = LuauCodeGenerator(NoCoder())
    for module in p.modules:
        script = gen.generate_with_self_correction(module, p)
        errors = [d for d in analyzer.analyze_source(script, module.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.message) for d in errors]


def test_no_resource_stealing_on_explicit_incorrect_ownership():
    p = uploaded_mining_plan()
    d = p.game_design["dynamic_design"]
    d["module_world_objects"][p.modules[0].module_id] = ["AlienEnemy1F017B11"]
    assert mining_world_nodes(p, p.modules[0]) == []
    assert render_host_mining(p.modules[0], p) is None
    p = uploaded_mining_plan()
    d = p.game_design["dynamic_design"]
    d["host_world_actions"] = {"MiningSite03886011": {
        "service": "UnrelatedPlanetMiningService"}}
    assert mining_world_nodes(p, p.modules[0]) == []
    assert render_host_mining(p.modules[0], p) is None


def test_unowned_foreign_resource_site_is_never_assumed_for_other_mechanic():
    p = uploaded_mining_plan()
    d = p.game_design["dynamic_design"]
    d["module_world_objects"][p.modules[0].module_id] = []
    assert mining_world_nodes(p, p.modules[0]) == []
    assert render_host_mining(p.modules[0], p) is None
    assert ensure_mining_world_contract(p), "Host must add its own target instead"
