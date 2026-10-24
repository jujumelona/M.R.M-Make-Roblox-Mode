"""World-object ABI is based on materialized names, not genre guesses.

Plan 79 generated workspace:FindFirstChild("Spaceship"), whereas the
materialized object was Spaceship213E1D31. Real game actions must not be
accepted just because the script parses.
"""
from types import SimpleNamespace as NS
from roblox_mod_ai.world_object_abi import (
    world_lookup_guidance, world_lookup_errors, world_names,
)


def setup():
    mod = NS(name="GenericUpgradeServer", module_id="dyn_upgrade",
             description="Upgrade an owned world object")
    return NS(
        modules=[mod],
        game_design={"dynamic_design": {
            "world_objects": [
                {"name": "WorldMachineOne", "class": "Part"},
                {"name": "WorldMachineTwo", "class": "Part"},
            ],
            "module_world_objects": {
                mod.module_id: ["WorldMachineOne"]
            },
        }},
    ), mod


def test_prompt_has_exact_real_world_objects_not_inferred_names():
    proposal, module = setup()
    all_names, authorized = world_names(proposal, module)
    assert all_names == ["WorldMachineOne", "WorldMachineTwo"]
    assert authorized == ["WorldMachineOne"]
    guidance = world_lookup_guidance(proposal, module)
    assert '"WorldMachineOne"' in guidance
    assert '"WorldMachineTwo"' in guidance


def test_invented_world_name_from_model_is_rejected():
    proposal, _ = setup()
    code = (
        'local thing = workspace:FindFirstChild("Machine")\n'
        'if not thing then return false end\n'
        'thing:SetAttribute("Speed", 10)'
    )
    assert any("WORLD_OBJECT_NAME_UNDECLARED" in issue
               for issue in world_lookup_errors(code, proposal))


def test_real_world_name_is_accepted():
    proposal, _ = setup()
    code = (
        'local thing = workspace:FindFirstChild("WorldMachineOne")\n'
        'if not thing then return false end\n'
        'thing:SetAttribute("Speed", 10)'
    )
    assert world_lookup_errors(code, proposal) == []


def test_dynamic_object_named_in_same_script_is_allowed():
    proposal, _ = setup()
    code = (
        'local generated = Instance.new("Part")\n'
        'generated.Name = "CreatedAtRuntime"\n'
        'generated.Parent = workspace\n'
        'local found = workspace:FindFirstChild("CreatedAtRuntime")\n'
    )
    assert world_lookup_errors(code, proposal) == []


def test_strings_comments_and_non_workspace_objects_not_flagged():
    proposal, _ = setup()
    code = (
        '-- workspace:FindFirstChild("CommentName")\n'
        'local x = \'workspace:FindFirstChild("StringName")\'\n'
        'local gui = player:FindFirstChild("PlayerGui")\n'
    )
    assert world_lookup_errors(code, proposal) == []


def test_generation_and_replay_gates_both_import_same_world_checker():
    from roblox_mod_ai import host_service_codegen, module_generation_gate
    assert callable(host_service_codegen.world_lookup_errors)
    assert callable(module_generation_gate.world_lookup_errors)
