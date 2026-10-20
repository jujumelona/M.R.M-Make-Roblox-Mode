"""Manual execution-path audit of Roblox host-generated source.

Checks concrete runtime hazards in the emitted Roblox gateway rather than
declaring a synthetic game or Roblox Studio session successful.
"""
import pytest

from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.host_world_setup import render_host_world_setup
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


def game_with_action(kind="RemoteFunction", max_args=2):
    service = RobloxModuleSpec(
        module_id="dyn_gateway", name="CustomCraftingServer",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/CustomCraftingServer.luau",
        description="The server checks items then crafts a requested object.",
    )
    design = {"host_actions": {
        "CraftItemAction": {
            "service": "CustomCraftingServer",
            "kind": kind,
            "max_args": max_args,
        }},
        "remotes": {"CraftItemAction": kind},
        "world_objects": [],
        "host_world_actions": {},
    }
    return RobloxProposal(
        game_title="ManualGatewayAudit", description="Real Lua gateway",
        requested_prompt="Let players craft items using a secure server action",
        game_design={"dynamic_design": design},
        modules=[service],
    )


def test_rpc_argument_maximum_is_enforced_in_generated_handlers():
    for kind in ("RemoteEvent", "RemoteFunction"):
        proposal = game_with_action(kind=kind, max_args=2)
        source = render_dynamic_server_bootstrap(proposal)
        expected = (
            'if select("#", ...) > 2 then return nil end'
            if kind == "RemoteFunction" else
            'if select("#", ...) > 2 then return end'
        )
        assert expected in source
        assert "\\n" not in source, "Luau text must use real line breaks"
        assert "service.handleAction(player, services, ...)" in source
    zero = render_dynamic_server_bootstrap(game_with_action(max_args=0))
    assert 'if select("#", ...) > 0 then return nil end' in zero


@pytest.mark.parametrize("limit", [-1, 17, "3", True])
def test_gateway_rejects_invalid_remote_argument_limits(limit):
    with pytest.raises(ValueError, match="argument constraint"):
        render_dynamic_server_bootstrap(game_with_action(max_args=limit))


def test_gateway_checks_nested_data_and_fails_when_declared_instance_is_missing():
    source = render_dynamic_server_bootstrap(game_with_action())
    assert "local function safeWireValue(value, depth, state, seen)" in source
    assert "if depth > 6 then return false end" in source
    assert "if seen[value] then return false end" in source
    assert "state.entries > 256" in source
    assert "state.bytes <= 32768" in source
    assert "safeWireValue(child, depth + 1, state, seen)" in source
    assert 'ServerScriptService:WaitForChild(name, 20)' in source
    assert 'if not scriptModule then error("Missing required server ModuleScript:' in source
    assert 'ReplicatedStorage:WaitForChild("Remotes", 20)' in source
    assert 'remotes:WaitForChild("CraftItemAction", 20)' in source


def test_planet_ground_is_not_underground_or_overlapping_spawn_top():
    module = RobloxModuleSpec(
        module_id="dyn_planet_setup", name="SpaceModeSetupF5E8F01Server",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/SpaceModeSetupF5E8F01Server.luau",
        description="The server initializes a space mode environment with themed world assets and setup.",
    )
    proposal = RobloxProposal(
        game_title="PlanetScene", description="Physical planet setting",
        requested_prompt="Create a space mode environment",
        game_design={"dynamic_design": {
            "host_actions": {}, "host_world_actions": {},
            "world_objects": [],
        }},
        modules=[module],
    )
    source = render_host_world_setup(module, proposal)
    assert source is not None
    assert "ground.Position = Vector3.new(0, -0.5, 0)" in source
    # Baseplate extends Y=-20..0, the scene slab extends Y=-1.5..0.5.
    # SpawnLocation extends Y=0.5..1.5.
    assert "ground.Size = Vector3.new(160, 2, 160)" in source
