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
    assert "stored.inventory = inventorySnapshot" in source
    assert "stored.lastSaved = os.time()" in source
    assert "stored.lockUntil = os.time() + 120" in source
    assert "if not stored or stored.lockToken ~= sessionToken then return nil end" in source
