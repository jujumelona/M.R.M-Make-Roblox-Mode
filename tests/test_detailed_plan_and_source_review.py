"""Generic game planning and AI source-inspection regression tests.

These tests deliberately cannot claim Roblox engine gameplay execution.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.detailed_plan import build_detailed_plan, audit_detailed_plan
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
