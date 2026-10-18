"""Regression: a failed MRM run must return actionable artifacts, not die silently."""
from __future__ import annotations

import json
from pathlib import Path
import zipfile

from roblox_mod_ai.agent_trajectory import AgentTrajectory
from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.orchestrator import RobloxProductionOrchestrator
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, RobloxService, ModuleKind


def make_module(module_id, name, path, code=""):
    return RobloxModuleSpec(
        module_id=module_id, name=name, kind=ModuleKind.SERVER_SCRIPT,
        file_path=path, roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        code=code,
    )


def test_partial_source_and_trace_survive_generation_failure(tmp_path, monkeypatch):
    orchestrator = RobloxProductionOrchestrator(tmp_path)
    proposal = RobloxProposal(
        requested_prompt="Generate a custom game with trade and mining",
        game_title="SpaceTrial", description="test", game_design={},
        modules=[
            make_module("dyn_trade", "TradeService", "src/server/TradeService.server.luau",
                        "--!strict\nprint('Trade service exists')\n"),
            make_module("dyn_mining", "MiningService", "src/server/MiningService.server.luau"),
        ],
    )

    def fail_second(module, plan):
        assert module.name == "MiningService"
        raise ValueError("Model tool reported a syntax error on MiningService")
    monkeypatch.setattr(orchestrator.code_generator, "generate_with_self_correction",
                        fail_second)
    result = orchestrator.execute(proposal, run_name="failed")
    assert not result.success
    root = Path(result.project_dir)
    assert (root / "src/server/TradeService.server.luau").is_file()
    assert not (root / "src/server/MiningService.server.luau").exists()
    partial = json.loads((root / "proposal_partial.json").read_text(encoding="utf-8"))
    assert partial["modules"][0]["code"].startswith("--!strict")
    trace = json.loads((root / "agent_trajectory.json").read_text(encoding="utf-8"))
    assert any(x["phase"] == "generation" and not x["passed"]
               and "MiningService" in str(x["observation"]) for x in trace["steps"])
    failure_zip = Path(result.metadata["failure_logs_zip"])
    assert failure_zip.is_file()
    with zipfile.ZipFile(failure_zip) as bundle:
        names = bundle.namelist()
        assert "agent_failure_report.json" in names
        assert "agent_trajectory.json" in names
        assert "src/server/TradeService.server.luau" in names
        assert "proposal_partial.json" in names
        report = json.loads(bundle.read("agent_failure_report.json"))
        assert not report["success"]
        assert "MiningService" in report["error"]


def test_incomplete_plan_exports_diagnostics_and_original_request(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "0")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "0")
    session = CompleteRobloxAISession(output_root=tmp_path)
    prompt = "광물 채굴하고 거래해서 우주선을 만들어 다른 행성으로 간다"
    reply = session.plan(prompt)
    assert not reply.ready_to_build
    bundle = tmp_path / "plan_failure_logs.zip"
    assert bundle.is_file()
    with zipfile.ZipFile(bundle) as reader:
        report = json.loads(reader.read("plan_failure_report.json"))
        assert report["requested_prompt"] == prompt
        assert report["unimplemented_facets"]
        assert "proposal.json" in reader.namelist()


def test_trajectory_keeps_all_observations_and_failure_zip(tmp_path):
    log = AgentTrajectory(tmp_path / "run")
    log.record("lint", "selene", {"stderr": "line 3: unexpected token"},
               passed=False, attempt=1)
    log.record("repair", "rewrite src/server/Service.server.luau", {"changed": True},
               passed=True, attempt=1)
    failure = log.failure_bundle("real verifier unavailable", tool_results={
        "selene": {"executed": True, "success": False, "stderr": "line 3"}
    })
    assert failure.exists()
    saved = json.loads(log.path.read_text(encoding="utf-8"))
    assert [step["passed"] for step in saved["steps"]] == [False, True]
