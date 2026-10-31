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
    proposal = fixture(tmp_path)
    (tmp_path / TRADE).write_text(
        (tmp_path / TRADE).read_text(encoding="utf-8")
        + "\nstock.money += 1\n",
        encoding="utf-8",
    )
    router = RecoveringRouter(initial="duplicates")
    report = audit_whole_requirement_completion(proposal, tmp_path, router)
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
    import json
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server reduces owned resources",
        "The server increases earned currency",
        "The server attaches an owned section",
        "The server persists owned section state",
    ]

    class BoundedModel:
        def __init__(self):
            self.prompts = []

        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.prompts.append(prompt)
            assert not prompt.startswith("Post-generation")
            assert not prompt.startswith(("Audit exactly ONE", "Recheck ONE"))
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert prompt.startswith("Check ONE promised")
            obj = json.loads(prompt[prompt.index('{"effect":'):])
            # A small model misuses ONE real state write for every behavior.
            # Such spurious repeated proof must still be blocked.
            return {
                "choice": next(
                    x["id"] for x in obj["candidates"]
                    if x["statement"] == "ship.Sections += 1"
                )
            }

    router = BoundedModel()
    report = audit_whole_requirement_completion(proposal, tmp_path, router)
    assert not report["fully_covered"], report
    assert "cannot prove" in report["reason"], report
    assert report.get("unverified_effects"), report
    assert any(x["stage"] == "batch_skipped" for x in report["recovery"])
    assert sum(x.startswith("Check ONE promised") for x in router.prompts) == 4


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
    """Complex prose becomes bounded host-source selections, not large JSON."""
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
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.calls.append(prompt)
            assert not prompt.startswith("Post-generation")
            assert len(prompt) < 15000
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert prompt.startswith("Check ONE promised")
            data = json.loads(prompt[prompt.index('{"effect":'):])
            # A repeated, unrelated implementation line cannot prove every
            # distinct effect just because the 9B model asserts it.
            return {"choice": next(
                row["id"] for row in data["candidates"]
                if row["statement"] == "ship.Sections += 1"
            )}
    model = TinyModel()
    report = audit_whole_requirement_completion(proposal, tmp_path, model)
    assert not report["fully_covered"], report
    assert "cannot prove" in report["reason"], report
    assert report.get("unverified_effects"), report
    assert len([p for p in model.calls if p.startswith("Check ONE promised")]) == 5


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
    fixture(tmp_path)
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
    fixture(tmp_path)
    from roblox_mod_ai.requirement_completion_audit import _real_source_quote
    file = tmp_path / TRADE
    file.write_text(
        "-- stock.resources -= 1\n" + file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert _real_source_quote(
        tmp_path, TRADE, "stock.resources -= 1"
    ) == 4


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


def test_comment_only_quote_cannot_prove_mutation_with_long_comment(tmp_path):
    (tmp_path / TRADE).parent.mkdir(parents=True, exist_ok=True)
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





def test_seven_effects_malformed_ai_evidence_uses_host_owned_witness_ids(tmp_path):
    """No game/genre special case: every server effect is a real source write."""
    import json
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    fields = tuple("abcdefgh")
    req["server_state_changes"] = [
        "The server increments state." + field + " by one" for field in fields[:7]
    ]
    path = tmp_path / SHIP
    path.write_text(
        "--!strict\nlocal function perform()\n"
        + "".join("    state." + x + " += 1\n" for x in fields)
        + "end\n", encoding="utf-8",
    )

    class SmallJsonModel:
        def __init__(self):
            self.choices = []
            self.invalid_count = 0
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            if prompt.startswith(("Audit exactly ONE", "Recheck ONE")):
                self.invalid_count += 1
                return {"verdict": "implemented"}  # old broken evidence format
            if prompt.startswith("Check ONE promised"):
                obj = json.loads(prompt[prompt.index('{"effect":'):])
                field = obj["effect"].split("state.")[1].split()[0]
                choices = [
                    row for row in obj["candidates"]
                    if "state." + field + " += 1" in row["statement"]
                ]
                assert len(choices) == 1
                self.choices.append(choices[0]["id"])
                return {"choice": choices[0]["id"]}
            raise AssertionError("Unexpected model prompt: " + prompt[:80])

    model = SmallJsonModel()
    report = audit_whole_requirement_completion(proposal, tmp_path, model)
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert len(report["checks"]) == 7
    assert all(row["quote"].startswith("state.") for row in report["checks"])
    assert len(model.choices) == 7
    assert model.invalid_count == 0
    assert sum(row.get("status") == "source_witness_selected"
               for row in report.get("recovery", [])) == 7


def test_seven_unparseable_effects_are_all_reported_not_silently_approved(tmp_path):
    """Independent effects survive model errors with host-owned stable IDs."""
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server changes state field " + str(i) for i in range(7)
    ]

    class NeverAnswers:
        calls = 0
        def complete_json(self, **kwargs):
            self.calls += 1
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            return {"not_the_schema": True}

    model = NeverAnswers()
    report = audit_whole_requirement_completion(proposal, tmp_path, model)
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert len(report["unverified_effects"]) == 7, report
    assert {row["effect_id"] for row in report["unverified_effects"]} == {
        "effect-%02d" % i for i in range(1, 8)
    }
    assert "cannot prove 7 independent effects" in report["reason"]
    assert model.calls >= 7  # one bounded structured call per effect, no old schema


