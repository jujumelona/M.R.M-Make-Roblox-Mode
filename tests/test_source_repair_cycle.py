"""Behavioral tests of the actual bounded source-review repair coordinator.

No Roblox Studio or remote model needed: patch, rollback, retry and evidence
requirements are tested through real files and deterministic fake reviewers.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.source_repair_cycle import run_source_repair_cycle


SOURCE = "--!strict\nlocal fuel = 0\nreturn fuel\n"
FIXED = "--!strict\nlocal fuel = 10\nreturn fuel\n"
FIRST_BAD = "--!strict\nlocal fuel = -1\nreturn fuel\n"


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _setup(tmp_path, module_id="dyn_spacelift"):
    module = SimpleNamespace(
        name="ShipPhysics", module_id=module_id,
        file_path="src/server/ShipPhysics.luau", code=SOURCE,
    )
    proposal = SimpleNamespace(
        modules=[module], requested_prompt="Build spacecraft fuel movement",
        game_design={"detailed_implementation_plan": {
            "required_functions": [{
                "id": "r-1", "owner_modules": ["ShipPhysics"],
                "original_request": "Ship consumes fuel when moving",
            }],
        }},
    )
    file = tmp_path / module.file_path
    file.parent.mkdir(parents=True)
    file.write_text(SOURCE, encoding="utf-8")
    return proposal, module, file


def _report(path, source, status="issues_found"):
    issue = [{
        "file": path, "line": 2, "quote": "local fuel = 0",
        "issue": "Fuel never changes", "severity": "blocking",
        "repair": "Deduct fuel on valid movement request",
    }] if status == "issues_found" else []
    return {
        "status": status, "fully_covered": True,
        "findings": issue, "source_sha256": {path: _sha(source)},
    }


class Planner:
    def __init__(self):
        self.plans = []
    def complete_json(self, **kwargs):
        self.plans.append(kwargs["prompt"])
        return {
            "file": "src/server/ShipPhysics.luau",
            "root_cause": "Fuel amount is never changed",
            "change_strategy": "Implement correct decrement after validation",
            "invariants": ["Only server changes fuel"],
            "regression_tests": ["zero fuel stops movement"],
        }


def _factory(patches):
    issued = iter(patches)
    class FakeAgent:
        def __init__(self, **kwargs):
            pass
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            assert "root_cause" in diagnostics and "Fuel never changes" in diagnostics
            return next(issued)
    return FakeAgent


def test_iterative_repair_reviews_actual_changed_source_and_passes(tmp_path):
    proposal, module, file = _setup(tmp_path)
    model = Planner()
    calls = []
    def validate():
        calls.append("verify")
        return {"passed": "fuel = 10" in file.read_text(encoding="utf-8")}
    def review():
        calls.append("review")
        assert file.read_text(encoding="utf-8") == FIXED
        return _report(module.file_path, FIXED, "reviewed_no_blockers")
    result = run_source_repair_cycle(
        proposal, tmp_path, model, _report(module.file_path, SOURCE),
        verify=validate, review_again=review, agent_factory=_factory([FIXED]),
    )
    assert result["passed"] and result["status"] == "passed"
    assert [x["status"] for x in result["attempts"]] == ["passed"]
    assert calls == ["verify", "review"]
    assert result["changed_files"] == [module.file_path]
    assert file.read_text(encoding="utf-8") == FIXED
    assert module.code == FIXED
    assert len(model.plans) == 1


def test_failed_first_patch_rolls_back_then_replans_with_failure_diagnostics(tmp_path):
    proposal, module, file = _setup(tmp_path)
    model = Planner()
    checked = []
    def validate():
        current = file.read_text(encoding="utf-8")
        checked.append(current)
        return {"passed": current == FIXED,
                "reason": "fuel negative" if current == FIRST_BAD else ""}
    result = run_source_repair_cycle(
        proposal, tmp_path, model, _report(module.file_path, SOURCE),
        verify=validate,
        review_again=lambda: _report(module.file_path, FIXED, "reviewed_no_blockers"),
        max_rounds=3, agent_factory=_factory([FIRST_BAD, FIXED]),
    )
    assert result["passed"] and [r["status"] for r in result["attempts"]] == [
        "reverted", "passed",
    ]
    assert checked == [FIRST_BAD, FIXED]
    assert file.read_text(encoding="utf-8") == FIXED
    assert "previous_failed_repair_attempts" in model.plans[1]
    assert "fuel negative" in model.plans[1]


def test_repeated_same_bad_patch_stops_without_claiming_success(tmp_path):
    proposal, module, file = _setup(tmp_path)
    result = run_source_repair_cycle(
        proposal, tmp_path, Planner(), _report(module.file_path, SOURCE),
        verify=lambda: {"passed": False}, review_again=lambda: None,
        max_rounds=5, agent_factory=_factory([FIRST_BAD, FIRST_BAD]),
    )
    assert not result["passed"] and result["status"] == "blocked"
    assert len(result["attempts"]) == 2
    assert file.read_text(encoding="utf-8") == SOURCE
    assert module.code == SOURCE


def test_exhausted_attempts_keep_original_code(tmp_path):
    proposal, module, file = _setup(tmp_path)
    patches = [f"--!strict\nlocal fuel = -{i}\n" for i in range(1, 4)]
    result = run_source_repair_cycle(
        proposal, tmp_path, Planner(), _report(module.file_path, SOURCE),
        verify=lambda: {"passed": False, "reason": "actual test failed"},
        review_again=lambda: None, max_rounds=3,
        agent_factory=_factory(patches),
    )
    assert not result["passed"] and result["status"] == "exhausted"
    assert len(result["attempts"]) == 3
    assert all(x["status"] == "reverted" for x in result["attempts"])
    assert file.read_text(encoding="utf-8") == SOURCE


def test_host_generated_security_template_is_not_overwritten_by_ai(tmp_path):
    proposal, module, file = _setup(tmp_path, module_id="mod_network_bridge")
    called = []
    result = run_source_repair_cycle(
        proposal, tmp_path, Planner(), _report(module.file_path, SOURCE),
        verify=lambda: called.append("called") or {"passed": True},
        review_again=lambda: None,
    )
    assert not result["passed"] and result["status"] == "blocked"
    assert "generator-level repair" in result["reason"]
    assert not called
    assert file.read_text(encoding="utf-8") == SOURCE


def test_source_changed_since_review_never_repaired_silently(tmp_path):
    proposal, module, file = _setup(tmp_path)
    file.write_text(FIXED, encoding="utf-8")
    result = run_source_repair_cycle(
        proposal, tmp_path, Planner(), _report(module.file_path, SOURCE),
        verify=lambda: {"passed": True}, review_again=lambda: None,
        max_rounds=1,
    )
    assert not result["passed"]
    assert "Source changed since AI review" in result["reason"]
    assert file.read_text(encoding="utf-8") == FIXED
