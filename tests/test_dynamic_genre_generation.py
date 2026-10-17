"""Tests for dynamic genre decomposition and topological work graph."""

from pathlib import Path
from roblox_mod_ai import CompleteRobloxAISession
from roblox_mod_ai.planner import RobloxGameDesignPlanner


def test_genre_detection_and_dynamic_module_assembly():
    planner = RobloxGameDesignPlanner()

    # 1. Obby / Parkour request
    obby_plan = planner.plan("50단계 용암 점프맵 오비 만들어줘")
    module_names = [m.name for m in obby_plan.proposal.modules]
    assert "ObbyService" in module_names
    assert "ObbyController" in module_names
    assert "CombatSystem" not in module_names

    # 2. Shop & Economy request
    shop_plan = planner.plan("아이템 구매 가능한 코인 상점 시스템")
    module_names = [m.name for m in shop_plan.proposal.modules]
    assert "ShopService" in module_names
    assert "ShopController" in module_names
    assert "CombatSystem" not in module_names

    # 3. Tycoon request
    tycoon_plan = planner.plan("드롭퍼와 컨베이어가 있는 공장 타이쿤 게임")
    module_names = [m.name for m in tycoon_plan.proposal.modules]
    assert "TycoonService" in module_names
    assert "TycoonController" in module_names


def test_work_graph_receipt_and_build_mode(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    plan = session.plan("코인 상점과 검투가 합쳐진 아레나 게임")

    result = session.build(plan, run_name="test_work_graph", source_only=True)
    assert result.success is False
    assert result.work_receipt is not None
    assert result.work_receipt.overall_success is False

    # Verify stage progression in receipt
    stage_names = [s.stage.value for s in result.work_receipt.stages]
    assert "resolve_dependencies" in stage_names
    assert "generate_code" in stage_names
    assert "lint_and_self_correct" in stage_names
    assert "playtest" not in stage_names  # no engine was launched
    assert "package" in stage_names

    # Verify build mode truthfulness
    assert result.build_mode == "source_only"

    # Verify work_receipt.json was persisted
    receipt_file = Path(result.project_dir) / "work_receipt.json"
    assert receipt_file.is_file()
