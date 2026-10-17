"""Regression: required gameplay graph and real-runtime fail-closed policy."""
from pathlib import Path

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.quality_gates import acceptance_obligations
from roblox_mod_ai.runtime_verification import OpenCloudRuntimeVerifier


def test_coin_shop_combat_obligations(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나")
    result = session.build(source_only=True)
    assert result.analysis_report.passed
    assert result.metadata["acceptance"]["passed"]
    checks = {x["id"]: x["passed"] for x in result.metadata["acceptance"]["checks"]}
    for obligation in ("coin.world", "coin.touch_award", "coin.to.shop", "shop.effect",
                       "shop.ui", "leaderboard.stats", "leaderboard.hud",
                       "combat.server", "combat.client"):
        assert checks[obligation]


def test_missing_coin_award_is_not_approved(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    plan = session.plan("코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나")
    result = session.build(source_only=True)
    proposal = plan.authored_plan.proposal
    module = next(m for m in proposal.modules if m.name == "CoinCollector")
    module.code = "--!strict\\n-- no coin award here"
    report = acceptance_obligations(proposal, Path(result.project_dir))
    assert not report["passed"]
    assert "coin.touch_award" in [x["id"] for x in report["checks"] if not x["passed"]]


def test_runtime_requires_real_external_engine(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("RMM_ALLOW_TEST_PLACE_PUBLISH", raising=False)
    plan = CompleteRobloxAISession(output_root=tmp_path).plan("코인 수집")
    result = OpenCloudRuntimeVerifier().run(plan.authored_plan.proposal, tmp_path / "nonexistent.rbxlx")
    assert not result["passed"]
    assert not result["executed"]