def test_host_witness_zero_is_unverified_not_a_fabricated_repair(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server decrements a distinct persistent player metric"
    ]

    class RejectsProof:
        def complete_json(self, **kwargs):
            p = kwargs["prompt"]
            if p.startswith("Post-generation"):
                return {"checks": [], "extra_missing": []}
            if p.startswith(("Audit exactly ONE", "Recheck ONE")):
                return {}
            if p.startswith("Check ONE promised"):
                return {"choice": 0}
            raise AssertionError(p[:80])

    report = audit_whole_requirement_completion(
        proposal, tmp_path, RejectsProof(),
    )
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert len(report["unverified_effects"]) == 1
    assert report.get("findings", []) == []
    assert any(r.get("reason") == "no_conclusive_source_witness"
               for r in report["recovery"])


def test_source_witnesses_never_include_comment_or_arithmetic_only_evidence():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses
    source = (
        "-- state.resource += 500\n"
        "local x = math.max(0, 2)\n"
        'print("state.resource += 999")\n'
        "state.resource += 1\n"
    )
    path = "src/server/SomeOwner.luau"
    found = _host_effect_witnesses(
        "Increment resource state", {path: source}, [],
    )
    assert len(found) == 1
    assert found[0]["file"] == path
    assert found[0]["line"] == 4
    assert found[0]["quote"] == "state.resource += 1"



def test_persistent_owner_write_survives_decorative_statement_noise():
    """Rank verified GetState-derived fields, never a named game mechanic."""
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses
    path = "src/server/DynamicOwner.luau"
    source = (
        'local profile = services.PlayerDataManager.GetState(player, "GenericState")\n'
        + "".join("widget.Property%d = %d\n" % (i, i) for i in range(80))
        + "profile.savedCounter += 1\n"
    )
    witnesses = _host_effect_witnesses(
        "The authoritative player state is persisted after success",
        {path: source}, [], limit=24,
    )
    assert any(row["quote"] == "profile.savedCounter += 1"
               for row in witnesses), witnesses


def test_source_owner_allocation_does_not_starve_other_services():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses
    sources = {
        "src/server/A.luau": "".join(
            "prop.Attribute%d = %d\n" % (i, i) for i in range(90)
        ),
        "src/server/B.luau": "state.second += 1\n",
        "src/server/C.luau": "state.third += 1\n",
    }
    witnesses = _host_effect_witnesses(
        "The server processes the requested state transition",
        sources, [], limit=24,
    )
    assert {row["file"] for row in witnesses} == set(sources)



