"""Generic game planning and AI source-inspection regression tests.

These tests deliberately cannot claim Roblox engine gameplay execution.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.detailed_plan import build_detailed_plan, audit_detailed_plan, enrich_detailed_plan
from roblox_mod_ai.source_review import review_generated_sources


def example():
    modules = [
        SimpleNamespace(module_id="dyn_spaceship", name="ShipMovement",
                        file_path="src/server/ShipMovement.luau",
                        roblox_service="ServerScriptService", kind="server_module",
                        depends_on=["mod_network"], description="Move spaceship and spend fuel"),
        SimpleNamespace(module_id="mod_network", name="NetworkRemotes",
                        file_path="src/shared/NetworkRemotes.luau",
                        roblox_service="ReplicatedStorage", kind="shared_module",
                        depends_on=[], description="Shared events"),
    ]
    blueprint = {
        "requirements": [{
            "id": "req-01", "source": "우주선이 이동하면서 연료를 소모",
            "acceptance": "Movement reduces server fuel state and denies zero fuel",
            "owners": ["ShipMovement"], "missing": False,
        }],
        "mechanics": [{
            "id": "move", "owners": ["ShipMovement"],
            "interaction": "player requests flight",
            "precondition": "fuel > 0 and craft is active",
            "postcondition": "validated flight reduces fuel",
            "rejection": "zero fuel refuses movement",
            "persistence": "save fuel if required",
        }],
        "integration_contracts": [{
            "id": "move_to_hud", "owners": ["ShipMovement", "NetworkRemotes"],
            "depends_on": ["move", "ui"], "expected": "fuel reaches HUD",
            "negative_test": "forged request rejected",
        }],
        "blocking_issues": [],
    }
    return SimpleNamespace(
        requested_prompt="우주선이 이동하면서 연료를 소모",
        modules=modules,
        game_design={
            "project_mode": "new_experience",
            "implementation_blueprint": blueprint,
            "pre_design_research": {"ledger": {"requirements": [{
                "id": "req-01", "statement": "우주선이 이동하면서 연료를 소모"}]}},
            "dynamic_design": {
                "module_requirements": {"dyn_spaceship": ["req-01"]},
                "module_behaviors": {"dyn_spaceship": "spend fuel"},
            },
        },
    )


def test_detailed_plan_preserves_original_behavior_and_edge_cases_without_genre_rules():
    p = example()
    plan = build_detailed_plan(p)
    assert plan["runtime_execution"] == "excluded_from_colab"
    row = plan["required_functions"][0]
    assert row["original_request"] == "우주선이 이동하면서 연료를 소모"
    assert row["owner_files"] == ["src/server/ShipMovement.luau"]
    assert row["preconditions"] == ["fuel > 0 and craft is active"]
    assert row["invalid_or_edge_inputs"] == ["zero fuel refuses movement"]
    assert row["server_state_changes"] == ["validated flight reduces fuel"]
    assert plan["cross_module_connections"][0]["id"] == "move_to_hud"
    assert plan["blocking_issues"] == []
    p.game_design["detailed_implementation_plan"] = deepcopy(plan)
    assert audit_detailed_plan(p)["passed"]
    p.modules[0].file_path = "src/server/Altered.luau"
    assert not audit_detailed_plan(p)["passed"]


def test_unowned_new_requirement_blocks_detail_plan():
    p = example()
    p.game_design["implementation_blueprint"]["requirements"].append({
        "id": "req-02", "source": "unimplemented feature",
        "acceptance": "effect occurs", "owners": [],
    })
    plan = build_detailed_plan(p)
    assert any("no implementation owner" in x for x in plan["blocking_issues"])


def _write_modules(p, root):
    for m in p.modules:
        path = root / m.file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("--!strict\nlocal result = 42\nreturn result\n", encoding="utf-8")


class FakeReviewer:
    def __init__(self, finding=None):
        self.finding = finding
        self.calls = []

    def complete_json(self, **kw):
        self.calls.append(kw)
        return {"findings": [self.finding] if self.finding else []}


def test_ai_rechecks_every_module_and_grounds_defects_in_real_source(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    p = example()
    p.game_design["detailed_implementation_plan"] = build_detailed_plan(p)
    _write_modules(p, tmp_path)
    fake = FakeReviewer({"line": 2, "quote": "local result = 42",
                         "severity": "blocking", "issue": "No fuel state changes",
                         "repair": "Check fuel in server movement"})
    res = review_generated_sources(p, tmp_path, fake, max_lines_per_chunk=40)
    assert res["executed"] and res["fully_covered"]
    assert res["status"] == "issues_found"
    assert len(res["reviewed"]) == 2
    assert len(res["findings"]) == 2
    assert all(x["evidence"] == "source_line_quote_matched" for x in res["findings"])
    assert all(x["role"] == "analyzer" for x in fake.calls)
    assert res["scope"] == "static_ai_reinspection_no_roblox_engine"


def test_hallucinated_quote_never_blocks_generated_code(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    p = example()
    p.game_design["detailed_implementation_plan"] = build_detailed_plan(p)
    _write_modules(p, tmp_path)
    fake = FakeReviewer({"line": 2, "quote": "os.execute('rm -rf /')",
                         "severity": "blocking", "issue": "Fabricated code"})
    res = review_generated_sources(p, tmp_path, fake)
    assert res["status"] == "reviewed_no_blockers"
    assert not res["findings"]


def test_disabled_ai_never_pretends_model_review_was_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "0")
    result = review_generated_sources(example(), tmp_path, FakeReviewer())
    assert result["status"] == "not_run"
    assert result["executed"] is False
    assert result["fully_covered"] is False


def test_model_error_fails_review_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    p = example()
    p.game_design["detailed_implementation_plan"] = build_detailed_plan(p)
    _write_modules(p, tmp_path)
    class Broken:
        def complete_json(self, **kw):
            raise ValueError("invalid model response")
    res = review_generated_sources(p, tmp_path, Broken())
    assert res["status"] == "failed"
    assert not res["fully_covered"]


def test_model_elaborates_each_original_requirement_with_state_and_negative_cases(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "1")
    p = example()
    plan = build_detailed_plan(p)
    class Planner:
        def __init__(self):
            self.calls = []
        def complete_json(self, **kw):
            self.calls.append(kw)
            return {
                "steps": ["check fuel", "move in permitted state"],
                "preconditions": ["a valid ship is present"],
                "server_state_changes": ["fuel decreases"],
                "client_feedback": ["updated fuel appears in HUD"],
                "failure_cases": ["zero fuel denies movement"],
                "cross_module_interfaces": ["ship service sends fuel to client"],
                "offline_verification": ["zero fuel input keeps ship position fixed"],
            }
    ai = Planner()
    enriched = enrich_detailed_plan(plan, ai)
    p.game_design["detailed_implementation_plan"] = enriched
    assert enriched["ai_planning"]["status"] == "enriched"
    assert set(enriched["ai_planning"]["requirements"]) == {"req-01"}
    assert "server_state_changes" in enriched["ai_planning"]["requirements"]["req-01"]
    assert len(ai.calls) == 1
    assert ai.calls[0]["role"] == "planner"
    assert audit_detailed_plan(p)["passed"]


def test_model_plan_fails_closed_on_empty_or_incomplete_steps(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "1")
    p = example()
    class Missing:
        def complete_json(self, **kw):
            return {"steps": ["something"]}
    planned = enrich_detailed_plan(build_detailed_plan(p), Missing())
    p.game_design["detailed_implementation_plan"] = planned
    assert planned["ai_planning"]["status"] == "failed"
    assert not audit_detailed_plan(p)["passed"]


def test_ai_planning_skips_if_model_generation_disabled(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "0")
    monkeypatch.setenv("RMM_MODEL_BASE_URL", "http://localhost:9999")
    monkeypatch.delenv("RMM_ENABLE_AI_DETAILED_PLAN", raising=False)
    p = example()
    planned = enrich_detailed_plan(build_detailed_plan(p), object())
    assert planned["ai_planning"]["status"] == "not_run"


def test_truncated_detailed_plan_recovers_by_splitting_json_fields(monkeypatch):
    """Regression: proposal 13's first 7-field JSON ended with finish_reason=length."""
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "1")
    p = example()
    class TruncatingPlanner:
        def __init__(self):
            self.calls = []
        def complete_json(self, **kw):
            self.calls.append(kw)
            keys = tuple(kw["prompt"].split("JSON keys: ", 1)[1]
                         .split("\n", 1)[0].split(", "))
            if len(keys) > 4:
                raise ValueError("Model JSON completion truncated (finish_reason=length)")
            return {key: ["validate original requirement and reject invalid state"]
                    for key in keys}
    ai = TruncatingPlanner()
    plan = enrich_detailed_plan(build_detailed_plan(p), ai)
    p.game_design["detailed_implementation_plan"] = plan
    assert plan["ai_planning"]["status"] == "enriched"
    details = plan["ai_planning"]["requirements"]["req-01"]
    assert set(details) == {
        "steps", "preconditions", "server_state_changes", "client_feedback",
        "failure_cases", "cross_module_interfaces", "offline_verification",
    }
    assert len(ai.calls) == 3
    assert all(call["role"] == "planner" for call in ai.calls)
    assert all(call["max_tokens"] == 2048 for call in ai.calls)
    assert audit_detailed_plan(p)["passed"]


def test_detailed_plan_single_field_failure_is_not_silently_accepted(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "1")
    p = example()
    class Unrepairable:
        def complete_json(self, **kw):
            keys = tuple(kw["prompt"].split("JSON keys: ", 1)[1]
                         .split("\n", 1)[0].split(", "))
            if len(keys) > 1:
                raise ValueError("Model JSON completion truncated (finish_reason=length)")
            return {"wrong_field": ["unusable"]}
    plan = enrich_detailed_plan(build_detailed_plan(p), Unrepairable())
    p.game_design["detailed_implementation_plan"] = plan
    assert plan["ai_planning"]["status"] == "failed"
    assert "req-01" in plan["ai_planning"]["reason"]
    assert not audit_detailed_plan(p)["passed"]


def test_detailed_plan_non_output_model_error_never_retries(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "1")
    p = example()
    class Offline:
        calls = 0
        def complete_json(self, **kw):
            self.calls += 1
            raise RuntimeError("model server unreachable")
    ai = Offline()
    plan = enrich_detailed_plan(build_detailed_plan(p), ai)
    assert ai.calls == 1
    assert plan["ai_planning"]["status"] == "failed"
    assert "model server unreachable" in plan["ai_planning"]["reason"]
