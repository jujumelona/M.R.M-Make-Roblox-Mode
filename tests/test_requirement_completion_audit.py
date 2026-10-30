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
                items[1]["quote"] = "stock.money += 1"
                return {"checks": [items[0], items[0], *items[1:]],
                        "extra_missing": []}
            if self.initial == "no_extras":
                return {"checks": [], "extra_missing": None}
            return {"checks": response()["checks"][:1], "extra_missing": []}
        if prompt.startswith("Find user-requested"):
            return {"extra_missing": []}
        assert prompt.startswith("Audit exactly ONE"), prompt[:120]
        assert "current_owner_sources" in prompt
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
    (tmp_path / TRADE).write_text(
        (tmp_path / TRADE).read_text(encoding="utf-8")
        + "\nstock.money += 1\n",
        encoding="utf-8",
    )
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
    (tmp_path / SHIP).write_text(
        (tmp_path / SHIP).read_text(encoding="utf-8")
        + "\ncoins.Value += 1\n",
        encoding="utf-8",
    )
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
            catalog = {
                row["path"]: int(index)
                for index, row in data["current_owner_sources"].items()
            }
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
    assert ("shared evidence" in report["reason"]
            or "currency state writer" in report["reason"]), report
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
    (tmp_path / TRADE).write_text(
        (tmp_path / TRADE).read_text(encoding="utf-8")
        + "\nstock.money += 1\n",
        encoding="utf-8",
    )
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


def test_lower_ranked_server_owner_is_checked_before_missing_verdict(tmp_path):
    """An effect implemented by owner #3 cannot be declared missing by #1/#2."""
    import json
    from types import SimpleNamespace

    proposal = fixture(tmp_path)
    extra = "src/server/LowRankOtherServer.luau"
    source = ("--!strict\nlocal function supporting()\n"
              "    local unrelated = 1\n"
              "    unrelated += 1\nend\n" + ("-- padding\n" * 30)
              + "actualProgress.special_state = true\n")
    dest = tmp_path / extra
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")
    proposal.modules.append(SimpleNamespace(name="LowRankOther", file_path=extra))
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["owner_files"] = [SHIP, TRADE, extra]
    req["server_state_changes"] = [
        "Game records the custom player ship state mutation"
    ]
    assert len(_obligations(req)) == 1

    class OwnerWindowModel:
        def __init__(self):
            self.scopes = []
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Post-generation"):
                raise ValueError("finish_reason=length")
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert prompt.startswith("Audit exactly ONE"), prompt[:110]
            data = json.loads(prompt[prompt.index('{"effect":'):])
            scope = data["current_owner_sources"]
            paths = {v["path"]: int(k) for k,v in scope.items()}
            self.scopes.append(list(paths))
            if extra not in paths:
                selected = next(iter(paths))
                return {
                    "verdict": "missing", "file_id": paths[selected],
                    "line": 3,
                    "issue": "No authoritative ship state writer in this window",
                    "repair": "Inspect the remaining owner and validate its state mutation",
                }
            line = source.splitlines().index(
                "actualProgress.special_state = true"
            ) + 1
            return {"verdict": "implemented", "file_id": paths[extra],
                    "line": line}
    model = OwnerWindowModel()
    report = audit_whole_requirement_completion(proposal, tmp_path, model)
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert len(model.scopes) == 2
    assert any(extra in paths for paths in model.scopes)


