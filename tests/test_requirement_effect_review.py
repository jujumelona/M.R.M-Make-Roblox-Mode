"""No Studio required: test the behavior review and guarded repair boundary."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.requirement_effect_review import review_requirement_effects
from roblox_mod_ai.source_repair_cycle import run_source_repair_cycle

BEFORE = "--!strict\nlocal rank = 0\nrank += 1\nreturn rank\n"
AFTER = "--!strict\nlocal thrust = 1\nthrust += 1\nreturn thrust\n"
FILE = "src/server/ShipUpgrade.luau"


def setup(tmp_path: Path, module_id: str = "dyn_ship_upgrade"):
    module = SimpleNamespace(name="ShipUpgrade", module_id=module_id,
                             file_path=FILE, code=BEFORE)
    target = tmp_path / FILE
    target.parent.mkdir(parents=True)
    target.write_text(BEFORE, encoding="utf-8")
    req = {
        "id": "req-thrust", "original_request": "Upgrade the ship's thrust",
        "expected_outcome": "The real ship thrust changes after purchase",
        "owner_modules": ["ShipUpgrade"], "owner_files": [FILE],
    }
    proposal = SimpleNamespace(
        modules=[module], requested_prompt=req["original_request"],
        game_design={"detailed_implementation_plan": {
            "required_functions": [req],
        }},
    )
    return proposal, module, target


class FakeModel:
    def __init__(self, results):
        self.results = iter(results)
        self.prompts = []
    def complete_json(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        return next(self.results)


def missing():
    return {"verdict": "missing", "file": FILE, "quote": "rank += 1",
            "issue": "Only rank increases; thrust is unchanged",
            "repair": "Update ship thrust state from purchased tier"}


def complete():
    return {"verdict": "implemented", "file": FILE,
            "quote": "thrust += 1", "issue": "none", "repair": "none"}


def test_original_requirement_compared_to_effect_and_quoted(tmp_path):
    proposal, _, _ = setup(tmp_path)
    model = FakeModel([missing()])
    result = review_requirement_effects(proposal, tmp_path, model)
    assert result["status"] == "issues_found" and result["fully_covered"]
    finding = result["findings"][0]
    assert finding["line"] == 3 and finding["requirement_id"] == "req-thrust"
    assert finding["evidence"] == "requirement_effect_review_source_quote"
    assert "real ship thrust" in model.prompts[0]
    assert "rank += 1" in model.prompts[0]


def test_fabricated_positive_evidence_never_passes(tmp_path):
    proposal, _, _ = setup(tmp_path)
    model = FakeModel([{
        "verdict": "implemented", "file": FILE, "quote": "ship.Thrust = 99",
        "issue": "none", "repair": "none",
    }])
    result = review_requirement_effects(proposal, tmp_path, model)
    assert result["status"] == "failed" and not result["fully_covered"]
    assert "fabricated" in result["reason"]


def test_uncertain_reviewer_never_counts_as_pass(tmp_path):
    proposal, _, _ = setup(tmp_path)
    result = review_requirement_effects(proposal, tmp_path, FakeModel([{
        "verdict": "uncertain", "file": FILE, "quote": "",
        "issue": "Source excerpt did not show physics", "repair": "none",
    }]))
    assert result["status"] == "failed"


class Planner:
    def complete_json(self, **kwargs):
        return {"file": FILE,
                "root_cause": "Thrust not updated by rank purchase",
                "change_strategy": "Update real thrust after currency charge",
                "invariants": ["Keep server authority"],
                "regression_tests": ["New rank changes thrust"]}


def fake_agent():
    class Agent:
        def __init__(self, **kwargs):
            pass
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            return AFTER
    return Agent


def test_generated_host_gameplay_may_be_repaired_only_on_semantic_evidence(tmp_path, monkeypatch):
    proposal, module, target = setup(tmp_path)
    import roblox_mod_ai.source_repair_cycle as cycle
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *args: True)
    initial = review_requirement_effects(proposal, tmp_path, FakeModel([missing()]))
    verified = []
    def verify():
        verified.append(target.read_text(encoding="utf-8"))
        return {"passed": target.read_text(encoding="utf-8") == AFTER}
    def review_again():
        return review_requirement_effects(proposal, tmp_path, FakeModel([complete()]))
    blocked = run_source_repair_cycle(
        proposal, tmp_path, Planner(), initial, verify=verify,
        review_again=review_again, agent_factory=fake_agent(),
    )
    assert blocked["status"] == "blocked" and target.read_text(encoding="utf-8") == BEFORE
    fixed = run_source_repair_cycle(
        proposal, tmp_path, Planner(), initial, verify=verify,
        review_again=review_again, allow_host_gameplay_repairs=True,
        agent_factory=fake_agent(),
    )
    assert fixed["passed"] and target.read_text(encoding="utf-8") == AFTER
    assert verified == [AFTER]


def test_host_infrastructure_remains_immutable_even_with_gap_evidence(tmp_path, monkeypatch):
    proposal, _, target = setup(tmp_path, module_id="mod_network_bridge")
    import roblox_mod_ai.source_repair_cycle as cycle
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *args: True)
    initial = review_requirement_effects(proposal, tmp_path, FakeModel([missing()]))
    result = run_source_repair_cycle(
        proposal, tmp_path, Planner(), initial, verify=lambda: {"passed": True},
        review_again=lambda: None, allow_host_gameplay_repairs=True,
        agent_factory=fake_agent(),
    )
    assert result["status"] == "blocked"
    assert target.read_text(encoding="utf-8") == BEFORE


def test_failed_validation_rolls_back_host_gameplay_patch(tmp_path, monkeypatch):
    proposal, _, target = setup(tmp_path)
    import roblox_mod_ai.source_repair_cycle as cycle
    monkeypatch.setattr(cycle, "host_source_must_regenerate", lambda *args: True)
    initial = review_requirement_effects(proposal, tmp_path, FakeModel([missing()]))
    result = run_source_repair_cycle(
        proposal, tmp_path, Planner(), initial,
        verify=lambda: {"passed": False, "reason": "revised source breaks API"},
        review_again=lambda: None, allow_host_gameplay_repairs=True,
        max_rounds=1, agent_factory=fake_agent(),
    )
    assert not result["passed"] and target.read_text(encoding="utf-8") == BEFORE


def test_multi_owner_requirement_reviews_entire_independent_server_files(tmp_path):
    proposal, module, file = setup(tmp_path)
    module.description = "Server upgrades the owned ship's thrust."
    another = SimpleNamespace(
        name="MarketTrade", module_id="dyn_market_trade",
        file_path="src/server/MarketTrade.luau", code="--!strict\\nreturn true\\n",
        description="Transfer currency and item to the buyer",
    )
    other_path = tmp_path / another.file_path
    other_path.parent.mkdir(parents=True, exist_ok=True)
    other_path.write_text(another.code, encoding="utf-8")
    proposal.modules.append(another)
    requirement = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    requirement["owner_files"] = [module.file_path, another.file_path]
    requirement["owner_modules"] = [module.name, another.name]
    # A long middle section must NEVER vanish from the source the model sees.
    long_middle = "\\n".join("local sentinel%03d = %d" % (i, i) for i in range(90))
    complete_first = BEFORE.replace("rank += 1", long_middle + "\\nrank += 1")
    file.write_text(complete_first, encoding="utf-8")
    model = FakeModel([
        {"verdict": "missing", "file": another.file_path, "quote": "return true",
         "issue": "No server currency or item ownership transfer",
         "repair": "Transfer validated balances to both players"},
        {"verdict": "missing", "file": FILE, "quote": "rank += 1",
         "issue": "Only rank increases and the thrust does not change",
         "repair": "Modify owned vehicle's thrust after upgrade"},
    ])
    outcome = review_requirement_effects(proposal, tmp_path, model)
    assert outcome["status"] == "issues_found" and outcome["fully_covered"]
    assert len(outcome["findings"]) == 2
    assert len(model.prompts) == 2
    assert "sentinel050" in model.prompts[1] or "sentinel050" in model.prompts[0]
    assert "SOURCE EXCERPT OMITTED" not in "\\n".join(model.prompts)


def test_oversized_complete_source_fails_without_fabricated_approval(tmp_path):
    proposal, module, file = setup(tmp_path)
    file.write_text(BEFORE + ("-- source section\\n" * 1100), encoding="utf-8")
    model = FakeModel([])
    result = review_requirement_effects(proposal, tmp_path, model)
    assert result["status"] == "failed"
    assert "exceeds reviewer context" in result["reason"]
    assert model.prompts == []