def test_production_host_witness_mode_also_applies_to_short_requirements(tmp_path):
    """Production never uses the brittle all-effects/file_id/quote AI schema."""
    import json
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server decrements the first saved resource",
        "The server increments the second saved property",
    ]
    (tmp_path / TRADE).write_text(
        SOURCE_TRADE + "stock.property += 1\n", encoding="utf-8",
    )

    class OneIntegerOnly:
        def __init__(self):
            self.prompts = []
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            self.prompts.append(prompt)
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert prompt.startswith("Check ONE promised"), prompt[:90]
            data = json.loads(prompt[prompt.index('{"effect":'):])
            needle = (
                "stock.resources -= 1" if "first" in data["effect"]
                else "stock.property += 1"
            )
            choices = [row["id"] for row in data["candidates"]
                       if row["statement"] == needle]
            assert len(choices) == 1
            return {"choice": choices[0]}

    router = OneIntegerOnly()
    report = audit_whole_requirement_completion(
        proposal, tmp_path, router, host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert len(report["checks"]) == 2
    assert len([x for x in router.prompts
                if x.startswith("Check ONE promised")]) == 2
    assert not any(p.startswith(("Post-generation", "Audit exactly ONE"))
                   for p in router.prompts)


def test_plain_integer_recovers_small_model_json_failure(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server updates one authoritative player state field"
    ]

    class BrokenJsonButValidPlain:
        def __init__(self):
            self.plain_calls = 0
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Check ONE promised"):
                raise ValueError("json_schema completion invalid")
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            raise AssertionError(kwargs["prompt"][:50])
        def complete(self, **kwargs):
            self.plain_calls += 1
            assert kwargs["max_tokens"] <= 12
            assert "Return" not in kwargs["prompt"]
            return "1"

    router = BrokenJsonButValidPlain()
    report = audit_whole_requirement_completion(
        proposal, tmp_path, router, host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert router.plain_calls == 1
    assert any(x.get("recovered_from") == "plain_integer"
               for x in report.get("recovery", []))


def test_plain_integer_with_multiple_choices_never_passes(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server updates one authoritative player state field"
    ]

    class AmbiguousPlain:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            return {"invalid": True}
        def complete(self, **kwargs):
            return "1 or 2"

    report = audit_whole_requirement_completion(
        proposal, tmp_path, AmbiguousPlain(), host_witness_only=True,
    )
    assert not report["fully_covered"]
    assert report["status"] == "failed"
    assert len(report["unverified_effects"]) == 1
    assert report.get("findings", []) == []


def test_unverified_model_replies_report_all_requirements_in_one_run(tmp_path):
    proposal = fixture(tmp_path)
    first = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    first["server_state_changes"] = [
        "The server persists state for the first feature"
    ]
    second = {
        "id": "req-generic-02",
        "original_request": "Perform a second unrelated requested action",
        "owner_files": [SHIP, TRADE],
        "server_state_changes": [
            "The server persists state for the second feature"
        ],
    }
    proposal.game_design["detailed_implementation_plan"]["required_functions"].append(second)

    class NeverAnswers:
        def __init__(self):
            self.count = 0
        def complete_json(self, **kwargs):
            p = kwargs["prompt"]
            if p.startswith("Find user-requested"):
                return {"missing_actions": []}
            self.count += 1
            return {"malformed": True}

    model = NeverAnswers()
    report = audit_whole_requirement_completion(
        proposal, tmp_path, model, host_witness_only=True,
    )
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert {row["requirement_id"] for row in report["unverified_effects"]} == {
        first["id"], second["id"],
    }
    assert model.count == 2, report
    assert "cannot prove 2 independent effects" in report["reason"]


def test_original_scope_json_failure_can_recover_only_from_exact_plain_none(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["server_state_changes"] = [
        "The server decrements a real persistent resource count"
    ]

    class ScopeFailsJson:
        def __init__(self, text):
            self.text = text
            self.plain_calls = 0
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Check ONE promised"):
                return {"choice": 1}
            raise ValueError("json_schema invalid")
        def complete(self, **kwargs):
            self.plain_calls += 1
            return self.text

    approved = ScopeFailsJson("NONE")
    report = audit_whole_requirement_completion(
        proposal, tmp_path, approved, host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert approved.plain_calls == 1
    assert any(row.get("status") == "recovered_plain_none"
               for row in report["recovery"])

    omitted = ScopeFailsJson(
        "MISSING: An additional server-owned state change from the original request"
    )
    other = audit_whole_requirement_completion(
        proposal, tmp_path, omitted, host_witness_only=True,
    )
    assert other["status"] == "failed", other
    assert other["unplanned_actions"], other
    assert "original request omitted" in other["reason"]

    ambiguous = ScopeFailsJson("NONE, probably, or missing something")
    bad = audit_whole_requirement_completion(
        proposal, tmp_path, ambiguous, host_witness_only=True,
    )
    assert not bad["fully_covered"], bad
    assert bad["status"] == "failed"
    assert "omitted-effect audit" in bad["reason"]



def test_host_witness_keeps_selected_physical_line_when_statements_repeat(tmp_path):
    """Identical writes in different functions are different source evidence."""
    import json

    proposal = fixture(tmp_path)
    requirement = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    requirement["owner_files"] = [SHIP]
    requirement["server_state_changes"] = [
        "The authoritative server increments an owned counter"
    ]
    (tmp_path / SHIP).write_text(
        "local function first()\n"
        "    state.counter += 1\n"
        "end\n"
        "local function second()\n"
        "    state.counter += 1\n"
        "end\n", encoding="utf-8",
    )

    class SelectSecond:
        def complete_json(self, **kwargs):
            p = kwargs["prompt"]
            if p.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert p.startswith("Check ONE promised")
            obj = json.loads(p[p.index('{"effect":'):])
            candidates = obj["candidates"]
            second = [row for row in candidates
                      if "5: state.counter += 1" in row["context"]]
            assert len(second) == 1, candidates
            return {"choice": second[0]["id"]}

    report = audit_whole_requirement_completion(
        proposal, tmp_path, SelectSecond(), host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert report["checks"][0]["line"] == 5, report
    assert report["checks"][0]["quote"] == "state.counter += 1"


def test_host_witness_rejects_tampered_line_even_if_quote_exists(tmp_path, monkeypatch):
    import roblox_mod_ai.requirement_completion_audit as audit

    proposal = fixture(tmp_path)
    requirement = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    requirement["owner_files"] = [SHIP]
    requirement["server_state_changes"] = [
        "The authoritative server increments an owned counter"
    ]
    (tmp_path / SHIP).write_text(
        "state.counter += 1\nstate.other += 1\n", encoding="utf-8",
    )

    monkeypatch.setattr(audit, "_fallback_effect_witness_review",
        lambda *args, **kwargs: ({
            "verdict": "implemented", "file": SHIP,
            "quote": "state.counter += 1", "line": 2,
            "issue": "none", "repair": "none",
        }, {"stage": "host_witness_fallback", "status": "source_witness_selected"}))

    class OnlyScope:
        def complete_json(self, **kwargs):
            return {"missing_actions": []}

    result = audit.audit_whole_requirement_completion(
        proposal, tmp_path, OnlyScope(), host_witness_only=True,
    )
    assert result["status"] == "failed", result
    assert "host witness line/quote mismatch" in result["reason"]


def test_audit_rejects_owner_path_escape_before_reading(tmp_path):
    from types import SimpleNamespace
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["owner_files"] = ["src/server/../../escape.luau"]
    proposal.modules.append(SimpleNamespace(
        name="BadOwner", file_path="src/server/../../escape.luau",
    ))
    (tmp_path / "escape.luau").write_text("state.score += 1\n", encoding="utf-8")

    result = audit_whole_requirement_completion(
        proposal, tmp_path, Router(response()), host_witness_only=True,
    )
    assert result["status"] == "failed", result
    assert "missing complete source ownership" in result["reason"]


def test_audit_rejects_more_owners_than_bounded_witness_capacity():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses
    sources = {
        "src/server/Module%d.luau" % i: "state.counter%d += 1\n" % i
        for i in range(25)
    }
    assert _host_effect_witnesses(
        "Update the requested state", sources, [], limit=24,
    ) == []



def test_one_unverified_effect_does_not_hide_other_confirmed_findings(tmp_path):
    """A failed model reply does not discard already grounded missing effects."""
    proposal = fixture(tmp_path)

    class MixedReview:
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Post-generation"):
                return {"checks": response()["checks"][:2], "extra_missing": []}
            if prompt.startswith(("Audit exactly ONE", "Recheck ONE",
                                  "Check ONE promised")):
                return {"malformed": True}
            raise AssertionError(prompt[:100])

    report = audit_whole_requirement_completion(
        proposal, tmp_path, MixedReview(),
    )
    assert report["status"] == "failed", report
    assert not report["fully_covered"]
    assert [row["effect_id"] for row in report["unverified_effects"]] == [
        "effect-03",
    ], report
    assert len(report["findings"]) == 1, report
    assert report["findings"][0]["requirement_id"] == "req-generic"
    assert "Currency balance" in report["findings"][0]["issue"]



def test_host_scaffold_witness_must_be_inside_authenticated_action_body():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/AnyService.luau"
    source = (
        "local Service = {}\n"
        "local function neverInvoked()\n"
        "    state.fake += 1\n"
        "end\n"
        "function Service.start(services)\n"
        "    Service._services = services\n"
        "end\n"
        "function Service.handleAction(player, services, ...)\n"
        "    if player == nil then return false end\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        '    local profile = services.PlayerDataManager.GetState(player, "Account")\n'
        "    profile.real += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\n"
        "return Service\n"
    )
    witnesses = _host_effect_witnesses("Update owned state", {path: source}, [])
    assert [row["quote"] for row in witnesses] == ["profile.real += 1"]
    assert witnesses[0]["line"] == 12


def test_host_scaffold_scratch_only_body_cannot_attest_a_gameplay_effect():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/AnyService.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        "    local scratch = {}\n"
        "    scratch.score += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\n"
        "return Service\n"
    )
    assert _host_effect_witnesses("Update server state", {path: source}, []) == []


def test_host_scaffold_malformed_body_markers_cannot_prove_gameplay():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/AnyService.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        '    local profile = services.PlayerDataManager.GetState(player, "Account")\n'
        "    profile.real += 1\n"
        "end\nreturn Service\n"
    )
    assert _host_effect_witnesses("Update server state", {path: source}, []) == []



def test_scaffold_cannot_use_scratch_write_beside_real_player_state_write():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/GenericHandler.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        '    local profile = services.PlayerDataManager.GetState(player, "GameState")\n'
        "    local scratch = {}\n"
        "    scratch.fake += 1\n"
        "    profile.actual += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    observed = _host_effect_witnesses("Mutate game state", {path: source}, [])
    assert len(observed) == 1, observed
    assert observed[0]["quote"] == "profile.actual += 1"
    assert observed[0]["line"] == 7


def test_scaffold_rebinding_authenticated_local_to_scratch_removes_proof():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/GenericHandler.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        '    local profile = services.PlayerDataManager.GetState(player, "GameState")\n'
        "    profile.actual += 1\n"
        "    local profile = {}\n"
        "    profile.scratch += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    observed = _host_effect_witnesses("Mutate game state", {path: source}, [])
    assert len(observed) == 1, observed
    assert observed[0]["quote"] == "profile.actual += 1"



def test_markerless_routed_handler_rejects_unused_helper_state_write():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/OldService.luau"
    source = (
        "local Service = {}\n"
        "local function unusedHelper()\n"
        "    fake.value += 1\n"
        "end\n"
        "function Service.handleAction(player, services)\n"
        '    local profile = services.PlayerDataManager.GetState(player, "Account")\n'
        "    profile.value += 1\n"
        "end\n"
        "return Service\n"
    )
    result = _host_effect_witnesses("Update state", {path: source}, [])
    assert len(result) == 1, result
    assert result[0]["quote"] == "profile.value += 1"
    assert result[0]["line"] == 7


def test_markerless_routed_handler_with_only_scratch_write_is_not_proof():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/OldService.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services)\n"
        "    local scratch = {}\n"
        "    scratch.value += 1\n"
        "end\nreturn Service\n"
    )
    assert _host_effect_witnesses("Update state", {path: source}, []) == []



def test_routed_write_after_unconditional_return_is_not_gameplay_evidence():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/AnyService.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        "    return false\n"
        '    local profile = services.PlayerDataManager.GetState(player, "State")\n'
        "    profile.counter += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    assert _host_effect_witnesses("Increment counter", {path: source}, []) == []


def test_routed_conditional_early_return_does_not_hide_later_valid_write():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/AnyService.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        "    if player == nil then\n"
        "        return false\n"
        "    end\n"
        '    local profile = services.PlayerDataManager.GetState(player, "State")\n'
        "    profile.counter += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    found = _host_effect_witnesses("Increment counter", {path: source}, [])
    assert len(found) == 1, found
    assert found[0]["line"] == 8



def test_routed_world_target_alias_may_be_a_real_effect_not_scratch():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/WorldAction.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        '    local actionTarget = workspace:FindFirstChild("OwnedTarget")\n'
        "    if not actionTarget then return false end\n"
        "    actionTarget:Destroy()\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    witnesses = _host_effect_witnesses("Destroy a server-selected world object",
                                      {path: source}, [])
    assert len(witnesses) == 1, witnesses
    assert witnesses[0]["quote"] == "actionTarget:Destroy()"


