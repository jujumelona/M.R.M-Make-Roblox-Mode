"""Adversarial proof tests for Part-backed combat health, independent of genre."""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.attribute_health_attestation import attest_attribute_health
from roblox_mod_ai.requirement_effect_review import review_requirement_effects


SERVER = """--!strict
local Players = game:GetService("Players")
local Service = {}
function Service.start(services)
    local marker = workspace:FindFirstChild("TargetDrone", true)
    if marker:GetAttribute("Vitality") == nil then
        marker:SetAttribute("Vitality", 100)
    end
    task.spawn(function()
        while marker.Parent do
            local remaining = marker:GetAttribute("Vitality")
            if remaining == 0 then
                marker:SetAttribute("Vitality", 100)
            end
            task.wait(10)
        end
    end)
end
function Service.handleAction(player, services, ...)
    if player.Parent ~= Players then
        return { success = false, reason = "not_player" }
    end
    local target = workspace:FindFirstChild("TargetDrone", true)
    local root = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
    if not root or not target or not target:IsA("BasePart")
        or (root.Position - target.Position).Magnitude > 40 then
        return { success = false, reason = "out_of_range" }
    end
    local hp = target:GetAttribute("Vitality")
    if type(hp) ~= "number" or hp <= 0 then
        return { success = false, reason = "dead" }
    end
    local rank = 2
    local damage = math.min(20, 5 + rank)
    local remaining = math.max(0, hp - damage)
    target:SetAttribute("Vitality", remaining)
    if remaining == 0 then
        target.Material = Enum.Material.Neon
    end
    return { success = true, remainingHealth = remaining }
end
return Service
"""


ROLE = "Server validates an attack and damages a real world enemy's health."


def test_server_owned_part_health_is_real_damage_without_humanoid():
    proof = attest_attribute_health(SERVER, ROLE)
    assert proof is not None
    assert proof["method"] == "server_owned_attribute_health_transition"
    assert proof["attribute"] == "Vitality"
    assert proof["quote"] == 'target:SetAttribute("Vitality", remaining)'


@pytest.mark.parametrize("broken", [
    SERVER.replace('target:SetAttribute("Vitality", remaining)',
                   'target:SetAttribute("Decoration", remaining)'),
    SERVER.replace('target:GetAttribute("Vitality")',
                   'target:GetAttribute("Shield")'),
    SERVER.replace('target:IsA("BasePart")', 'target:IsA("Folder")'),
    SERVER.replace('workspace:FindFirstChild("TargetDrone", true)\n    local root',
                   'workspace:FindFirstChild("OtherDrone", true)\n    local root'),
    SERVER.replace('local damage = math.min(20, 5 + rank)',
                   'local damage = args.damage'),
    SERVER.replace('local damage = math.min(20, 5 + rank)',
                   'local damage = 0'),
    SERVER.replace('local damage = math.min(20, 5 + rank)',
                   'local damage = math.min(20, 0 + rank)'),
    SERVER.replace('if not root or not target or not target:IsA("BasePart")',
                   'if not target or not target:IsA("BasePart")'),
    SERVER.replace('(root.Position - target.Position).Magnitude > 40',
                   '(root.Position - target.Position).Magnitude == 0'),
    SERVER.replace('if type(hp) ~= "number" or hp <= 0 then',
                   'if type(hp) ~= "number" then'),
    SERVER.replace('target:SetAttribute("Vitality", remaining)',
                   'task.wait(1)\n    target:SetAttribute("Vitality", remaining)'),
    SERVER.replace('local remaining = math.max(0, hp - damage)',
                   'local remaining = math.max(0, hp + damage)'),
])
def test_health_attestation_fails_closed_on_missing_provenance(broken):
    assert attest_attribute_health(broken, ROLE) is None


def test_independent_requirement_review_does_not_force_humanoid(tmp_path):
    path = "src/server/DroneCombat.luau"
    file = tmp_path / path
    file.parent.mkdir(parents=True)
    file.write_text(SERVER, encoding="utf-8")
    module = SimpleNamespace(
        file_path=path, name="DroneCombat",
        description=ROLE,
    )
    proposal = SimpleNamespace(
        modules=[module],
        game_design={"detailed_implementation_plan": {"required_functions": [{
            "id": "req-drone",
            "original_request": "Make a game where players fight enemy drones",
            "expected_outcome": "The player's attacks reduce drone health",
            "owner_files": [path],
        }]}},
    )

    class ModelMustNotBeAuthority:
        def complete_json(self, **kwargs):
            raise AssertionError("Deterministically proven damage was sent to model")

    report = review_requirement_effects(
        proposal, tmp_path, ModelMustNotBeAuthority(),
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert len(report["cross_module_contracts"]) == 1
    assert report["cross_module_contracts"][0]["method"] == (
        "server_owned_attribute_health_transition"
    )
