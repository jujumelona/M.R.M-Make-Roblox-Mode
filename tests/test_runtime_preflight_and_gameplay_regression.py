"""Regression cases for the October 19 built-but-not-playtested arena artifact.

Do not turn missing owner credentials into an engine pass. Verify concrete
source-generation regressions without needing a Roblox account in CI.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.runtime_verification import OpenCloudRuntimeVerifier


def test_playtest_requires_owner_opt_in_and_never_publishes_without_credentials(monkeypatch):
    for key in (
        "ROBLOX_OPEN_CLOUD_API_KEY", "ROBLOX_TEST_UNIVERSE_ID",
        "ROBLOX_TEST_PLACE_ID", "RMM_ALLOW_TEST_PLACE_PUBLISH",
    ):
        monkeypatch.delenv(key, raising=False)

    class Publisher:
        def publish_place(self, *args, **kwargs):
            raise AssertionError("must not publish to any experience")

    result = OpenCloudRuntimeVerifier(publisher=Publisher()).run(
        SimpleNamespace(game_design={}), Path("/nonexistent/test-place.rbxlx"))
    assert result["passed"] is False
    assert result["executed"] is False
    assert result["status"] == "verification_setup_required"
    assert set(result["missing_requirements"]) == {
        "ROBLOX_OPEN_CLOUD_API_KEY", "ROBLOX_TEST_UNIVERSE_ID",
        "ROBLOX_TEST_PLACE_ID", "RMM_ALLOW_TEST_PLACE_PUBLISH=1",
    }


def test_missing_explicit_publish_opt_in_is_not_a_release_failure(monkeypatch):
    monkeypatch.setenv("ROBLOX_OPEN_CLOUD_API_KEY", "do-not-use")
    monkeypatch.setenv("ROBLOX_TEST_UNIVERSE_ID", "42")
    monkeypatch.setenv("ROBLOX_TEST_PLACE_ID", "99")
    monkeypatch.delenv("RMM_ALLOW_TEST_PLACE_PUBLISH", raising=False)
    result = OpenCloudRuntimeVerifier().run(
        SimpleNamespace(game_design={}), Path("/nonexistent/test-place.rbxlx"))
    assert result["status"] == "verification_setup_required"
    assert result["missing_requirements"] == ["RMM_ALLOW_TEST_PLACE_PUBLISH=1"]


def test_shop_owned_magic_staff_survives_respawn_and_avoids_self_hit():
    generator = LuauCodeGenerator()
    source = generator._generate_shop_service(SimpleNamespace(name="ShopService"), None)
    assert "local function grantMagicStaff(player: Player): boolean" in source
    assert 'if owned:FindFirstChild("magic_staff") then' in source
    assert 'params.FilterDescendantsInstances = {caster}' in source
    assert 'player:WaitForChild("Backpack", 10)' in source
    assert 'if player.Character then task.spawn(restoreEquipment' in source
    assert 'if not grantMagicStaff(player) then' in source


def test_lease_renewal_saves_current_currency_and_inventory():
    generator = LuauCodeGenerator()
    source = generator._generate_safe_datastore_service(
        SimpleNamespace(name="PlayerDataManager", module_id="mod_player_data",
                        kind="data_store"), None)
    assert "stored.coins = coinsSnapshot" in source
    assert 'local ownedInventory = player:FindFirstChild("OwnedItems")' in source
    assert "in ownedInventory:GetChildren()" in source
    assert "stored.inventory = inventorySnapshot" in source
    assert "stored.lastSaved = os.time()" in source
    assert "stored.lockUntil = os.time() + 120" in source
    assert "if not stored or stored.lockToken ~= sessionToken then return nil end" in source


def test_offline_studio_preview_does_not_resolve_cloud_data_store_or_kick_players():
    generator = LuauCodeGenerator()
    source = generator._generate_safe_datastore_service(
        SimpleNamespace(name="PlayerDataManager", module_id="mod_player_data",
                        kind="data_store"), None)
    assert 'local RunService = game:GetService("RunService")' in source
    assert 'if RunService:IsStudio() and game.GameId == 0 then' in source
    assert 'studioEphemeral[userId] = true' in source
    assert 'if studioEphemeral[userId] then continue end' in source
    assert 'return true -- Preview data is intentionally NOT persisted' in source
    assert 'local function activeStore(): GlobalDataStore' in source
    assert 'return activeStore():UpdateAsync' in source
    assert 'warn("RMM Studio local preview: using memory-only profile' in source
    assert 'player:Kick("Profile is unavailable or active on another server' in source


def test_combat_kill_rewards_are_server_owned_and_limited_to_credited_deaths():
    generator = LuauCodeGenerator()
    source = generator._generate_combat_service(SimpleNamespace(name="CombatSystem"), None)
    assert "local KNOCKOUT_REWARD_COINS = 25" in source
    assert "local function trackKnockout(targetHumanoid: Humanoid, attacker: Player)" in source
    assert "targetHumanoid.Died:Connect(function()" in source
    assert "if credit.player.Parent ~= Players then return end" in source
    assert "os.clock() - credit.time > 8" in source
    assert "coins.Value += KNOCKOUT_REWARD_COINS" in source
    assert "trackKnockout(targetHumanoid, player)" in source
    assert source.index("if distance > MAX_REACH") < source.index("trackKnockout(targetHumanoid, player)")


def test_hud_updates_live_health_and_rebinds_after_respawn():
    generator = LuauCodeGenerator()
    src = generator._generate_hud_controller(SimpleNamespace(name="HUDController"), None)
    assert 'health.Name = "HealthDisplay"' in src
    assert "humanoid.HealthChanged:Connect(updateHealth)" in src
    assert 'humanoid:GetPropertyChangedSignal("MaxHealth"):Connect(updateHealth)' in src
    assert 'localPlayer.CharacterAdded:Connect(bindCharacter)' in src
    assert "if healthChanged then healthChanged:Disconnect() end" in src
    assert "if maxHealthChanged then maxHealthChanged:Disconnect() end" in src
