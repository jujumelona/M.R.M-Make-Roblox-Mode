"""Regression checks for an actual round-combat + coin + shop game.

These inspect generated source and Rojo topology, not only module names.
Real Studio multiplayer and DataStore restoration remain separate requirements.
"""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.project_generator import RobloxProjectGenerator


def _make_proposal(*, combat=True, shop=True, coins=True, round_game=True):
    names = ["NetworkRemotes", "PlayerDataManager"]
    if combat:
        names.extend(("CombatSystem", "CombatController"))
    if shop:
        names.extend(("ShopService", "ShopController"))
    if coins:
        names.append("CoinCollector")
    if round_game and combat:
        names.extend(("ArenaRoundService", "RoundController"))
    modules = [
        SimpleNamespace(name=name, module_id="mod_arena_round" if name == "ArenaRoundService"
                        else "mod_" + name.lower())
        for name in names
    ]
    return SimpleNamespace(
        game_title="ArenaTest",
        modules=modules,
        game_design={
            "features": {"is_combat": combat, "is_shop": shop,
                         "is_coin_collect": coins, "is_leaderboard": True},
            "requested_counts": {},
            "project_mode": "new_experience",
            "storage_backend": "builtin",
            "ui_backend": "builtin",
        },
    )


def _in_ring(point):
    return -20 < point[0] < 20 and -20 < point[2] < 20


def test_tool_input_is_client_only_and_damage_is_server_authoritative():
    proposal = _make_proposal()
    generator = object.__new__(LuauCodeGenerator)
    shop = generator._generate_shop_service(SimpleNamespace(name="ShopService"), proposal)
    client = generator._generate_shop_controller(SimpleNamespace(name="ShopController"), proposal)
    assert 'weaponUse.OnServerEvent:Connect' in shop
    assert 'child.Activated:Connect' in client
    assert 'weaponUse:FireServer("magic_staff")' in client
    assert 'tool.Activated:Connect' not in shop
    for required in (
        'typeof(weaponId) ~= "string"', 'owned:FindFirstChild("magic_staff")',
        'weapon:IsA("Tool")', 'ArenaRoundActive', 'InArenaRound',
        'lastCastByUserId', 'workspace:Raycast', 'target:TakeDamage(20)',
    ):
        assert required in shop
    assert 'PurchaseResult' in client
    assert 'pcall(function()' in client


def test_shop_does_not_insert_unrequested_magic_weapon_into_noncombat_game():
    proposal = _make_proposal(combat=False, round_game=False)
    generator = object.__new__(LuauCodeGenerator)
    shop = generator._generate_shop_service(SimpleNamespace(name="ShopService"), proposal)
    client = generator._generate_shop_controller(SimpleNamespace(name="ShopController"), proposal)
    assert 'magic_staff = {' not in shop
    assert '"Arcane Staff - 150"' not in client


def test_round_lobby_is_outside_arena_and_only_required_remotes_are_installed():
    proposal = _make_proposal()
    generator = object.__new__(RobloxProjectGenerator)
    rojo = generator.generate_rojo_project_json(proposal)
    world = rojo["tree"]["Workspace"]
    assert not _in_ring(world["SpawnLocation"]["$properties"]["CFrame"][:3])
    assert not _in_ring(world["ShopStalls"]["ShopCounter"]["$properties"]["CFrame"][:3])
    for name, coin in world["Coins"].items():
        if name.startswith("Coin"):
            assert not _in_ring(coin["$properties"]["CFrame"][:3])
    remotes = rojo["tree"]["ReplicatedStorage"]["Remotes"]
    assert {name for name in remotes if not name.startswith("$")} == {
        "AttackRequest", "ShopPurchase", "ShopWeaponUse", "RoundStatus"}
    generator = object.__new__(LuauCodeGenerator)
    bridge = generator._generate_shared_network_module(
        SimpleNamespace(name="NetworkRemotes"), proposal)
    for name in ("AttackRequest", "ShopPurchase", "ShopWeaponUse", "RoundStatus"):
        assert name + ' = "' + name + '"' in bridge
    for forbidden in ("StageChanged", "ResetToStage", "ButtonPurchased", "DamageEvent"):
        assert forbidden not in bridge
        assert forbidden not in remotes


def test_noncombat_shop_keeps_spawn_in_default_world_and_no_attack_channels():
    proposal = _make_proposal(combat=False, round_game=False, coins=False)
    rojo = object.__new__(RobloxProjectGenerator).generate_rojo_project_json(proposal)
    world = rojo["tree"]["Workspace"]
    assert world["SpawnLocation"]["$properties"]["CFrame"][:3] == [0, 1, 0]
    remotes = rojo["tree"]["ReplicatedStorage"]["Remotes"]
    assert {name for name in remotes if not name.startswith("$")} == {
        "ShopPurchase", "ShopWeaponUse"}
