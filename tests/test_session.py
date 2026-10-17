"""End-to-end integration tests for CompleteRobloxAISession."""

import os
from pathlib import Path
import pytest
from roblox_mod_ai import CompleteRobloxAISession, RobloxAuthoredPlan


def test_session_plan_revise_build(tmp_path: Path):
    output_dir = tmp_path / "rmm_out"
    session = CompleteRobloxAISession(output_root=output_dir)

    # 1. Plan
    prompt = "Create a sword-fighting arena with coins, shop, and leaderstats"
    reply = session.plan(prompt)

    assert reply.ready_to_build
    assert "Roblox Experience Plan" in reply.message
    assert len(reply.authored_plan.proposal.modules) >= 4
    assert all(a.verified for a in reply.authored_plan.proposal.assets)  # No guessed fallback IDs

    # 2. Checkpoint persistence
    saved_json = output_dir / "proposal.json"
    assert saved_json.is_file()

    # 3. Revise
    revised_reply = session.revise("Add a magic staff and cooldown UI")
    assert revised_reply.authored_plan.revision_count == 1
    assert len(revised_reply.authored_plan.checkpoints) >= 2
    assert any("MagicAbilities" in m.name for m in revised_reply.authored_plan.proposal.modules)

    # 4. Reload plan in fresh session
    new_session = CompleteRobloxAISession(output_root=output_dir)
    loaded_reply = new_session.load_plan(saved_json)
    assert loaded_reply.authored_plan.revision_count == 1

    # 5. Build
    build_result = new_session.build(run_name="test_run", source_only=True)
    # A source-only build is not a verified Roblox game.
    assert not build_result.success
    assert not build_result.rbxlx_path
    assert not build_result.playtest_report.passed
    assert (Path(build_result.project_dir) / "src/server/ShopService.server.luau").is_file()
    assert (Path(build_result.project_dir) / "src/server/CoinCollector.server.luau").is_file()
    assert build_result.analysis_report.passed
    assert build_result.metadata["acceptance"]["passed"]
