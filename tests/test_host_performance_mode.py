"""Replay real failed SpaceModeF5E8F01Server scoped-body generation on the host.

A short model generated 3 invalid bodies for this contract. The host must
own the threshold and source-of-truth lookup instead of requesting Luau.
"""
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_performance_mode import (
    eligible_performance_mode, render_host_performance_mode,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.luau_service_contract import service_contract_checks
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Ship performance mode gate must not ask model for Luau")

    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Ship mode threshold is already authored in contract")


def fixture(threshold=100, mode="space", server_name="SpaceModeF5E8F01Server"):
    def mod(name, kind, description):
        return RobloxModuleSpec(
            module_id="dyn_" + name, name=name, kind=kind,
            file_path=("src/server/" + name + ".luau"
                       if kind == ModuleKind.SERVER_MODULE else
                       "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE else
                            RobloxService.STARTER_PLAYER_SCRIPTS),
            description=description,
        )
    server = mod(server_name, ModuleKind.SERVER_MODULE,
        f"The server owns the {mode}-mode state machine and validates every "
        f"mode transition. A player may only enter {mode} mode when the ship's "
        f"performance value is at least {threshold}, and the server rejects "
        "the transition with a clear message otherwise. The server tracks "
        "the player's current mode, the ship's performance value, and the "
        "player's accumulated currency. Entering this mode is a "
        "server-authoritative state change; the server does not rely on "
        "client-reported values.")
    client_name = server_name.removesuffix("Server") + "Client"
    client = mod(client_name, ModuleKind.CLIENT_SCRIPT,
        "The client displays the current mode and the ship's performance "
        "value. On transition it shows the server result or rejection.")
    builder = mod("IndependentVesselAssemblyServer", ModuleKind.SERVER_MODULE,
        "The server owns the ship assembly state and validates every part "
        "addition, removal and swap before applying it. The part must be "
        "owned and satisfy the structural rules for the ship class.")
    action = "ArbitraryModeAction"
    p = RobloxProposal(
        requested_prompt="A game where a player builds and upgrades any vessel",
        game_title="Mode Gate Reproduction",
        description="Minimum-ship-performance game mode",
        modules=[server, client, builder],
        game_design={"dynamic_design": {
            "host_actions": {
                action: {"service": server.name, "kind": "RemoteFunction"},
            },
            "remotes": {action: "RemoteFunction"},
            "module_remotes": {
                server.module_id: [action], client.module_id: [action],
            },
            "host_world_actions": {}, "world_objects": [],
        }},
    )
    return p, server, client, builder


def test_actual_failed_mode_contract_no_long_model_luau_required():
    p, server, client, _ = fixture()
    assert eligible_performance_mode(server, p) == (
        server.name, "ArbitraryModeAction", 100, "Space Mode"
    )
    assert eligible_performance_mode(client, p)
    scope = generation_scope(p)
    routing = {m["name"]: m["strategy"] for m in scope["modules"]}
    missing = scope["unverified_cross_module_dependencies"]
    assert len(missing) == 1
    assert missing[0]["consumer"] == server.name
    assert missing[0]["threshold"] == 100
    assert missing[0]["status"] == "unverified_producer_contract"
    assert routing[server.name] == "host_verified_template"
    assert routing[client.name] == "host_verified_template"
    coder = LuauCodeGenerator(NoModel())
    owner_code = coder.generate_with_self_correction(server, p)
    client_code = coder.generate_with_self_correction(client, p)
    assert owner_code == render_host_performance_mode(server, p)
    assert client_code == render_host_gameplay(client, p)
    assert "local REQUIRED_PERFORMANCE = 100" in owner_code
    assert 'manager.GetState(player, "RMMShipSections")' in owner_code
    assert 'manager.GetState(player, "RMMShipBuild")' in owner_code
    assert 'manager.GetState(player, "RMMGameMode")' in owner_code
    assert 'part.owned == true' in owner_code
    assert 'player:GetAttribute("RMMShipPerformance")' in owner_code
    assert 'player:GetAttribute("RMMShipAssemblyPerformance")' in owner_code
    assert "score >= REQUIRED_PERFORMANCE" in owner_code
    assert 'state.activeMode = MODE' in owner_code
    assert '"insufficient_ship_performance"' in owner_code
    assert 'return {success = false, reason = "ship_not_built"}' not in owner_code
    assert '"ship_not_built"' in owner_code
    assert 'request ~= "enter" and request ~= "status"' in owner_code
    assert 'select("#", ...) ~= 1' in owner_code
    assert 'coins.Value +=' not in owner_code
    assert 'coins.Value -=' not in owner_code
    assert 'RMMInSpace' not in owner_code
    assert 'character:PivotTo' not in owner_code
    assert "PlayerDataManager:GetState" not in owner_code
    assert 'remote:InvokeServer("enter")' not in client_code
    assert 'remote:InvokeServer(action)' in client_code
    assert 'call("enter")' in client_code
    assert 'call("status")' in client_code
    assert '"ArbitraryModeAction"' in client_code
    for module, code in ((server, owner_code), (client, client_code)):
        problems = [d for d in LuauStaticAnalyzer().analyze_source(code, module.file_path)
                    if d.severity == "ERROR"]
        assert not problems, [(d.rule, d.line_number, d.message) for d in problems]
    checks = service_contract_checks(server.name, owner_code, require_start=True, needs_action=True)
    assert all(item["passed"] for item in checks), checks


def test_threshold_is_authored_data_not_prompt_specific_constant():
    p, server, client, _ = fixture(threshold=175, mode="arena",
                                    server_name="GenericArenaTravelServer")
    assert eligible_performance_mode(server, p) == (
        server.name, "ArbitraryModeAction", 175, "Arena Mode"
    )
    assert "local REQUIRED_PERFORMANCE = 175" in render_host_performance_mode(server, p)
    assert 'local MODE = "Arena Mode"' in render_host_performance_mode(server, p)
    assert '"Arena Mode"' in render_host_performance_mode(client, p)


@pytest.mark.parametrize("bad_value", [0, 100001])
def test_invalid_threshold_fails_closed(bad_value):
    p, server, _, _ = fixture(threshold=bad_value)
    assert eligible_performance_mode(server, p) is None


def test_missing_real_builder_or_client_route_fails_closed():
    p, server, client, builder = fixture()
    p.modules.remove(builder)
    assert eligible_performance_mode(server, p) is None
    p, server, client, _ = fixture()
    p.game_design["dynamic_design"]["remotes"]["ArbitraryModeAction"] = "RemoteEvent"
    assert eligible_performance_mode(server, p) is None
    p, server, client, _ = fixture()
    p.game_design["dynamic_design"]["module_remotes"][client.module_id] = ["WrongRoute"]
    assert eligible_performance_mode(client, p) is None
    p, server, client, _ = fixture()
    server.description = "The server draws an image of a spaceship."
    assert eligible_performance_mode(server, p) is None


def test_mode_gate_does_not_grant_flight_without_launch_service():
    p, server, _, _ = fixture()
    code = render_host_performance_mode(server, p)
    assert 'state.activeMode = MODE' in code
    assert 'return result' in code
    assert 'RMMInSpace' not in code
    assert 'RMMSpaceUnlocked' not in code
    assert 'character:PivotTo' not in code
    assert 'TeleportService' not in code
