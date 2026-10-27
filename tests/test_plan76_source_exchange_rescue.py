"""Uploaded run: planner repeatedly proposed a vague currency change as trade.

The host must preserve exact source IDs and accepted sibling mechanics,
require TWO real state effects, and never certify a no-op or imaginary P2P.
"""
import pytest

from roblox_mod_ai.atomic_action_quotes import eligible_atomic_action_spans, SourceActionBindingError
from roblox_mod_ai.source_owned_microplanning import (
    complete_source_owned_actions, _repair_incomplete_owned_exchange,
    _coverage_issues,
)

SOURCE = "자원파밍 거래"


def inputs():
    spans = eligible_atomic_action_spans(SOURCE)
    mine = next(row for row in spans if row["quote"] == "자원파밍")
    trade = next(row for row in spans if row["quote"] == "거래")
    return [
        {"source_id": mine["id"],
         "action": "The server mines resource ore and credits the collected resources to owned inventory."},
        {"source_id": trade["id"],
         "action": "Server changes the player's currency balance to complete a trade."},
    ]


class TinyPlanner:
    def __init__(self, good=True):
        self.calls = []
        self.good = good

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        fields = kwargs["json_schema"]["properties"]
        if "actions" in fields:
            allowed = fields["actions"]["items"]["properties"]["source_id"]["enum"]
            return {"actions": [{"source_id": allowed[0],
                                 "action": "Server changes the player's currency balance to complete a trade."}]}
        if "given_mutation" in fields:
            if self.good:
                return {
                    "given_mutation": "The server deducts owned ore from the player's verified inventory",
                    "received_mutation": "the server credits earned money to the same player's owned currency balance",
                }
            return {
                "given_mutation": "The server updates a player menu but does not deduct any owned items",
                "received_mutation": "the server displays the money count without crediting any owned balance",
            }
        raise AssertionError("Unexpected planner action")


def test_vague_exchange_rescued_without_replanning_harvest():
    router = TinyPlanner()
    fixed = complete_source_owned_actions(router, SOURCE, initial_actions=inputs())
    assert len(fixed) == 2
    assert fixed[0]["action"] == inputs()[0]["action"]
    assert fixed[0]["source_quote"] == "자원파밍"
    assert fixed[1]["source_quote"] == "거래"
    assert "deducts owned ore" in fixed[1]["action"]
    assert "credits earned money" in fixed[1]["action"]
    assert not _coverage_issues(SOURCE, fixed)
    assert [len(x[1]["json_schema"]["required"]) for x in router.calls][-1] == 2


def test_invalid_dual_effect_never_accepted_as_success():
    router = TinyPlanner(good=False)
    with pytest.raises(SourceActionBindingError, match="MISSING_ACTION_UNRESOLVED"):
        complete_source_owned_actions(router, SOURCE, initial_actions=inputs())
    assert any("given_mutation" in c[1]["json_schema"]["properties"] for c in router.calls)


def test_generic_repair_leaves_sibling_and_source_ownership_unchanged():
    initial = inputs()
    router = TinyPlanner()
    rewritten = _repair_incomplete_owned_exchange(
        router, SOURCE, initial,
        ["SOURCE_TRADE_ACTION_MISSING: needs a real server-owned exchange"],
        max_actions=6, evidence=[],
    )
    assert rewritten
    assert rewritten[0] == initial[0]
    assert rewritten[1]["source_id"] == initial[1]["source_id"]
    assert initial[1]["action"] == "Server changes the player's currency balance to complete a trade."
