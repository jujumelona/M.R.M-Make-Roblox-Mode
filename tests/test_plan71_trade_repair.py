"""Regression for proposal (71): repeated short non-trade answers.

A compound original clause already has mining, currency earned and ship
construction. The 9B model repeatedly replies to a 48-source-ID prompt
without specifying a trade transfer. Instead of failing an entire feature
after three resets, ask for ONE source-anchored authoritative effect with a
small one-field schema. Never insert host-invented game mechanics.
"""
import pytest

from roblox_mod_ai.atomic_action_quotes import (
    eligible_atomic_action_spans, SourceActionBindingError,
)
from roblox_mod_ai.source_owned_microplanning import (
    complete_source_owned_actions, _focused_source_span, _coverage_issues,
)

SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)


def span(piece):
    return next(row for row in eligible_atomic_action_spans(SOURCE)
                if row["quote"] == piece)


def initial():
    return [
        {
            "source_id": span("자원파밍")["id"],
            "action": (
                "Server validates the resource node and mines new ore "
                "into the player's owned inventory."
            ),
        },
        {
            "source_id": span("돈모으기")["id"],
            "action": (
                "Server validates a mining reward and credits earned "
                "currency into the player's authoritative money balance."
            ),
        },
        {
            "source_id": span("부위마다")["id"],
            "action": (
                "Server checks owned materials and builds a craft section "
                "attached to the owned ship model."
            ),
        },
    ]


class Router:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_trade_is_source_anchored_not_model_id_guessed():
    selected = _focused_source_span(
        SOURCE, "SOURCE_TRADE_ACTION_MISSING: trade needs a transfer",
        eligible_atomic_action_spans(SOURCE),
        {"자원파밍", "돈모으기", "부위마다"},
    )
    assert selected is not None
    assert selected["quote"] == "거래"


def test_original_trade_failure_recovers_with_short_host_owned_source():
    # Two 48-ID requests fail to provide a game-state change.
    ineffective = {
        "source_id": span("거래")["id"],
        "action": "Server opens a trade menu, displays ore prices and waits.",
    }
    model_replies = [
        {"actions": [ineffective]},
        {"actions": [{
            **ineffective,
            "action": "Server shows the trade catalog and updates the UI.",
        }]},
        {"action": (
            "Server validates an ore trade, deducts owned ore, and credits "
            "the player's authoritative currency balance."
        )},
    ]
    router = Router(model_replies)
    bound = complete_source_owned_actions(
        router, SOURCE, initial_actions=initial(),
    )
    assert len(bound) == 4
    assert bound[-1]["source_quote"] == "거래"
    assert not _coverage_issues(SOURCE, bound)
    assert [x["max_tokens"] for _, x in router.calls] == [180, 180, 160]
    final_prompt, final_options = router.calls[-1]
    assert "source_quote" in final_prompt
    assert "거래" in final_prompt
    assert "source_id" not in final_options["json_schema"]["properties"]
    assert "action" in final_options["json_schema"]["properties"]


def test_focused_reply_still_must_prove_exchange_mutation():
    router = Router([
        {"actions": [{
            "source_id": span("거래")["id"],
            "action": "Server opens a trade menu and validates selection.",
        }]},
        {"actions": [{
            "source_id": span("거래")["id"],
            "action": "Server shows a trade confirmation dialog.",
        }]},
        {"action": (
            "Server validates a trade request and shows a confirmation "
            "without changing player inventory."
        )},
        {"action": (
            "Server validates a trade request and leaves currency and "
            "player inventory unchanged."
        )},
    ])
    with pytest.raises(SourceActionBindingError,
                       match="ATOMIC_SOURCE_MISSING_ACTION_UNRESOLVED"):
        complete_source_owned_actions(
            router, SOURCE, initial_actions=initial(),
        )
    assert len(router.calls) == 4


def test_no_source_anchor_for_unrequested_effect():
    assert _focused_source_span(
        SOURCE, "SETTLEMENT_DROPPED: settlement not present",
        eligible_atomic_action_spans(SOURCE), set(),
    ) is None


def test_failed_trade_model_reply_is_reported_not_hidden():
    router = Router([
        {"actions": [{
            "source_id": span("거래")["id"],
            "action": "Server displays a trade menu only.",
        }]},
        {"actions": [{
            "source_id": span("거래")["id"],
            "action": "Server displays an item catalog only.",
        }]},
        {"action": (
            "Server displays trade offers, with all player balances "
            "remaining unchanged."
        )},
        {"action": (
            "Server displays trade offers, with all player balances "
            "remaining unchanged."
        )},
    ])
    with pytest.raises(SourceActionBindingError) as exc:
        complete_source_owned_actions(
            router, SOURCE, initial_actions=initial(),
        )
    assert "rejected:" in str(exc.value)
    assert "FOCUSED_NO_PROGRESS" in str(exc.value)



def test_truncated_local_gap_responses_do_not_restart_entire_facet():
    router = Router([
        ValueError("Model JSON completion truncated (finish_reason=length)"),
        ValueError("Model JSON completion truncated (finish_reason=length)"),
        {"action": (
            "Server validates a player-initiated ore trade, deducts owned "
            "ore and credits the player's earned currency balance."
        )},
    ])
    result = complete_source_owned_actions(
        router, SOURCE, initial_actions=initial(),
    )
    assert len(result) == 4
    assert result[-1]["source_quote"] == "거래"
    assert len(router.calls) == 3
    assert not _coverage_issues(SOURCE, result)
