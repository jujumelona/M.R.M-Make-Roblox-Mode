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
    assert "PlayerDataStore:UpdateAsync(key" in code
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