def test_routed_world_target_rebound_to_unowned_scratch_is_not_proof():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/WorldAction.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        "    local actionTarget = {}\n"
        "    actionTarget.value += 1\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    assert _host_effect_witnesses("World state action", {path: source}, []) == []



def test_compound_upgrade_and_payment_create_two_independent_obligations():
    """One money debit cannot also prove the independent upgraded state."""
    from roblox_mod_ai.requirement_completion_audit import _obligations
    req = {
        "server_state_changes": [
            "The owned machine's performance is upgraded and the owner's "
            "currency is debited by the server-priced cost."
        ],
    }
    obligations = _obligations(req)
    assert len(obligations) == 2, obligations
    assert "performance is upgraded" in obligations[0]["behavior"]
    assert "currency is debited" in obligations[1]["behavior"]


def test_authoritative_profile_aliases_are_all_visible_to_witness_selection():
    """Both direct and aliased GetState writes must survive evidence extraction."""
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses
    path = "src/server/GenericService.luau"
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services)\n"
        "    local manager = services.PlayerDataManager\n"
        "    local owned = manager.GetState(player, 'Resources')\n"
        "    local profile = services.PlayerDataManager.GetState(player, 'Machine')\n"
        "    owned.count -= 1\n"
        "    profile.level += 1\n"
        "end\nreturn Service\n"
    )
    candidates = _host_effect_witnesses(
        "Update authenticated player state", {path: source}, [],
    )
    assert {(row["line"], row["quote"]) for row in candidates} == {
        (6, "owned.count -= 1"),
        (7, "profile.level += 1"),
    }, candidates


