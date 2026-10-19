"""Cross-file acceptance of authored goals, transitions, and actual host sources."""
from __future__ import annotations

import json
from pathlib import Path

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.quality_gates import acceptance_obligations
from roblox_mod_ai.project_generator import RobloxProjectGenerator


def _session(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH", "0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "0")
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "0")
    return CompleteRobloxAISession(output_root=tmp_path, fast_mode=True)


def test_real_arena_plan_produces_connected_round_result_and_replay(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch)
    reply = session.plan("코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나 게임")
    assert reply.ready_to_build
    proposal = reply.authored_plan.proposal
    assert proposal.game_design["gameplay_contract"]["mode"] == "round"
    assert "ArenaRoundService" in {m.name for m in proposal.modules}
    result = session.build(source_only=True)
    assert result.success, [x["id"] for x in result.metadata["acceptance"]["checks"]
                            if not x["passed"]]
    root = Path(result.project_dir)
    cfg = json.loads((root / "default.project.json").read_text(encoding="utf-8"))
    assert cfg["tree"]["ReplicatedStorage"]["Remotes"]["RoundStatus"]["$className"] == "RemoteEvent"
    onboarding = (root / "src/client/GameObjectiveController.client.luau").read_text(encoding="utf-8")
    assert 'goal.Name = "GameObjective"' in onboarding
    assert 'hint.Name = "GameActionHint"' in onboarding
    assert "검투 아레나" in onboarding
    assert "toggle.Activated:Connect" in onboarding
    round_service = (root / "src/server/ArenaRoundService.server.luau").read_text(encoding="utf-8")
    combat = (root / "src/server/CombatSystem.server.luau").read_text(encoding="utf-8")
    assert "winner" in round_service
    assert "ArenaRoundActive" in round_service and "InArenaRound" in round_service
    assert "ArenaRoundActive" in combat and "InArenaRound" in combat
    assert 'game:GetAttribute("ArenaRoundActive")' in combat
    checks = {x["id"]: x["passed"] for x in result.metadata["acceptance"]["checks"]}
    assert checks["lifecycle.source.onboarding"]
    assert all(ok for key, ok in checks.items() if key.startswith("lifecycle."))
    recipe = json.loads((root / "gameplay_playtest_scenarios.json").read_text(encoding="utf-8"))
    assert recipe["verification"] == "not_run"
    assert {"round.solo", "round.win", "round.disconnect", "round.draw", "round.replay"} <= {
        entry["id"] for entry in recipe["scenarios"]}
    assert all(not item["executed"] for item in recipe["scenarios"])

    # Tampering with the built code after a valid plan must fail acceptance.
    round_path = root / "src/server/ArenaRoundService.server.luau"
    round_path.write_text("--!strict\nprint('no round')\n", encoding="utf-8")
    broken = acceptance_obligations(proposal, root)
    assert not broken["passed"]
    assert "lifecycle.source.round" in {x["id"] for x in broken["checks"] if not x["passed"]}


def test_obby_has_last_checkpoint_goal_and_completion_feedback(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch)
    reply = session.plan("5단계 용암 점프맵")
    assert reply.ready_to_build
    assert reply.authored_plan.proposal.game_design["gameplay_contract"]["mode"] == "stage"
    result = session.build(source_only=True)
    assert result.success, result.metadata["acceptance"]
    root = Path(result.project_dir)
    src = (root / "src/server/ObbyService.server.luau").read_text(encoding="utf-8")
    assert "local lastStage = 5" in src
    assert 'player:SetAttribute("ObbyComplete", true)' in src
    ui = (root / "src/client/ObbyController.client.luau").read_text(encoding="utf-8")
    assert 'GetAttributeChangedSignal("ObbyComplete")' in ui
    scenario = json.loads((root / "gameplay_playtest_scenarios.json").read_text(encoding="utf-8"))
    assert any(x["id"] == "stage.finish" for x in scenario["scenarios"])


def test_owned_addon_uses_host_game_goal_not_forced_end(tmp_path, monkeypatch):
    session = _session(tmp_path, monkeypatch)
    reply = session.plan("검투 아레나 전투 시스템 추가", project_mode="existing_experience_addon")
    assert reply.authored_plan.proposal.game_design["gameplay_contract"]["mode"] == "addon"
    assert "ArenaRoundService" not in {m.name for m in reply.authored_plan.proposal.modules}
