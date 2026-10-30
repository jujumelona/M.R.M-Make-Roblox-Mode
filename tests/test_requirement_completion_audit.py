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
            (tmp_path / module.file_path).read_text(encoding="utf-8").encode("utf-8")
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
        module.file_path: sha256((tmp_path / module.file_path).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
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


class RecoveringRouter:
    """Simulate the small model's short/malformed batch and bounded replies."""

    def __init__(self, *, initial="partial", fail_single=False):
        self.initial = initial
        self.fail_single = fail_single
        self.prompts = []

    def complete_json(self, **kwargs):
        prompt = kwargs["prompt"]
        self.prompts.append(kwargs)
        if prompt.startswith("Post-generation"):
            if self.initial == "length":
                raise ValueError("finish_reason=length: completion truncated")
            if self.initial == "duplicates":
                items = response(first="implemented")["checks"]
                return {"checks": [items[0], items[0], *items[1:]],
                        "extra_missing": []}
            if self.initial == "no_extras":
                return {"checks": [], "extra_missing": None}
            return {"checks": response()["checks"][:1], "extra_missing": []}
        if prompt.startswith("Find user-requested"):
            return {"extra_missing": []}
        assert prompt.startswith("Audit exactly ONE"), prompt[:120]
        assert "complete_server_sources" in prompt
        if self.fail_single:
            return {"verdict": "implemented", "file": TRADE,
                    "quote": "invented imaginary server code"}
        if "increases earned currency" in prompt:
            return {"verdict": "missing", "file": TRADE,
                    "quote": "stock.resources -= 1",
                    "issue": "Currency balance is never increased in the authoritative wallet",
                    "repair": "Credit the server-owned wallet after successful inventory debit"}
        if "Purchasing a ship section" in prompt:
            return {"verdict": "implemented", "file": SHIP,
                    "quote": "ship.Sections += 1", "issue": "none", "repair": "none"}
        if "Successful trade reduces" in prompt:
            return {"verdict": "implemented", "file": TRADE,
                    "quote": "stock.resources -= 1", "issue": "none", "repair": "none"}
        raise AssertionError("Unknown independent effect")


def test_incomplete_batch_recovers_each_missing_effect_without_false_pass(tmp_path):
    router = RecoveringRouter(initial="partial")
    report = audit_whole_requirement_completion(fixture(tmp_path), tmp_path, router)
    assert report["status"] == "issues_found", report
    assert report["fully_covered"]
    assert {v["id"] for v in report["checks"]} == {
        "effect-01", "effect-02", "effect-03"
    }
    assert len(report["findings"]) == 1
    assert [x["effect_id"] for x in report["recovery"]
            if x["stage"] == "single_effect"] == ["effect-02", "effect-03"]
    assert len(router.prompts) == 4
    assert any(p["prompt"].startswith("Find user-requested")
               for p in router.prompts)


def test_duplicate_effect_is_reaudited_not_double_counted(tmp_path):
    router = RecoveringRouter(initial="duplicates")
    report = audit_whole_requirement_completion(fixture(tmp_path), tmp_path, router)
    assert report["status"] == "reviewed_no_blockers", report
    assert report["fully_covered"]
    assert len(report["checks"]) == 3
    assert [x["effect_id"] for x in report["recovery"]
            if x["stage"] == "single_effect"] == ["effect-01"]


def test_truncated_model_output_recovers_all_effects_and_original_scope(tmp_path):
    router = RecoveringRouter(initial="length")
    report = audit_whole_requirement_completion(fixture(tmp_path), tmp_path, router)
    assert report["status"] == "issues_found", report
    assert len(report["checks"]) == 3
    assert len(report["findings"]) == 1
    assert any(x["stage"] == "batch_output" for x in report["recovery"])
    assert any(p["prompt"].startswith("Find user-requested")
               for p in router.prompts)


def test_invalid_single_evidence_cannot_be_accepted_on_recovery(tmp_path):
    router = RecoveringRouter(initial="partial", fail_single=True)
    report = audit_whole_requirement_completion(fixture(tmp_path), tmp_path, router)
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert report["checks"] == [] or all(
        x.get("verdict") != "implemented" or x.get("line") for x in report["checks"]
    )


def test_missing_extra_audit_is_repeated_instead_of_skipped(tmp_path):
    router = RecoveringRouter(initial="no_extras")
    report = audit_whole_requirement_completion(fixture(tmp_path), tmp_path, router)
    assert report["status"] == "issues_found", report
    assert report["fully_covered"]
    assert any(p["prompt"].startswith("Find user-requested")
               for p in router.prompts)


def test_large_requirement_never_requests_unbounded_batch(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "Successful trade reduces server-owned resources",
        "Successful sale increases earned server-owned currency",
        "Purchasing a ship section attaches the owned part",
        "Completing the purchase persists the ship ownership state",
    ]

    class BoundedModel:
        def __init__(self):
            self.prompts = []

        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.prompts.append(prompt)
            assert not prompt.startswith("Post-generation"), (
                "Large batch should not be sent to a small model"
            )
            if prompt.startswith("Find user-requested"):
                return {"extra_missing": []}
            assert prompt.startswith("Audit exactly ONE")
            return {"verdict": "implemented", "file": SHIP,
                    "quote": "ship.Sections += 1",
                    "issue": "none", "repair": "none"}

    router = BoundedModel()
    report = audit_whole_requirement_completion(proposal, tmp_path, router)
    assert not report["fully_covered"], report
    assert "shared evidence" in report["reason"], report
    assert any(x["stage"] == "batch_skipped" for x in report["recovery"])
    assert sum(x.startswith("Audit exactly ONE") for x in router.prompts) == 4



def test_host_numbered_compact_evidence_requires_real_line(tmp_path):
    from roblox_mod_ai.requirement_completion_audit import (
        _normalize_single_effect_answer, _source_scopes_for_effect,
    )
    proposal = fixture(tmp_path)
    sources = {
        SHIP: (tmp_path / SHIP).read_text(encoding="utf-8"),
        TRADE: (tmp_path / TRADE).read_text(encoding="utf-8"),
    }
    ranked, indexed = _source_scopes_for_effect(
        "Successful sale reduces resources and increases currency",
        sources, proposal.modules,
    )
    assert indexed and all("1:" in v for v in indexed.values())
    index = ranked.index(TRADE)
    line = sources[TRADE].splitlines().index("    stock.resources -= 1") + 1
    result = _normalize_single_effect_answer(
        {"verdict": "implemented", "file_id": index, "line": line},
        ranked, sources,
    )
    assert result is not None and result["quote"] == "stock.resources -= 1"
    assert result["file"] == TRADE
    assert _normalize_single_effect_answer(
        {"verdict": "implemented", "file_id": index, "line": 9999},
        ranked, sources,
    ) is None


def test_original_negative_rejection_clause_kept_with_its_operation():
    from roblox_mod_ai.requirement_completion_audit import _obligations
    requirements = {"server_state_changes": [
        "Mining increases owned inventory; rejected requests change nothing. "
        "Selling reduces inventory and increases earned currency; "
        "rejected requests change neither displayed balance."
    ]}
    effects = _obligations(requirements)
    assert len(effects) == 3, effects
    assert "rejected requests" in effects[0]["behavior"]
    assert "rejected requests" in effects[2]["behavior"]


def test_unplanned_original_action_blocks_without_source_hallucination(tmp_path):
    proposal = fixture(tmp_path)
    class Reporter:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Post-generation"):
                raise ValueError("finish_reason=length")
            if kwargs["prompt"].startswith("Find user-requested"):
                assert "complete_server_sources" not in kwargs["prompt"]
                return {"missing_actions": [
                    "A requested physical resource deposit must exist in the world"
                ]}
            assert kwargs["prompt"].startswith("Audit exactly ONE")
            if "Successful trade reduces" in kwargs["prompt"]:
                return {"verdict": "implemented", "file": TRADE,
                        "quote": "stock.resources -= 1"}
            return {"verdict": "implemented", "file": SHIP,
                    "quote": "ship.Sections += 1"}

    report = audit_whole_requirement_completion(proposal, tmp_path, Reporter())
    assert report["status"] == "failed"
    assert not report["fully_covered"]
    assert "original request omitted" in report["reason"]
    assert report["unplanned_actions"]


def test_realistic_multipart_requirement_recovers_compact_first_effect(tmp_path):
    """Regression for a semicolon-joined extract/sell/assemble contract."""
    import json
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "After accepted world-resource extraction, the player's owned inventory "
        "increases by the resource quantity actually extracted from the validated "
        "world deposit; rejected requests change nothing. After a successful "
        "trade, the player's owned resource inventory decreases by the sold "
        "quantity and the earned money balance increases by the server-priced "
        "payout; rejected requests change neither displayed balance. "
        "The player's owned spaceship now has one additional ship section "
        "attached, and the server-owned ship assembly state is persisted "
        "as a completed piece-by-piece construction."
    ]
    assert len(_obligations(req)) == 5

    class TinyModel:
        def __init__(self):
            self.calls = []
            self.first_invalid = True

        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.calls.append(prompt)
            assert not prompt.startswith("Post-generation")
            assert len(prompt) < 15000, "Reviewer still received a giant prompt"
            if prompt.startswith("Find user-requested"):
                assert "complete_server_sources" not in prompt
                return {"missing_actions": []}
            assert prompt.startswith(("Audit exactly ONE", "Recheck ONE"))
            data = json.loads(prompt[prompt.index('{"effect":'):])
            catalog = data["owner_catalog"]
            if self.first_invalid:
                self.first_invalid = False
                return {}
            target = SHIP if "ship section" in data["effect"] else TRADE
            # The model returns ONLY a physical source coordinate, never code.
            return {
                "verdict": "missing" if "world-resource extraction"
                            in data["effect"] else "implemented",
                "file_id": catalog[target],
                "line": 3,
                "issue": "The authoritative resource source has no mining transaction",
                "repair": "Implement validated deposit extraction and inventory credit",
            }

    model = TinyModel()
    report = audit_whole_requirement_completion(proposal, tmp_path, model)
    # The tiny model recovered a malformed reply, but incorrectly used the
    # same real code line to assert multiple unrelated successful effects.
    # This must be rejected, not counted as proof of a working game.
    assert not report["fully_covered"], report
    assert "shared evidence" in report["reason"], report
    assert any(r.get("status") == "invalid_evidence"
               for r in report["recovery"])
    assert len(model.calls) == 7  # five effects + retry + scope review


