"""A complete build cannot pass from one cherry-picked action quote.

The post-generation pass checks EVERY separately promised effect. Every
evidence quote is matched against disk source bytes, and actual missing
behavior is forwarded to the transactional repair loop for its owner.
"""
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.requirement_completion_audit import (
    audit_whole_requirement_completion, _obligations,
)

SHIP = "src/server/ShipServer.luau"
TRADE = "src/server/MarketServer.luau"
SOURCE_SHIP = (
    "--!strict\n"
    "local function build()\n"
    "    ship.Sections += 1\n"
    "    return ship.Sections\n"
    "end\n"
)
SOURCE_TRADE = (
    "--!strict\n"
    "local function sale()\n"
    "    stock.resources -= 1\n"
    "    return stock.resources\n"
    "end\n"
)


def fixture(tmp_path):
    for path, source in ((SHIP, SOURCE_SHIP), (TRADE, SOURCE_TRADE)):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    effects = [
        "Successful trade reduces owned resources and increases earned currency",
        "Purchasing a ship section attaches the new section to the owned ship",
    ]
    required = {
        "id": "req-generic",
        "original_request": "Trade resources for money and build ship sections",
        "expected_outcome": ". ".join(effects),
        "owner_files": [SHIP, TRADE],
        # Real generated proposals persist this at required_functions[*].
        "server_state_changes": effects,
    }
    proposal = SimpleNamespace(
        modules=[
            SimpleNamespace(name="ShipServer", file_path=SHIP),
            SimpleNamespace(name="MarketServer", file_path=TRADE),
        ],
        game_design={
            "detailed_implementation_plan": {"required_functions": [required]}
        },
    )
    return proposal


class Router:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def complete_json(self, **kwargs):
        self.prompts.append(kwargs)
        return self.response


def response(*, first="missing"):
    return {
        "checks": [
            {"id": "effect-01", "verdict": "implemented", "file": TRADE,
             "quote": "stock.resources -= 1",
             "issue": "none", "repair": "none"},
            {"id": "effect-02", "verdict": first, "file": TRADE,
             "quote": "stock.resources -= 1",
             "issue": "Currency balance is never increased in the authoritative wallet",
             "repair": "Credit the server-owned currency after validated inventory debit"},
            {"id": "effect-03", "verdict": "implemented", "file": SHIP,
             "quote": "ship.Sections += 1",
             "issue": "none", "repair": "none"},
        ],
        "extra_missing": [],
    }


def test_one_real_effect_cannot_approve_other_missing_effect(tmp_path):
    proposal = fixture(tmp_path)
    router = Router(response())
    report = audit_whole_requirement_completion(proposal, tmp_path, router)
    assert report["fully_covered"] and report["status"] == "issues_found"
    assert len(report["checks"]) == 3
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["file"] == TRADE
    assert finding["requirement_id"] == "req-generic"
    assert finding["evidence"] == "requirement_effect_review_source_quote"
    assert "currency" in finding["issue"].lower()
    assert "original_user_request" in router.prompts[0]["prompt"]
    assert "stock.resources -= 1" in router.prompts[0]["prompt"]
    assert "ship.Sections += 1" in router.prompts[0]["prompt"]


def test_missing_effect_checks_cannot_silently_disappear(tmp_path):
    proposal = fixture(tmp_path)
    router = Router({"checks": response()["checks"][:1], "extra_missing": []})
    report = audit_whole_requirement_completion(proposal, tmp_path, router)
    assert report["status"] == "failed"
    assert not report["fully_covered"]
    assert "incomplete" in report["reason"]


def test_fabricated_quote_cannot_count_as_implemented(tmp_path):
    proposal = fixture(tmp_path)
    result = response(first="implemented")
    result["checks"][1]["quote"] = "coins.Value += 999"
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(result))
    assert report["status"] == "failed"
    assert "ungrounded" in report["reason"]


def test_comment_only_quote_cannot_certify_effect(tmp_path):
    proposal = fixture(tmp_path)
    source = (tmp_path / TRADE).read_text()
    (tmp_path / TRADE).write_text(
        source + "\n-- This action adds earned currency to wallet\n",
        encoding="utf-8")
    result = response(first="implemented")
    result["checks"][1]["quote"] = "This action adds earned currency to wallet"
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(result))
    assert report["status"] == "failed"
    assert "ungrounded" in report["reason"]


