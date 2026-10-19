"""Regressions for character/profile races in generated persistent equipment.

These are static generator contracts. The emitted Place still needs a real
Roblox Studio respawn/reconnect test before gameplay can be certified.
"""
from types import SimpleNamespace
from roblox_mod_ai.code_generator import LuauCodeGenerator


def _proposal():
    return SimpleNamespace(
        modules=[SimpleNamespace(module_id="mod_arena_round")],
        game_design={"features": {"is_shop": True, "is_combat": True}},
    )


def test_saved_items_are_populated_before_folder_is_published_to_player():
    generator = LuauCodeGenerator()
    src = generator._generate_safe_datastore_service(
        SimpleNamespace(name="PlayerDataManager"), _proposal()
    )
    create = src.index('local owned = Instance.new("Folder")')
    markers = src.index("for _, id in data.inventory", create)
    parent = src.index("owned.Parent = player", markers)
    assert create < markers < parent
    assert "marker.Parent = owned" in src[markers:parent]


def test_paid_equipment_restores_on_profile_arrival_without_ten_second_timeout():
    src = LuauCodeGenerator()._generate_shop_service(
        SimpleNamespace(name="ShopService"), _proposal()
    )
    assert 'player:WaitForChild("OwnedItems", 10)' not in src
    assert 'player.ChildAdded:Connect(function(child)' in src
    assert 'child.Name == "OwnedItems" and child:IsA("Folder")' in src
    assert 'restoreEquipment(player, player.Character)' in src
    assert 'player.CharacterAdded:Connect(onCharacter)' in src
    assert 'player.Character ~= character' in src


def test_shield_restoration_is_idempotent_and_does_not_overheal_on_race():
    src = LuauCodeGenerator()._generate_shop_service(
        SimpleNamespace(name="ShopService"), _proposal()
    )
    guard = 'if character:GetAttribute("RMMGearRestored") then return end'
    set_flag = 'character:SetAttribute("RMMGearRestored", true)'
    shield = 'if owned:FindFirstChild("shield") then\n        humanoid.MaxHealth += 50'
    assert guard in src
    assert set_flag in src
    assert shield in src
    assert src.index(guard) < src.index(set_flag) < src.index(shield)
