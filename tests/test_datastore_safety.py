"""Tests verifying DataStore resilience against data loss, backoff, and BindToClose waiting."""

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, RobloxService


def test_datastore_code_safety_patterns():
    generator = LuauCodeGenerator()
    proposal = RobloxProposal(
        requested_prompt="Save player data",
        game_title="SaveTest",
        description="Testing DataStore generator",
        game_design={},
        modules=[],
    )

    module = RobloxModuleSpec(
        module_id="mod_player_data",
        name="PlayerDataManager",
        kind="data_store",
        file_path="src/server/PlayerDataManager.server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )

    code = generator.generate_module_code(module, proposal)

    # 1. Must distinguish read failure from nil data (no zero overwrites!)
    assert "player:Kick(" in code
    assert "if not success then" in code
    assert "if not success or lockedByOther or rawData == nil then" in code
    # Lazy resolution avoids cloud DataStore calls in unpublished Studio previews.
    assert "activeStore():UpdateAsync(key" in code
    assert 'if RunService:IsStudio() and game.GameId == 0 then' in code
    assert "if studioEphemeral[userId] then" in code
    assert "current.lockToken ~= sessionLocks[userId]" in code
    assert "stored.lockUntil = os.time() + 120" in code
    assert 'owned.Name = "OwnedItems"' in code

    # 2. Must use exponential backoff with jitter
    assert "retryWithBackoff" in code
    assert "backoffTime" in code
    assert "2 ^ attempt" in code

    # 3. Must use session token locking
    assert "GenerateGUID" in code
    assert "lockToken" in code

    # 4. BindToClose must wait for completion
    assert "game:BindToClose" in code
    assert "deadline" in code
    assert "remaining" in code


def test_departed_player_cannot_keep_newly_acquired_profile_lease():
    """A DataStore UpdateAsync can finish AFTER PlayerRemoving was observed.

    This would otherwise leave an unowned lock until its 120s expiry.
    """
    module = RobloxModuleSpec(
        module_id="mod_player_data", name="PlayerDataManager",
        kind="data_store", file_path="src/server/PlayerDataManager.server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )
    src = LuauCodeGenerator().generate_module_code(module, RobloxProposal(
        requested_prompt="Coins", game_title="RaceTest", description="", game_design={}, modules=[module]))
    loaded = src.index("if not success or lockedByOther or rawData == nil then")
    disconnected = src.index("if player.Parent ~= Players then", loaded)
    recorded = src.index("sessionData[userId] = data", loaded)
    assert loaded < disconnected < recorded
    release = src[disconnected:recorded]
    assert 'not studioEphemeral[userId]' in release
    assert 'current.lockToken ~= sessionToken' in release
    assert 'current.lockToken = nil' in release
    assert 'current.lockUntil = nil' in release
    assert 'retryWithBackoff(function()' in release
    assert 'return -- Do not create phantom leaderstats' in release


def test_callable_profile_retains_its_existing_queued_disconnect_coordinator():
    """The dynamic host service has its own race handling, not duplicated."""
    module = RobloxModuleSpec(
        module_id="mod_player_data", name="PlayerDataManager",
        kind="server_module", file_path="src/server/PlayerDataManager.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )
    src = LuauCodeGenerator()._generate_safe_datastore_service(module, None)
    assert "if player.Parent ~= Players then" in src
    assert "restartQueued(userId)" in src
    assert "savePlayerData(player, true)" in src
    assert "Do not create phantom leaderstats for departed players" not in src
