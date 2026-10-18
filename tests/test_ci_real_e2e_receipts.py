"""Test the REAL-MODEL runner's report boundary without pretending CI has MiMo.

A run may fail at the engine stage, but receipt creation itself must not
crash due to stale result attributes, or report unverified Studio as passed.
"""
from types import SimpleNamespace

from tools import run_real_model_e2e as cli


def test_failed_runtime_preserves_actual_stage_errors(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"data": [{"id": "local-mimo"}]}

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url):
            assert url == "http://127.0.0.1:8910/v1/models"
            return Response()

    class Session:
        def __init__(self, output_root): self.output_root = output_root
        router = SimpleNamespace(get_adapter_for_role=lambda role: SimpleNamespace(
            base_url="http://127.0.0.1:8910/v1"))
        def plan(self, prompt):
            assert prompt == "mine and launch"
            proposal = SimpleNamespace(
                modules=[1, 2],
                game_design={"pre_design_research": {
                    "ledger": {"requirements": [{"id": "req-001"}],
                               "unimplemented_facets": []}}})
            return SimpleNamespace(ready_to_build=True,
                                   authored_plan=SimpleNamespace(proposal=proposal))
        def build(self, **kwargs):
            return SimpleNamespace(
                success=False,
                work_receipt=SimpleNamespace(to_dict=lambda: {"stages": [
                    {"stage": "generate_code", "success": True, "errors": [],
                     "details": {}},
                    {"stage": "playtest", "success": False,
                     "errors": ["Studio not accessible"],
                     "details": {"passed": False}},
                ]}),
                metadata={
                    "acceptance": {"passed": True, "checks": []},
                    "tool_results": {"rojo": {"success": True}},
                    "runtime": {"passed": False},
                },
                analysis_report=SimpleNamespace(passed=True),
                project_dir=str(tmp_path),
            )

    monkeypatch.setattr(cli.httpx, "Client", Client)
    monkeypatch.setattr(cli, "CompleteRobloxAISession", Session)
    receipt = cli.run("mine and launch", tmp_path)
    assert receipt["status"] == "build_or_runtime_failed"
    assert receipt["rojo_compiled"] is True
    assert receipt["source_static_passed"] is True
    assert receipt["studio_runtime_passed"] is False
    assert receipt["complete_game_verified"] is False
    assert receipt["production_errors"] == [{
        "stage": "playtest", "errors": ["Studio not accessible"],
        "details": {"passed": False},
    }]
    assert (tmp_path / "real_model_e2e_receipt.json").is_file()


def test_no_reachable_real_model_fails_without_pretending_to_run(monkeypatch, tmp_path):
    class DeadClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url): raise ConnectionError("real local model offline")
    class Session:
        def __init__(self, output_root): pass
        router = SimpleNamespace(get_adapter_for_role=lambda role: SimpleNamespace(
            base_url="http://127.0.0.1:8910/v1"))
        def plan(self, prompt): raise AssertionError("must not create fake model plan")
    monkeypatch.setattr(cli.httpx, "Client", DeadClient)
    monkeypatch.setattr(cli, "CompleteRobloxAISession", Session)
    report = cli.run("mine and launch", tmp_path)
    assert report["status"] == "error"
    assert report["plan_passed"] is False
    assert report["complete_game_verified"] is False
    assert "real local model offline" in str(report["failures"])