def test_repeated_model_choice_is_forced_to_independent_real_lines(tmp_path):
    """A small AI cannot reuse one statement for separate state changes."""
    import json
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["owner_files"] = [SHIP]
    req["server_state_changes"] = [
        "The server updates the first saved counter",
        "The server updates the second saved counter",
    ]
    (tmp_path / SHIP).write_text(
        "local function perform()\n"
        "    state.first += 1\n"
        "    state.second += 1\n"
        "end\n", encoding="utf-8",
    )

    class AlwaysFirst:
        def __init__(self):
            self.candidate_lists = []
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            assert prompt.startswith("Check ONE promised")
            data = json.loads(prompt[prompt.index('{"effect":'):])
            self.candidate_lists.append(data["candidates"])
            return {"choice": 1}

    router = AlwaysFirst()
    report = audit_whole_requirement_completion(
        proposal, tmp_path, router, host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers"
    assert len(report["checks"]) == 2
    assert {(e["file"], e["line"]) for e in report["checks"]} == {
        (SHIP, 2), (SHIP, 3),
    }
    assert len(router.candidate_lists) == 2
    assert len(router.candidate_lists[0]) == 2
    assert len(router.candidate_lists[1]) == 1


def test_one_state_write_cannot_falsely_certify_two_effects(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["owner_files"] = [SHIP]
    req["server_state_changes"] = [
        "The server changes the first authoritative counter",
        "The server changes the second authoritative counter",
    ]
    (tmp_path / SHIP).write_text("state.first += 1\n", encoding="utf-8")

    class FirstOnly:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            return {"choice": 1}

    report = audit_whole_requirement_completion(
        proposal, tmp_path, FirstOnly(), host_witness_only=True,
    )
    assert not report["fully_covered"], report
    assert report["status"] == "failed", report
    assert len(report["unverified_effects"]) == 1
    assert report["unverified_effects"][0]["effect_id"] == "effect-02"
    assert any(row.get("reason") == "no_unused_independent_source_witness"
               for row in report["recovery"])
    assert not report.get("findings")


def test_one_line_with_two_distinct_writes_remains_valid_for_two_effects(tmp_path):
    proposal = fixture(tmp_path)
    req = proposal.game_design["detailed_implementation_plan"]["required_functions"][0]
    req["owner_files"] = [SHIP]
    req["server_state_changes"] = [
        "The first property is reduced",
        "The second property is increased",
    ]
    (tmp_path / SHIP).write_text(
        "state.first -= 1; state.second += 1\n", encoding="utf-8",
    )

    class OneLine:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            return {"choice": 1}

    report = audit_whole_requirement_completion(
        proposal, tmp_path, OneLine(), host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert len(report["checks"]) == 2, report
    assert len({row["line"] for row in report["checks"]}) == 1



def test_routed_action_includes_executed_local_helper_state_changes():
    """Weapon/vehicle upgrades may mutate a verified object in a called helper."""
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/ActionWithHelper.luau"
    source = (
        "local Service = {}\n"
        "local function applyStatus(object, level)\n"
        '    object:SetAttribute("Damage", level + 1)\n'
        '    object:SetAttribute("Speed", level + 2)\n'
        "end\n"
        "local function unusedStatus(object)\n"
        '    object:SetAttribute("Fake", 999)\n'
        "end\n"
        "function Service.handleAction(player, services)\n"
        "    -- RMM_GAMEPLAY_BODY_BEGIN\n"
        "    local item = player.Character\n"
        "    if not item then return false end\n"
        "    applyStatus(item, 2)\n"
        "    -- RMM_GAMEPLAY_BODY_END\n"
        "end\nreturn Service\n"
    )
    found = _host_effect_witnesses("Update owned status", {path: source}, [])
    assert {(row["line"], row["quote"]) for row in found} == {
        (3, 'object:SetAttribute("Damage", level + 1)'),
        (4, 'object:SetAttribute("Speed", level + 2)'),
    }, found


def test_unreachable_helper_not_called_by_action_is_never_a_source_witness():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/ActionWithHelper.luau"
    source = (
        "local Service = {}\n"
        "local function uncalled(object)\n"
        '    object:SetAttribute("Fake", 999)\n'
        "end\n"
        "function Service.handleAction(player, services)\n"
        "    return false\n"
        "end\nreturn Service\n"
    )
    assert _host_effect_witnesses("Update state", {path: source}, []) == []


def test_reachable_helper_scratch_local_mutation_is_not_authored_proof():
    from roblox_mod_ai.requirement_completion_audit import _host_effect_witnesses

    path = "src/server/ActionWithHelper.luau"
    source = (
        "local Service = {}\n"
        "local function doNothing(owner)\n"
        "    local scratch = {}\n"
        "    scratch.fake += 1\n"
        "end\n"
        "function Service.handleAction(player, services)\n"
        "    doNothing(player)\n"
        "end\nreturn Service\n"
    )
    assert _host_effect_witnesses("Update state", {path: source}, []) == []



def test_multiple_independent_fields_with_one_predicate_are_all_obligations():
    from roblox_mod_ai.requirement_completion_audit import _obligations

    req = {
        "server_state_changes": [
            "The owned device's damage multiplier, firing speed, and "
            "capacity are updated and persisted in server-owned data."
        ],
    }
    obligations = _obligations(req)
    assert len(obligations) == 3, obligations
    assert obligations[0]["behavior"] == (
        "The owned device's damage multiplier is updated and persisted in "
        "server-owned data"
    )
    assert obligations[1]["behavior"] == (
        "The owned device's firing speed is updated and persisted in "
        "server-owned data"
    )
    assert obligations[2]["behavior"] == (
        "The owned device's capacity is updated and persisted in "
        "server-owned data"
    )


def test_noun_list_without_shared_effect_verb_is_not_split():
    from roblox_mod_ai.requirement_completion_audit import _obligations
    req = {
        "server_state_changes": [
            "The first, second, and third options are shown in the menu."
        ],
    }
    obligations = _obligations(req)
    assert len(obligations) == 1, obligations


def test_separate_update_and_payment_effects_are_individually_counted():
    from roblox_mod_ai.requirement_completion_audit import _obligations
    req = {
        "server_state_changes": [
            "The first system's strength, speed, and capacity are upgraded "
            "and persisted. The player's balance is debited by the price."
        ],
    }
    effects = _obligations(req)
    assert len(effects) == 4, effects
    assert sum("balance" in row["behavior"] for row in effects) == 1
