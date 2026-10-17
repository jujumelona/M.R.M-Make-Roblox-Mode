from pathlib import Path
from tools.run_open_cloud_smoke import run
from roblox_mod_ai.api import CompleteRobloxAISession


def test_cloud_smoke_cli_does_not_claim_success_without_credentials(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("RMM_ALLOW_TEST_PLACE_PUBLISH", raising=False)
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 수집 상점 아레나")
    target = tmp_path / "unused.rbxlx"
    target.write_text("<roblox/>", encoding="utf-8")
    result = run(tmp_path / "proposal.json", target)
    assert result["passed"] is False
    assert result["executed"] is False


def test_cloud_workflow_is_manual_and_test_place_only():
    content = (Path(__file__).resolve().parents[1] / ".github/workflows/open-cloud-smoke.yml").read_text()
    assert "workflow_dispatch" in content
    assert "environment: roblox-test" in content
    assert "secrets.ROBLOX_TEST_PLACE_ID" in content
    assert "secrets.ROBLOX_TEST_UNIVERSE_ID" in content
    assert "schedule:" not in content
    assert "pull_request:" not in content
