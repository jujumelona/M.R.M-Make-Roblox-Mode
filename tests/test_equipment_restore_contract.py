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
        SimpleNamespace(name="PlayerDataManager", module_id="mod_player_data",
                        kind="data_store"), _proposal()
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
    assert 'child.Name == "Backpack" and child:IsA("Backpack")' in src
    assert 'child.Name == "StarterGear" and child:IsA("StarterGear")' in src
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


def test_startergear_is_seeded_before_live_staff_delivery_and_deduplicated():
    src = LuauCodeGenerator()._generate_shop_service(
        SimpleNamespace(name="ShopService"), _proposal()
    )
    start = src.index('local function grantMagicStaff(player: Player): boolean')
    end = src.index('-- Remote clients can supply only the weapon identifier.', start)
    staff = src[start:end]
    assert 'player:FindFirstChildOfClass("Backpack")' in staff
    assert 'player:FindFirstChildOfClass("StarterGear")' in staff
    assert 'if not backpack or not starterGear then return false end' in staff
    assert 'local template = starterGear:FindFirstChild(toolName)' in staff
    assert 'newTool.Parent = starterGear' in staff
    assert 'local copy = template:Clone()' in staff
    assert 'copy.Parent = backpack' in staff
    assert staff.index("newTool.Parent = starterGear") < staff.index("copy.Parent = backpack")
    assert 'not backpack:FindFirstChild(toolName)' in staff
    assert 'character and character:FindFirstChild(toolName)' in staff


def test_staff_purchase_refunds_if_persistent_gear_cannot_be_delivered():
    src = LuauCodeGenerator()._generate_shop_service(
        SimpleNamespace(name="ShopService"), _proposal()
    )
    assert 'if not grantMagicStaff(player) then' in src
    assert 'coinsVal.Value += item.price' in src
    assert 'return false, "Backpack unavailable"' in src
    assert 'marker.Name = itemId' in src


def test_staff_input_is_rebound_each_time_roblox_replaces_backpack():
    src = LuauCodeGenerator()._generate_shop_controller(
        SimpleNamespace(name="ShopController"), _proposal()
    )
    assert 'localPlayer.ChildAdded:Connect(onBackpack)' in src
    assert 'if not child:IsA("Backpack") or observedBackpack == child then return end' in src
    assert 'if backpackConnection then backpackConnection:Disconnect() end' in src
    assert 'backpackConnection = child.ChildAdded:Connect(bindTool)' in src
    assert 'for _, tool in child:GetChildren() do bindTool(tool) end' in src
    assert 'localPlayer:FindFirstChildOfClass("Backpack")' in src
    assert 'if characterConnection then characterConnection:Disconnect() end' in src
    assert 'child.Destroying:Connect(function() bound[child] = nil end)' in src
    assert 'local backpack = localPlayer:WaitForChild("Backpack")' not in src
