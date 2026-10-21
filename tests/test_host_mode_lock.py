"""Regression: accepted-looking passive mode source must work on join and rejoin."""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_mode_lock import eligible_mode_lock, render_host_mode_lock
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Passive game mode lifecycle belongs to host")


def _plan(*, mode="Space Mode"):
    server = RobloxModuleSpec(
        module_id="dyn_mode_lock",
        name="PlayerModeInvariantServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/PlayerModeInvariantServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            f"The server enforces {mode} as the active game mode "
            "and validates that all gameplay state, progression and world "
            "content operate within the active mode context."
        ),
    )
    return RobloxProposal(
        game_title="General game mode", description="Server owned mode",
        requested_prompt="Create a custom game mode",
        modules=[server],
        game_design={"dynamic_design": {
            "host_actions": {}, "host_world_actions": {},
            "module_world_objects": {server.module_id: []},
        }},
    ), server


def test_passive_game_mode_is_host_owned_and_uses_real_callable_api():
    p, server = _plan()
    assert eligible_mode_lock(server, p) == "Space Mode"
    assert generation_scope(p)["counts"]["host_verified_template"] == 1
    source = LuauCodeGenerator(NoModel()).generate_with_self_correction(server, p)
    assert source == render_host_mode_lock(server, p)
    assert 'local MODE = "Space Mode"' in source
    assert 'manager.GetState(player, NAMESPACE)' in source
    assert 'manager.OnReady(function(player)' in source
    assert 'state.activeMode = MODE' in source
    assert 'workspace:SetAttribute("RMMActiveGameMode", MODE)' in source
    assert 'function Service.getStateForValidation(player)' in source
    assert 'function Service.isActive(player)' in source
    assert 'services[SPACE_MODE_NAMESPACE]' not in source
    assert 'stateChangedCallbacks[player]' not in source
    assert 'PlayerDataManager:GetState' not in source
    assert 'function Service.handleAction' not in source
    errors = [d for d in LuauStaticAnalyzer().analyze_source(source, server.file_path)
              if d.severity == "ERROR"]
    assert not errors, [(d.rule, d.line_number, d.message) for d in errors]


def test_mode_lock_is_not_specific_to_space_prompt_or_name():
    p, server = _plan(mode="Arena Mode")
    server.name = "CustomRulesServer"
    server.file_path = "src/server/CustomRulesServer.luau"
    assert eligible_mode_lock(server, p) == "Arena Mode"
    assert 'local MODE = "Arena Mode"' in render_host_mode_lock(server, p)


def test_ineligible_mode_with_route_or_wrong_description_fails_closed():
    p, server = _plan()
    p.game_design["dynamic_design"]["host_actions"]["ChangeMode"] = {
        "service": server.name, "kind": "RemoteFunction",
    }
    assert eligible_mode_lock(server, p) is None
    p, server = _plan()
    server.description = "A client purchase changes the active game mode."
    assert eligible_mode_lock(server, p) is None
    p, server = _plan()
    peer = RobloxModuleSpec(
        module_id="dyn_second_mode", name="DifferentModeLockServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/DifferentModeLockServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="The server enforces Arena Mode as the active game mode and validates its context.",
    )
    p.modules.append(peer)
    assert eligible_mode_lock(server, p) is None