def test_extra_original_action_not_in_plan_still_blocks_build(tmp_path):
    proposal = fixture(tmp_path)
    (tmp_path / TRADE).write_text(
        (tmp_path / TRADE).read_text() + "\nstock.money += 1\n",
        encoding="utf-8")
    result = response(first="implemented")
    result["checks"][1]["quote"] = "stock.money += 1"
    result["extra_missing"] = [{
        "behavior": "Player must visibly receive money after a trade",
        "file": TRADE, "quote": "return stock.resources",
        "issue": "Trade never increases the displayed player's currency",
        "repair": "Credit real wallet and replicate confirmed balance",
    }]
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(result))
    assert report["status"] == "issues_found"
    assert len(report["findings"]) == 1
    assert report["findings"][0]["behavior"].startswith("Player")


def test_all_effects_with_real_source_evidence_can_pass_source_review(tmp_path):
    proposal = fixture(tmp_path)
    (tmp_path / TRADE).write_text(
        (tmp_path / TRADE).read_text() + "\nstock.money += 1\n",
        encoding="utf-8")
    result = response(first="implemented")
    result["checks"][1]["quote"] = "stock.money += 1"
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(result))
    assert report["status"] == "reviewed_no_blockers"
    assert report["fully_covered"]
    assert report["findings"] == []
    assert "Studio" in report["reason"]


def test_no_usable_expected_effect_does_not_default_to_pass(tmp_path):
    proposal = fixture(tmp_path)
    requirement = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    requirement["server_state_changes"] = []
    requirement["expected_outcome"] = ""
    assert _obligations(requirement) == []
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(response()))
    assert report["status"] == "failed"
    assert not report["executed"]


def test_missing_obligation_is_repaired_in_place_then_all_effects_reaudited(
        tmp_path, monkeypatch):
    """End-to-end: completed audit -> targeted hunk -> re-audit -> accept."""
    from hashlib import sha256
    import roblox_mod_ai.source_repair_cycle as cycle

    proposal = fixture(tmp_path)
    for index, module in enumerate(proposal.modules):
        module.module_id = "dyn_" + str(index)
        module.kind = "server_module"
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *a: True)

    class Model:
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Patch exactly ONE"):
                return {"edits": [{
                    "before": "    stock.resources -= 1",
                    "after": "    stock.resources -= 1\n    stock.money += 1",
                }]}
            assert "Post-generation" in prompt
            complete = "stock.money += 1" in (tmp_path / TRADE).read_text()
            result = response(first="implemented" if complete else "missing")
            if complete:
                result["checks"][1]["quote"] = "stock.money += 1"
            return result

    router = Model()
    initial = audit_whole_requirement_completion(proposal, tmp_path, router)
    assert initial["status"] == "issues_found"
    initial["source_sha256"] = {
        module.file_path: sha256(
            (tmp_path / module.file_path).read_bytes()
        ).hexdigest()
        for module in proposal.modules
    }
    outcome = cycle.run_source_repair_cycle(
        proposal, tmp_path, router, initial,
        verify=lambda: {
            "passed": "stock.money += 1" in (tmp_path / TRADE).read_text()
        },
        review_again=lambda: audit_whole_requirement_completion(
            proposal, tmp_path, router,
        ),
        allow_host_gameplay_repairs=True,
        max_rounds=2,
    )
    assert outcome["passed"] is True, outcome
    assert outcome["changed_files"] == [TRADE]
    assert outcome["final_review"]["status"] == "reviewed_no_blockers"
    assert "stock.money += 1" in (tmp_path / TRADE).read_text()
    assert "ship.Sections += 1" in (tmp_path / SHIP).read_text()


def test_rejected_obligation_repair_restores_previous_gameplay_source(
        tmp_path, monkeypatch):
    """An unproven correction must never silently replace an existing module."""
    from hashlib import sha256
    import roblox_mod_ai.source_repair_cycle as cycle

    proposal = fixture(tmp_path)
    for index, module in enumerate(proposal.modules):
        module.module_id = "dyn_" + str(index)
        module.kind = "server_module"
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *a: True)

    class BadModel:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Patch exactly ONE"):
                return {"edits": [{
                    "before": "    stock.resources -= 1",
                    "after": "    stock.resources -= 2",
                }]}
            return response()

    router = BadModel()
    original = (tmp_path / TRADE).read_text()
    initial = audit_whole_requirement_completion(proposal, tmp_path, router)
    initial["source_sha256"] = {
        module.file_path: sha256((tmp_path / module.file_path).read_bytes()).hexdigest()
        for module in proposal.modules
    }
    outcome = cycle.run_source_repair_cycle(
        proposal, tmp_path, router, initial,
        verify=lambda: {"passed": False, "reason": "Unrelated behavior regressed"},
        review_again=lambda: audit_whole_requirement_completion(
            proposal, tmp_path, router,
        ),
        allow_host_gameplay_repairs=True,
        max_rounds=1,
    )
    assert not outcome["passed"]
    assert (tmp_path / TRADE).read_text() == original
