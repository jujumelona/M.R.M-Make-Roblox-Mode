"""Plan81: already accepted code must not assume a Part is a Model/IntValue.

This is NOT a Roblox Studio execution test. The world manifest is explicit,
so these static failures are provable even with a 9B model or offline Colab.
"""
from types import SimpleNamespace as NS
from roblox_mod_ai.world_instance_type_audit import world_instance_type_errors


def fixture():
    return NS(game_design={"dynamic_design": {"world_objects": [
        {"name": "ActualPart", "class": "Part"},
        {"name": "ActualCoinValue", "class": "IntValue"},
        {"name": "ActualVehicle", "class": "Model"},
    ]}})


def test_model_instead_of_part_is_rejected():
    code = (
        'local owned = workspace:FindFirstChild("ActualPart")\n'
        'if not owned or not owned:IsA("Model") then return false end\n'
        'owned:SetAttribute("Upgraded", true)\n'
    )
    assert any("WORLD_INSTANCE_TYPE_IMPOSSIBLE" in issue
               for issue in world_instance_type_errors(code, fixture()))


def test_part_instead_of_intvalue_is_rejected():
    code = (
        'local currency = workspace:FindFirstChild("ActualPart")\n'
        'if not currency:IsA("IntValue") then return false end\n'
        'currency.Value -= 1\n'
    )
    assert any("not as IntValue" in issue
               for issue in world_instance_type_errors(code, fixture()))


def test_exact_manifest_types_are_accepted():
    code = (
        'local part = workspace.ActualPart\n'
        'local vehicle = workspace:FindFirstChild("ActualVehicle")\n'
        'local credits = workspace:WaitForChild("ActualCoinValue")\n'
        'if not part:IsA("BasePart") then return false end\n'
        'if not vehicle:IsA("Model") then return false end\n'
        'if not credits:IsA("IntValue") then return false end\n'
    )
    assert world_instance_type_errors(code, fixture()) == []


def test_invented_engine_method_rejected_even_without_known_class():
    code = 'local a = workspace:FindFirstChild("Dynamic")\na:SetPrimaryPartC(false)'
    assert any("ROBLOX_ENGINE_METHOD_UNDEFINED" in issue
               for issue in world_instance_type_errors(code, fixture()))


def test_real_model_move_is_not_confused_with_invented_method():
    code = ('local a = workspace:FindFirstChild("ActualVehicle")\n'
            'a:PivotTo(CFrame.new(0, 100, 0))\n')
    assert world_instance_type_errors(code, fixture()) == []


def test_comment_and_string_are_not_executable_type_checks():
    code = (
        '-- local x = workspace:FindFirstChild("ActualPart")\n'
        '-- x:SetPrimaryPartC(false)\n'
        'local message = "a:SetPrimaryPartC(false)"'
    )
    assert world_instance_type_errors(code, fixture()) == []