def test_all_owner_code_larger_than_old_budget_is_scoped_not_rejected(tmp_path):
    """Only the AI request is bounded; large total project source is allowed."""
    import json
    proposal = fixture(tmp_path)
    for path in (SHIP, TRADE):
        source = (tmp_path / path).read_text(encoding="utf-8")
        (tmp_path / path).write_text(
            source + ("-- many independent source comments\n" * 1600),
            encoding="utf-8",
        )
    assert sum(len((tmp_path / path).read_text())
               for path in (SHIP, TRADE)) > 72000

    class TinyStructured:
        def complete_json(self, **kwargs):
            p = kwargs["prompt"]
            if p.startswith("Post-generation"):
                raise ValueError("finish_reason=length")
            if p.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert p.startswith("Audit exactly ONE"), p[:120]
            data = json.loads(p[p.index('{"effect":'):])
            paths = {v["path"]: int(k)
                     for k,v in data["current_owner_sources"].items()}
            if "Purchasing" in data["effect"]:
                return {"verdict": "implemented", "file_id": paths[SHIP],
                        "line": 3}
            if "increases earned currency" in data["effect"]:
                return {"verdict": "missing", "file_id": paths[TRADE],
                        "line": 3,
                        "issue": "Currency credit is not implemented",
                        "repair": "Credit the authoritative balance"}
            return {"verdict": "implemented", "file_id": paths[TRADE],
                    "line": 3}
    report = audit_whole_requirement_completion(
        proposal, tmp_path, TinyStructured(),
    )
    assert report["fully_covered"], report
    assert report["status"] == "issues_found", report
    assert "72" not in report["reason"]


def test_numbered_source_must_include_the_cited_line(tmp_path):
    from roblox_mod_ai.requirement_completion_audit import (
        _normalize_single_effect_answer,
    )
    source = (tmp_path / TRADE).read_text(encoding="utf-8")
    valid = {"verdict": "implemented", "file_id": 0, "line": 3}
    assert _normalize_single_effect_answer(
        valid, [TRADE], {TRADE: source},
        {TRADE: "1: --!strict\n2: local function sale()"},
    ) is None
    assert _normalize_single_effect_answer(
        valid, [TRADE], {TRADE: source},
        {TRADE: "3:     stock.resources -= 1"},
    ) is not None