def test_fabricated_batch_citation_recovers_only_that_effect(tmp_path):
    """A valid cardinality batch with one fake quote must not fail unscoped."""
    proposal = fixture(tmp_path)
    class BadCitationThenCompact:
        def __init__(self):
            self.calls = []
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.calls.append(prompt)
            if prompt.startswith("Post-generation"):
                answer = response(first="implemented")
                answer["checks"][1]["quote"] = "fictionalCoins.Value += 999"
                return answer
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert prompt.startswith("Audit exactly ONE")
            assert "increases earned currency" in prompt
            return {
                "verdict": "missing", "file": TRADE,
                "quote": "stock.resources -= 1",
                "issue": "The server never credits the earned currency",
                "repair": "Credit the authoritative wallet after validated resource debit",
            }
    model = BadCitationThenCompact()
    report = audit_whole_requirement_completion(proposal, tmp_path, model)
    assert report["fully_covered"], report
    assert report["status"] == "issues_found"
    assert len(report["findings"]) == 1
    assert len(report["checks"]) == 3
    assert [r["effect_id"] for r in report["recovery"]
            if r.get("stage") == "single_effect" and r.get("status") == "recovered"] == [
                "effect-02"
            ]


def test_false_positive_same_source_proves_two_different_acts_is_blocked(tmp_path):
    proposal = fixture(tmp_path)
    output = response(first="implemented")
    # Both 'resource decrease' and 'money increase' wrongly cite only debit.
    output["checks"][1]["quote"] = output["checks"][0]["quote"]
    output["checks"][1]["file"] = output["checks"][0]["file"]
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(output),
    )
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert "shared evidence" in report["reason"]


def test_model_cannot_discard_original_effect_as_out_of_scope(tmp_path):
    proposal = fixture(tmp_path)
    output = response()
    output["checks"][0].update({
        "verdict": "out_of_scope",
        "file": "",
        "quote": "",
        "issue": "The model thinks original requested mining is unrelated",
        "repair": "",
    })
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(output),
    )
    assert not report["fully_covered"]
    assert "scope conflict" in report["reason"]
