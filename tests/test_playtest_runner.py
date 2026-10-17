"""Tests for RobloxPlaytestRunner."""

from roblox_mod_ai.playtest_runner import RobloxPlaytestRunner
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


def test_playtest_runner_execution():
    runner = RobloxPlaytestRunner()
    proposal = RobloxProposal(
        requested_prompt="Combat Arena",
        game_title="CombatArena",
        description="Arena battle",
        game_design={},
        modules=[
            RobloxModuleSpec(
                module_id="mod_data",
                name="PlayerDataManager",
                kind=ModuleKind.DATA_STORE,
                file_path="src/server/PlayerDataManager.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                code="--!strict\nlocal pcall_result = pcall(function() end)\n",
            ),
            RobloxModuleSpec(
                module_id="mod_combat",
                name="CombatSystem",
                kind=ModuleKind.SERVER_SCRIPT,
                file_path="src/server/CombatSystem.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                code="--!strict\nlocal Remotes = game:GetService('ReplicatedStorage')\n",
            ),
        ],
    )

    report = runner.run_headless_playtest(proposal)
    assert report.passed
    assert report.passed_count == report.total_tests
    assert report.duration_ms > 0
