"""A vehicle launch must move the physically built root, never a dummy Part.

Explicit systems contracts are checked before model code, without adding
special-case words or IDs from the reported space-game prompt.
"""
from types import SimpleNamespace as Obj

from roblox_mod_ai.vehicle_identity_contract import vehicle_identity_errors
from roblox_mod_ai.world_motion_contract import vehicle_motion_code_errors


def scenario(*, launch_actor="VehicleRoot", builder_actor="VehicleRoot",
             include_builder=True):
    builder = Obj(
        name="ConstructorServer", module_id="dyn_build",
        description="Server builds a vehicle by assembling parts on a root",
        file_path="src/server/ConstructorServer.luau",
    )
    launcher = Obj(
        name="DepartureServer", module_id="dyn_depart",
        description="Server moves assembled vehicle with passengers aboard",
        file_path="src/server/DepartureServer.luau",
    )
    modules = [builder, launcher] if include_builder else [launcher]
    world_objects = [
        {"name": name, "class": "Model"}
        for name in sorted({launch_actor, builder_actor})
    ]
    return Obj(modules=modules, game_design={"dynamic_design": {
        "host_world_motion": {
            launcher.name: {"kind": "vehicle_world_transition"}
        },
        "module_world_objects": {
            builder.module_id: [builder_actor],
            launcher.module_id: [launch_actor],
        },
        "world_objects": world_objects,
    }})


def test_same_physical_actor_is_allowed():
    assert vehicle_identity_errors(scenario()) == []


def test_different_dummy_vehicle_is_rejected_before_luau():
    problems = vehicle_identity_errors(
        scenario(launch_actor="PlaceholderCraft", builder_actor="BuiltRoot")
    )
    assert len(problems) == 1
    assert "VEHICLE_ACTOR_NOT_BUILT_OBJECT" in problems[0]
    assert "PlaceholderCraft" in problems[0]
    assert "BuiltRoot" not in problems[0] or "ConstructorServer" in problems[0]


def test_standalone_vehicle_does_not_require_build_system():
    p = scenario(include_builder=False, launch_actor="Shuttle")
    assert vehicle_identity_errors(p) == []


def test_missing_world_actor_is_an_implementation_blocker():
    p = scenario()
    p.game_design["dynamic_design"]["module_world_objects"]["dyn_depart"] = [
        "InventedWorldObject"
    ]
    assert any("VEHICLE_ACTOR_WORLD_UNRESOLVED" in x
               for x in vehicle_identity_errors(p))


def test_real_pivotto_with_generic_craft_identifier_is_valid_motion_evidence():
    source = (
        'local craft = workspace:FindFirstChild("BuiltRoot")\n'
        'if not craft then return false end\n'
        'craft:PivotTo(CFrame.new(0, 400, 0))\n'
    )
    assert vehicle_motion_code_errors(source) == []


def test_player_status_change_is_not_vehicle_motion():
    assert any("VEHICLE_WORLD_MOVEMENT_CODE_MISSING" in x
               for x in vehicle_motion_code_errors(
                   'player:SetAttribute("InSpace", true)'
               ))
