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
    assert not result["passed"] and result["status"] == "blocked"
    # Do not burn a third model attempt on the same unchanged failure.
    assert len(result["attempts"]) == 2
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


def test_grounded_defect_does_not_require_second_llm_root_cause_plan(tmp_path):
    proposal, module, file = _setup(tmp_path)
    review = _report(module.file_path, SOURCE)
    review["findings"][0]["evidence"] = "requirement_effect_review_source_quote"

    class PatchOnlyRouter:
        def __init__(self):
            self.calls = []
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.calls.append(prompt)
            assert prompt.startswith("Patch exactly ONE"), (
                "Small model must receive a direct bounded patch, not a "
                "redundant English root-cause-planning task"
            )
            return {"before": "local fuel = 0", "after": "local fuel = 10"}

    import roblox_mod_ai.source_repair_cycle as cycle
    original_host_detector = cycle.host_source_must_regenerate
    cycle.host_source_must_regenerate = lambda *args: True
    try:
        router = PatchOnlyRouter()
        result = run_source_repair_cycle(
            proposal, tmp_path, router, review,
            verify=lambda: {"passed": file.read_text(encoding="utf-8") == FIXED},
            review_again=lambda: _report(module.file_path, FIXED, "reviewed_no_blockers"),
            max_rounds=1, allow_host_gameplay_repairs=True,
        )
        assert result["passed"] and file.read_text(encoding="utf-8") == FIXED
        assert len(router.calls) == 1
        assert result["attempts"][0]["plans"][0]["plan_origin"] == (
            "grounded_requirement_effect_findings"
        )
    finally:
        cycle.host_source_must_regenerate = original_host_detector


def test_many_grounded_defects_are_repaired_independently(tmp_path, monkeypatch):
    proposal, first, first_file = _setup(tmp_path)
    second = SimpleNamespace(
        name="ShipCargo", module_id="dyn_ship_cargo",
        file_path="src/server/ShipCargo.luau", code=SOURCE,
    )
    second_file = tmp_path / second.file_path
    second_file.write_text(SOURCE, encoding="utf-8")
    proposal.modules.append(second)
    import roblox_mod_ai.source_repair_cycle as cycle
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *args: True)

    class Router:
        def __init__(self):
            self.calls = []
        def complete_json(self, **kwargs):
            assert kwargs["prompt"].startswith("Patch exactly ONE")
            self.calls.append(kwargs["prompt"])
            return {"before": "local fuel = 0", "after": "local fuel = 10"}

    def review():
        findings = []
        hashes = {}
        for module in proposal.modules:
            value = (tmp_path / module.file_path).read_text(encoding="utf-8")
            hashes[module.file_path] = _sha(value)
            if value == SOURCE:
                findings.append({
                    "file": module.file_path, "line": 2,
                    "quote": "local fuel = 0", "severity": "blocking",
                    "issue": "Fuel is unchanged in actual source",
                    "repair": "Replace the fuel constant after valid action",
                    "evidence": "requirement_effect_review_source_quote",
                })
        return {
            "status": "issues_found" if findings else "reviewed_no_blockers",
            "fully_covered": True,
            "source_sha256": hashes, "findings": findings,
        }

    router = Router()
    result = run_source_repair_cycle(
        proposal, tmp_path, router, review(),
        verify=lambda: {"passed": True}, review_again=review,
        max_rounds=1, allow_host_gameplay_repairs=True,
    )
    assert result["passed"]
    assert len(result["attempts"]) == 2
    assert [r["status"] for r in result["attempts"]] == [
        "improved_needs_next_round", "passed",
    ]
    assert len(router.calls) == 2
    assert first_file.read_text(encoding="utf-8") == FIXED
    assert second_file.read_text(encoding="utf-8") == FIXED
    assert set(result["changed_files"]) == {first.file_path, second.file_path}


def test_changing_defect_count_does_not_revert_verified_original_fix(tmp_path, monkeypatch):
    proposal, module, file = _setup(tmp_path)
    import roblox_mod_ai.source_repair_cycle as cycle
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *args: True)
    middle = "--!strict\nlocal fuel = 10\nreturn fuel\n"
    finished = "--!strict\nlocal fuel = 10\nreturn fuel + 1\n"

    class PatchRouter:
        def __init__(self):
            self.fixes = 0
            self.focus = 0
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Patch exactly ONE"):
                self.fixes += 1
                if self.fixes == 1:
                    return {"before": "local fuel = 0", "after": "local fuel = 10"}
                return {"before": "return fuel", "after": "return fuel + 1"}
            assert prompt.startswith("Independent narrow source-diff")
            self.focus += 1
            return {"resolved": True, "evidence_quote": "local fuel = 10",
                    "reason": "Original zero fuel initialization was corrected"}
    router = PatchRouter()
    def review():
        source = file.read_text(encoding="utf-8")
        row = ({
            "file": module.file_path, "quote": "local fuel = 0",
            "line": 2, "severity": "blocking",
            "issue": "The fuel is initialized to zero with no usable amount",
            "repair": "Set initial fuel to a positive validated amount",
            "evidence": "requirement_effect_review_source_quote",
        } if source == SOURCE else {
            "file": module.file_path, "quote": "return fuel",
            "line": 3, "severity": "blocking",
            "issue": "The fuel getter has no derived usage feedback",
            "repair": "Return a useful positive observable result",
            "evidence": "requirement_effect_review_source_quote",
        })
        return {
            "status": "reviewed_no_blockers" if source == finished else "issues_found",
            "fully_covered": True, "source_sha256": {
                module.file_path: _sha(source)
            },
            "findings": [] if source == finished else [row],
        }
    initial = review()
    result = run_source_repair_cycle(
        proposal, tmp_path, router, initial,
        verify=lambda: {"passed": True}, review_again=review,
        max_rounds=2, allow_host_gameplay_repairs=True,
    )
    assert result["passed"]
    assert file.read_text(encoding="utf-8") == finished
    assert result["attempts"][0]["status"] == "improved_needs_next_round"
    assert result["attempts"][0]["scoped_progress"][module.file_path]["resolved"]
    assert result["attempts"][0]["review"]["status"] == "issues_found"
    assert result["attempts"][1]["status"] == "passed"
    assert router.focus == 1


def test_scoped_reviewer_must_show_real_new_code_evidence(tmp_path, monkeypatch):
    proposal, module, file = _setup(tmp_path)
    import roblox_mod_ai.source_repair_cycle as cycle
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *args: True)
    initial = _report(module.file_path, SOURCE)
    initial["findings"][0]["evidence"] = "requirement_effect_review_source_quote"

    class FalseProgress:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Patch exactly ONE"):
                return {"before": "local fuel = 0", "after": "local fuel = 10"}
            return {"resolved": True, "evidence_quote": "fantasy_source_not_present",
                    "reason": "Model mistakenly called patch complete"}
    def still_blocked():
        new = _report(module.file_path, file.read_text(encoding="utf-8"))
        new["findings"][0]["issue"] = "Different unresolved action defect"
        return new
    result = run_source_repair_cycle(
        proposal, tmp_path, FalseProgress(), initial,
        verify=lambda: {"passed": True},
        review_again=still_blocked, max_rounds=1,
        allow_host_gameplay_repairs=True,
    )
    assert not result["passed"]
    assert file.read_text(encoding="utf-8") == SOURCE
    assert result["changed_files"] == []