def test_comment_before_real_source_quote_does_not_hide_real_evidence(tmp_path):
    from roblox_mod_ai.requirement_completion_audit import _real_source_quote
    file = tmp_path / TRADE
    file.write_text(
        "-- stock.resources -= 1\n" + file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert _real_source_quote(
        tmp_path, TRADE, "stock.resources -= 1"
    ) == 4


def test_currency_reward_cannot_be_approved_by_alien_health_update(tmp_path):
    """The actual failed proposal promised damage AND a currency reward."""
    from roblox_mod_ai.requirement_completion_audit import (
        _has_currency_state_write,
    )
    currency_effect = (
        "The player gains the resulting damage amount as currency"
    )
    combat_only = (
        'target:SetAttribute("RMMAlienHealth", remaining)\n'
        "progress.planetOwned = true\n"
        "player:SetAttribute('RMMPlanetOwned', true)\n"
    )
    assert not _has_currency_state_write(currency_effect, combat_only)
    assert _has_currency_state_write(
        currency_effect,
        combat_only + "coins.Value = balance + payout\n",
    )
    assert _has_currency_state_write(
        "Buyer currency decreases by the server price",
        "inventory.resources -= 1\nwallet:Debit(serverPrice)\n",
    )


def test_planned_currency_reward_requires_a_real_server_writer(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "Alien entity health decreases by player damage",
        "Player gains resulting damage as currency",
    ]
    # This model lies about the second, unrelated effect, but the host can
    # establish that the reviewed source never writes a currency balance.
    class FabricatedReward:
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Post-generation"):
                return {"checks": [
                    {"id": "effect-01", "verdict": "implemented",
                     "file": TRADE, "quote": "stock.resources -= 1",
                     "issue": "none", "repair": "none"},
                    {"id": "effect-02", "verdict": "implemented",
                     "file": SHIP, "quote": "ship.Sections += 1",
                     "issue": "none", "repair": "none"},
                ], "extra_missing": []}
            raise AssertionError("Unexpected model call")
    report = audit_whole_requirement_completion(
        proposal, tmp_path, FabricatedReward()
    )
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert "currency state writer" in report["reason"]


def test_one_physical_line_can_contain_two_independent_state_writes(tmp_path):
    from roblox_mod_ai.requirement_completion_audit import _distinct_state_writes
    assert _distinct_state_writes(
        "stock.resources -= 1; stock.money += 1"
    ) == 2
    assert _distinct_state_writes(
        "stock.resources -= 1; stock.resources -= 1"
    ) == 1
    assert _distinct_state_writes(
        "local balance = 10; local duration = 4"
    ) == 0
    assert _distinct_state_writes(
        "-- stock.money += 1; stock.resources -= 1"
    ) == 0


def test_combined_resource_debit_and_wallet_credit_is_not_false_rejected(tmp_path):
    proposal = fixture(tmp_path)
    requirement = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    requirement["server_state_changes"] = [
        "Successful trade reduces owned resources",
        "Successful sale increases earned currency",
    ]
    line = "stock.resources -= 1; stock.money += 1"
    (tmp_path / TRADE).write_text(
        "--!strict\nlocal function sale()\n    " + line + "\nend\n",
        encoding="utf-8",
    )
    class SameLineModel:
        def complete_json(self, **kwargs):
            return {"checks": [
                {"id": "effect-01", "verdict": "implemented",
                 "file": TRADE, "quote": line, "issue": "none", "repair": "none"},
                {"id": "effect-02", "verdict": "implemented",
                 "file": TRADE, "quote": line, "issue": "none", "repair": "none"},
            ], "extra_missing": []}
    report = audit_whole_requirement_completion(
        proposal, tmp_path, SameLineModel(),
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report


def test_planned_spaceflight_cannot_pass_from_duration_arithmetic(tmp_path):
    from roblox_mod_ai.requirement_completion_audit import (
        _is_effectful_source_line, _normalize_single_effect_answer,
    )
    path = SHIP
    source = (
        "--!strict\n"
        "local duration = math.max(3, 7 - 0.4 * rank)\n"
        "local craft = workspace:FindFirstChild('Ship')\n"
        "craft:PivotTo(destination)\n"
    )
    assert not _is_effectful_source_line(source, 2)
    assert not _is_effectful_source_line(source, 3)
    assert _is_effectful_source_line(source, 4)
    assert _normalize_single_effect_answer(
        {"verdict": "implemented", "file_id": 0, "line": 2},
        [path], {path: source},
        {path: "2: local duration = math.max(3, 7 - 0.4 * rank)"},
    ) is None
    assert _normalize_single_effect_answer(
        {"verdict": "implemented", "file_id": 0, "line": 4},
        [path], {path: source},
        {path: "4: craft:PivotTo(destination)"},
    ) is not None


def test_luau_inline_and_multiline_comments_never_certify_wallet_writes():
    from roblox_mod_ai.requirement_completion_audit import (
        _mask_luau_comments, _has_currency_state_write,
    )
    code = (
        'local text = "-- this string is not a comment"\n'
        '-- coins.Value += 100\n'
        '--[=[\n'
        'coins.Value += 200\n'
        ']=]\n'
        'target:SetAttribute("RMMAlienHealth", 0) -- coins.Value += 300\n'
    )
    masked = _mask_luau_comments(code)
    assert masked.count("\n") == code.count("\n")
    assert len(masked) == len(code)
    assert "coins.Value" not in masked
    effect = "The player gains earned currency"
    assert not _has_currency_state_write(effect, code)
    assert _has_currency_state_write(
        effect, code + "\ncoins.Value += 1\n"
    )


def test_comment_only_quote_cannot_prove_mutation_with_long_comment(tmp_path):
    from roblox_mod_ai.requirement_completion_audit import _real_source_quote
    path = tmp_path / TRADE
    path.write_text(
        '--[=[\n'
        'stock.money += 9\n'
        ']=]\n'
        '-- stock.money += 9\n'
        'local x = 1 -- stock.money += 9\n',
        encoding="utf-8",
    )
    assert _real_source_quote(tmp_path, TRADE, "stock.money += 9") == 0
    with path.open("a", encoding="utf-8") as handle:
        handle.write("stock.money += 9\n")
    assert _real_source_quote(tmp_path, TRADE, "stock.money += 9") == 6


def test_host_combat_compiler_credits_actual_damage_only_after_prevalidation():
    from roblox_mod_ai.host_verified_typed_effects import (
        _inject_damage_currency_reward, _RANKED_DAMAGE,
        _COLONY_DAMAGE, _DAMAGE,
    )
    for base in (_RANKED_DAMAGE, _COLONY_DAMAGE, _DAMAGE):
        output = _inject_damage_currency_reward(base)
        assert output.count('target:SetAttribute("RMMAlienHealth", remaining)') == 1
        assert output.count("coins.Value += actualReward") == 1
        guard = output.index('reason = "wallet_capacity"')
        state = output.index('target:SetAttribute("RMMAlienHealth", remaining)')
        credit = output.index("coins.Value += actualReward")
        assert guard < state < credit
        assert "local actualReward = hp - remaining" in output
        assert "2147483647 - actualReward" in output


def test_damage_payout_requires_explicit_owner_requirement():
    from types import SimpleNamespace
    from roblox_mod_ai.host_verified_typed_effects import (
        _requires_damage_currency_reward,
    )
    module = SimpleNamespace(
        name="GenericDamageServer",
        file_path="src/server/GenericDamageServer.luau",
    )
    requirement = {
        "id": "req-x",
        "owner_files": [module.file_path],
        "server_state_changes": [
            "The alien entity's health decreases by player damage, "
            "and the player gains the resulting damage amount as currency"
        ],
    }
    proposal = SimpleNamespace(game_design={
        "detailed_implementation_plan": {"required_functions": [requirement]}
    })
    assert _requires_damage_currency_reward(module, proposal)
    requirement["server_state_changes"] = [
        "The alien entity's health decreases from player damage"
    ]
    assert not _requires_damage_currency_reward(module, proposal)
    requirement["server_state_changes"] = [
        "Alien takes damage. Player earns currency by selling resources."
    ]
    assert not _requires_damage_currency_reward(module, proposal)
    requirement["owner_files"] = ["src/server/UnrelatedServer.luau"]
    requirement["server_state_changes"] = [
        "The alien takes damage and the player gains money"
    ]
    assert not _requires_damage_currency_reward(module, proposal)


def test_currency_response_field_is_not_wallet_mutation():
    from roblox_mod_ai.requirement_completion_audit import (
        _has_currency_state_write,
    )
    effect = "Player gains currency after attack"
    assert not _has_currency_state_write(
        effect,
        'local balance = 30\n'
        'return {success = true, coins = coins.Value, earned = payout}\n',
    )
    assert not _has_currency_state_write(
        effect,
        'balance = balance + payout\n'
        'return {success = true, money = balance}\n',
    )
    assert _has_currency_state_write(
        effect, 'profile.money += payout\n',
    )
    assert _has_currency_state_write(
        effect, 'state["Money"] += payout\n',
    )
    assert _has_currency_state_write(
        effect, 'coins.Value = balance + payout\n',
    )


def test_string_containing_fake_currency_code_is_not_executed():
    from roblox_mod_ai.requirement_completion_audit import (
        _has_currency_state_write, _mask_noncode_luau_strings,
        _is_effectful_source_line,
    )
    effect = "Player gains earned currency"
    source = (
        'print("coins.Value += 999")\n'
        'warn([[stock.money += 999]])\n'
        'local message = "coins.Value = 300"\n'
        'target:SetAttribute("AlienHealth", remaining)\n'
    )
    assert not _has_currency_state_write(effect, source)
    assert not _is_effectful_source_line(source, 1)
    assert _is_effectful_source_line(source, 4)
    original = 'profile["Money"] += 9\n'
    masked = _mask_noncode_luau_strings(original)
    assert len(masked) == len(original)
    assert _has_currency_state_write(effect, original)
    non_mutation = 'print(profile["coins.Value += 999"])\n'
    assert not _has_currency_state_write(effect, non_mutation)
    assert not _is_effectful_source_line(non_mutation, 1)
