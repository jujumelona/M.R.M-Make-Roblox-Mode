"""33rd failure: architect completed, but producer/source gate aborted in 90ms.

The new contract loop returns failed module + exact source facet to the small
model at planning time, retries no more than twice and passes only a freshly
rechecked source design. It never mutates the original user request.
"""
import pytest

from roblox_mod_ai.authority_architecture_repair import (
    replan_unproven_authority, AuthorityArchitectureExhausted,
)
from test_log32_model_authority import _log32_design


def _design():
    plan, scope = _log32_design()
    design = dict(plan.game_design["dynamic_design"])
    design["modules"] = list(plan.modules)
    design["module_facets"] = {
        "dyn_colonize": ["intent-colony"],
        "dyn_ship": ["intent-upgrade"],
        "dyn_stateless": ["intent-beacon"],
    }
    return design


def _missing(design, _base, _request):
    # Test the same genuine contract checker that found the missing owner
    # in the original log32/33 plan, without requiring a live GGUF process.
    from roblox_mod_ai.model_action_authority import unproven_model_actions
    from types import SimpleNamespace
    proposal = SimpleNamespace(
        modules=design["modules"], game_design={"dynamic_design": design})
    scope = {"modules": [
        {"name": m.name, "strategy": "bounded_typed_server_action"}
        for m in proposal.modules]}
    return unproven_model_actions(proposal, scope)


def test_log33_repair_in_same_run_uses_scoped_feedback_not_new_user_request():
    first = _design()
    user_request = "build a game involving owned spacecraft upgrades and colonies"
    research = {}
    turns = []

    def redesign():
        feedback = research["_authority_feedback"]
        assert {tuple(row["source_facet_ids"]) for row in feedback} == {
            ("intent-colony",), ("intent-upgrade",)}
        assert all("required" not in row or row["required"] for row in feedback)
        assert all("original_server_behavior" in row for row in feedback)
        turns.append(feedback)
        revised = _design()
        for row in revised["modules"]:
            if row.name == "ColonizePlanet77D3DB2Server":
                row.description = "Mark a newly discovered unclaimed location"
            elif row.name == "ShipPerformanceUpgrade213E1D3Server":
                row.description = "Update a cosmetic ship color"
        return revised

    result = replan_unproven_authority(
        first, existing_modules=[], requested_prompt=user_request,
        research=research, redesign=redesign, inspect=_missing)
    assert result["modules"][0].description.startswith("Mark")
    assert len(turns) == 1
    assert [r["passed"] for r in research["authority_replan_attempts"]] == [
        False, True]
    assert "_authority_feedback" not in research
    assert user_request == "build a game involving owned spacecraft upgrades and colonies"


def test_log33_no_unsupported_design_can_be_relabelled_success_after_retries():
    research = {}
    originals = _design()
    count = 0
    def unchanged():
        nonlocal count
        count += 1
        return _design()
    with pytest.raises(AuthorityArchitectureExhausted,
                       match="UNPROVEN_MODEL_ACTION_AUTHORITY"):
        replan_unproven_authority(
            originals, existing_modules=[],
            requested_prompt="Do not omit ship or colonization",
            research=research, redesign=unchanged, max_repairs=2,
            inspect=_missing)
    assert count == 2
    assert len(research["authority_replan_attempts"]) == 3
    assert all(not x["passed"] for x in research["authority_replan_attempts"])
    assert "_authority_feedback" not in research


def test_log33_valid_actions_do_not_call_model_again():
    research = {}
    source = _design()
    calls = []
    result = replan_unproven_authority(
        source, existing_modules=[], requested_prompt="A verified game",
        research=research,
        redesign=lambda: calls.append(True),
        inspect=lambda _d, _m, _p: [],
    )
    assert result is source
    assert not calls
    assert research["authority_replan_attempts"][0]["passed"] is True


def test_log33_failed_redesign_cannot_leak_authority_feedback():
    research = {}
    def fails():
        raise RuntimeError("local planner unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        replan_unproven_authority(
            _design(), existing_modules=[], requested_prompt="Build colony",
            research=research, redesign=fails, inspect=_missing)
    assert "_authority_feedback" not in research


def test_log33_replan_budget_is_bounded():
    with pytest.raises(ValueError, match="retry budget"):
        replan_unproven_authority(
            _design(), existing_modules=[], requested_prompt="x",
            research={}, redesign=lambda: _design(), max_repairs=999,
            inspect=_missing)
