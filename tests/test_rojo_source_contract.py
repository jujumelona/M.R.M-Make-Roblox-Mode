"""Regression: one Rojo world definition for ZIP and compiled place."""
from pathlib import Path
from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.project_generator import RobloxProjectGenerator


def test_requested_world_is_present_in_rojo_source(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    plan = session.plan("코인 수집 상점 검투 아레나")
    world = RobloxProjectGenerator(tmp_path).generate_rojo_project_json(plan.authored_plan.proposal)["tree"]["Workspace"]
    assert len([k for k in world["Coins"] if k.startswith("Coin")]) >= 5
    assert "ShopStalls" in world
    assert "CombatArena" in world
    assert "SpawnLocation" in world


def test_other_genre_worlds_are_not_xml_only(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    for prompt, name in [
        ("용암 점프맵", "Checkpoints"),
        ("드롭퍼 컨베이어 타이쿤", "TycoonPlots"),
        ("채광 시뮬레이터", "SellZones"),
    ]:
        plan = session.plan(prompt)
        world = session.orchestrator.project_generator.generate_rojo_project_json(plan.authored_plan.proposal)["tree"]["Workspace"]
        assert name in world
