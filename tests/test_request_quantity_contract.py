from pathlib import Path
from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.project_generator import RobloxProjectGenerator

def test_50_stage_request_generates_50_not_five(tmp_path,monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH","0")
    session=CompleteRobloxAISession(output_root=tmp_path)
    plan=session.plan("50단계 용암 점프맵")
    assert plan.authored_plan.proposal.game_design["requested_counts"]["stages"]==50
    proposal=plan.authored_plan.proposal
    checkpoints=RobloxProjectGenerator(tmp_path).generate_rojo_project_json(proposal)["tree"]["Workspace"]["Checkpoints"]
    assert len([k for k in checkpoints if k.startswith("Stage")])==50
    result=session.build(source_only=True)
    assert result.metadata["acceptance"]["passed"],result.metadata["acceptance"]

def test_explicit_coins_are_not_silently_reduced(tmp_path,monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH","0")
    session=CompleteRobloxAISession(output_root=tmp_path)
    plan=session.plan("코인 30개를 수집하는 상점")
    proposal=plan.authored_plan.proposal
    world=RobloxProjectGenerator(tmp_path).generate_rojo_project_json(proposal)["tree"]["Workspace"]
    assert len([k for k in world["Coins"] if k.startswith("Coin")])==30
    result=session.build(source_only=True)
    assert result.metadata["acceptance"]["passed"]

def test_large_world_request_must_fail_clearly_not_truncate(tmp_path,monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH","0")
    session=CompleteRobloxAISession(output_root=tmp_path)
    reply=session.plan("500단계 용암 점프맵")
    assert not reply.ready_to_build
    assert "requested_count_exceeds_safe_build_limit" in reply.authored_plan.proposal.game_design["pre_design_research"]["ledger"]["unimplemented_facets"]
    result=session.build(source_only=True)
    assert not result.metadata["acceptance"]["passed"]
