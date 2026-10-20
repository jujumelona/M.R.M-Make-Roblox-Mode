"""Proposal (20) regression: a valid mining Remote had no declared mineable Part.

The implementation must create the minimal REAL world prerequisite from the
user's request BEFORE any 9B full-file generation, and must use the same
server-authoritative inventory and currency state afterward.
"""
import copy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class FailIfCalled:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("The small coder must not author a complete mining service")

    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("The small coder must not author a mining contract")


def proposal20():
    server = RobloxModuleSpec(
        module_id="dyn_f4276c85020a",
        name="ResourceMiningEconomy0388601Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ResourceMiningEconomy0388601Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server owns the resource economy. When a player performs "
            "a mining action, the server validates the action, applies a "
            "resource yield to the player's owned currency, and records "
            "the transaction in the player's economy state. The server "
            "enforces that mining actions are only valid while the player "
            "is in Space Mode, that the player has access to the required "
            "mining tool or station, and that the resource yield is "
            "bounded by the active mining rate. The server rejects invalid "
            "actions and returns a failure result without granting currency."
        ),
    )
    client = RobloxModuleSpec(
        module_id="dyn_61bdf2bd48ce",
        name="ResourceMiningEconomy0388601Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ResourceMiningEconomy0388601Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=(
            "The client displays the mining action result and the resulting "
            "currency balance after the server confirms the transaction."
        ),
    )
    design = {
        "host_actions": {
            "ResourceMiningEconomy0388601Action": {
                "service": server.name, "kind": "RemoteFunction",
            },
        },
        "host_world_actions": {
            "LaunchGate93682111": {"service": "LaunchGate9368211Server",
                                    "action_text": "Launch Gate"},
        },
        "world_objects": [
            {"name": "LaunchGate93682111", "class": "Part",
             "position": [24, 2, 24], "size": [4, 4, 4]},
            {"name": "AlienEnemy1F017B11", "class": "Part",
             "position": [36, 2, 24], "size": [4, 4, 4]},
        ],
        "module_world_objects": {server.module_id: [], client.module_id: []},
        "remotes": {"ResourceMiningEconomy0388601Action": "RemoteFunction"},
    }
    return RobloxProposal(
        requested_prompt=(
            "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
            "부위마다 만들어서 만들수있고 업그레이드해서 우주로 나간다"
        ),
        game_title="SpaceMining",
        description="Mining first, then ship building, then space exploration",
        game_design={"dynamic_design": design},
        modules=[server, client],
    )


def test_real_plan_missing_node_is_materialized_and_both_roles_are_host_owned():
    p = proposal20()
    miner, client = p.modules
    assert render_host_mining(miner, p) is None
    updates = ensure_mining_world_contract(p)
    assert len(updates) == 1
    assert updates[0]["resource_node"] == "ResourceNode03886011"
    assert updates[0]["input"] == "RemoteFunction_with_server_verified_Part"
    assert p.game_design["dynamic_design"]["world_objects"][-1]["name"] == updates[0]["resource_node"]
    assert p.game_design["dynamic_design"]["module_world_objects"][miner.module_id] == ["ResourceNode03886011"]
    assert p.game_design["dynamic_design"]["module_world_objects"][client.module_id] == ["ResourceNode03886011"]
    assert not ensure_mining_world_contract(p), "Preflight must be idempotent"
    gen = LuauCodeGenerator(FailIfCalled())
    server_source = gen.generate_with_self_correction(miner, p)
    client_source = gen.generate_with_self_correction(client, p)
    assert server_source == render_host_mining(miner, p)
    assert client_source == render_host_mining(client, p)
    assert 'local NODE_NAMES = {"ResourceNode03886011"}' in server_source
    assert "(root.Position - part.Position).Magnitude > MAX_RANGE" in server_source
    assert 'GetState(player, "RMMInventory")' in server_source
    assert "node.remaining -= 1" in server_source
    assert "coins.Value += 1" in server_source
    assert "remote:InvokeServer(target)" in client_source
    assert "claimedYield" not in server_source
    assert "miningRateFactorOverride" not in server_source
    bootstrap = render_dynamic_server_bootstrap(p)
    assert 'WaitForChild("ResourceMiningEconomy0388601Action")' in bootstrap
    assert "remote.OnServerInvoke = function(player, ...)" in bootstrap


def test_real_plan_materialization_cannot_steal_unrelated_world_objects():
    p = proposal20()
    before = copy.deepcopy(p.game_design["dynamic_design"]["world_objects"])
    ensure_mining_world_contract(p)
    after = p.game_design["dynamic_design"]["world_objects"]
    assert after[:2] == before
    assert len(after) == 3
    assert after[-1]["position"] not in [obj["position"] for obj in before]
    assert after[-1]["class"] == "Part"
    assert after[-1]["name"].startswith("ResourceNode")


def test_no_world_invention_without_mining_request_or_authenticated_remote():
    p = proposal20()
    p.requested_prompt = "Build a spaceship with no mining"
    # The request explicitly excludes mining; the host cannot add a node.
    p.requested_prompt = "우주선 조립과 업그레이드"
    assert not ensure_mining_world_contract(p)
    p = proposal20()
    p.game_design["dynamic_design"]["host_actions"]["ResourceMiningEconomy0388601Action"]["kind"] = "RemoteEvent"
    assert not ensure_mining_world_contract(p)
    p = proposal20()
    p.game_design["dynamic_design"]["host_actions"]["ResourceMiningEconomy0388601Action"]["max_args"] = 0
    assert not ensure_mining_world_contract(p)


def test_proposal20_host_luau_source_and_bootstrap_pass_static_validation():
    p = proposal20()
    ensure_mining_world_contract(p)
    gen = LuauCodeGenerator(FailIfCalled())
    analyzer = LuauStaticAnalyzer()
    for m in p.modules:
        code = gen.generate_with_self_correction(m, p)
        diagnostics = analyzer.analyze_source(code, file_path=m.file_path)
        assert not [d for d in diagnostics if d.severity == "ERROR"]
    bootstrap = render_dynamic_server_bootstrap(p)
    assert not [d for d in analyzer.analyze_source(bootstrap, "src/server/RMMServerBootstrap.server.luau")
                if d.severity == "ERROR"]
