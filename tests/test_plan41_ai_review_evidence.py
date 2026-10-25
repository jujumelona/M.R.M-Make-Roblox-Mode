"""Proposal 41: prevent quoted AI conjecture from halting host generation.

The regression matches the real failure's provenance and leaves all findings
visible. It does NOT claim the host source implements a working Roblox game.
"""
from pathlib import Path
from types import SimpleNamespace as NS

from roblox_mod_ai import source_finding_adjudication as adjudication
from roblox_mod_ai.source_review import review_generated_sources
from roblox_mod_ai.verification_selector import make_verification_report


def proposal(modules):
    return NS(requested_prompt="Mine resources and build a spacecraft",
              modules=modules, game_design={
                  "detailed_implementation_plan": {
                      "required_functions": [{"id": "req-1",
                           "original_request": "Earn resources and buy upgrades"}],
                      "implementation_modules": [{"name": x.name,
                          "requirements": ["req-1"]} for x in modules],
                  },
              })


def mod(name, id, path):
    return NS(module_id=id, name=name, file_path=path, code="")


def review(path, line, quote, issue):
    return {"status": "issues_found", "fully_covered": True,
            "source_sha256": {path: "abc"},
            "reviewed": [{"file": path, "from_line": 1, "to_line": 3}],
            "findings": [{"file": path, "line": line, "quote": quote,
                          "issue": issue, "severity": "blocking",
                          "evidence": "source_line_quote_matched",
                          "repair": "Replace the entire file"}]}


def scope_for(monkeypatch, modules, strategies):
    monkeypatch.setattr(adjudication, "generation_scope",
        lambda p: {"modules": [
            {"module_id": x.module_id, "strategy": strategies[x.module_id]}
            for x in modules
        ]})


def test_host_model_claim_is_preserved_as_unverified_not_auto_repaired(monkeypatch):
    m = mod("AlienCombat", "dyn_combat", "src/client/AlienCombat.client.luau")
    scope_for(monkeypatch, [m], {m.module_id: "host_space_action"})
    p = proposal([m])
    original = review(m.file_path, 2, 'remote:InvokeServer({ selection = "alien" })',
                      "Falsely treats alien combat as mining")
    actual = adjudication.adjudicate_source_findings(p, original)
    assert original["findings"][0]["severity"] == "blocking"  # never mutate input
    assert actual["status"] == "reviewed_unverified_host_claims"
    assert actual["fully_covered"]
    assert len(actual["findings"]) == 1
    assert actual["findings"][0]["claimed_severity"] == "blocking"
    assert actual["findings"][0]["severity"] == "advisory"
    assert actual["findings"][0]["adjudication"] == "unverified_host_model_claim"
    assert len(actual["unverified_host_claims"]) == 1
    assert "not a passed" in actual["reason"].lower()


def test_model_authored_source_remains_blocking_and_repairable(monkeypatch):
    m = mod("ShipEngine", "dyn_engine", "src/server/ShipEngine.luau")
    scope_for(monkeypatch, [m], {m.module_id: "bounded_server_action"})
    result = adjudication.adjudicate_source_findings(
        proposal([m]), review(m.file_path, 2, "return true",
                              "Missing an actual fuel decrement"))
    assert result["status"] == "issues_found"
    assert result["findings"][0]["severity"] == "blocking"
    assert not result["unverified_host_claims"]


def test_unknown_provenance_keeps_blocker_instead_of_false_pass(monkeypatch):
    m = mod("AlienCombat", "dyn_combat", "src/client/AlienCombat.client.luau")
    monkeypatch.setattr(adjudication, "generation_scope",
                        lambda _: {"modules": []})
    result = adjudication.adjudicate_source_findings(
        proposal([m]), review(m.file_path, 2, "return true", "Unverified behavior"))
    assert result["status"] == "issues_found"
    assert result["findings"][0]["severity"] == "blocking"
    assert "provenance_unavailable" in result["adjudication"]


def test_live_reviewer_routes_host_claims_after_full_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "1")
    m = mod("AlienCombat", "dyn_combat", "src/client/AlienCombat.client.luau")
    scope_for(monkeypatch, [m], {m.module_id: "host_space_action"})
    p = proposal([m])
    fp = tmp_path / m.file_path
    fp.parent.mkdir(parents=True)
    fp.write_text("--!strict\nlocal r = 1\nreturn r\n")

    class Model:
        def complete_json(self, **kwargs):
            return {"findings": [{"line": 2, "quote": "local r = 1",
                                 "severity": "blocking", "issue": "A guessed problem",
                                 "repair": "Replace module"}]}

    result = review_generated_sources(p, tmp_path, Model())
    assert result["fully_covered"]
    assert result["status"] == "reviewed_unverified_host_claims"
    assert result["reviewed"][0]["from_line"] == 1
    assert result["unverified_host_claims"]


def test_verification_reports_review_as_unverified_not_passed(monkeypatch):
    m = mod("AlienCombat", "dyn_combat", "src/client/AlienCombat.client.luau")
    scope_for(monkeypatch, [m], {m.module_id: "host_space_action"})
    reviewed = adjudication.adjudicate_source_findings(
        proposal([m]), review(m.file_path, 2, "return true", "Unproven claim"))
    outcome = make_verification_report(
        source_only=False, addon_mode=False,
        tool_results={"ai_source_review": reviewed},
        analysis_passed=True, acceptance={"passed": True}, artifact_ready=False,
    )
    assert outcome["checks"]["ai_source_review"]["status"] == "unverified"
    assert outcome["checks"]["ai_source_review"]["executed"] is True
    assert outcome["summary"]["unverified"] == 1
    assert outcome["gameplay_verified"] is False
