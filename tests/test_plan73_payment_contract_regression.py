"""Plan 73 reproducible regression for the verified no-payment false negative.

The actual failed proposal rejected:
"Server debits the buyer's owned currency for the weapon purchase."
The purchase checker accidentally used r'[.!?\\n]+' and SPLIT NORMAL LETTER n
inside 'owned', leaving no single phrase with both debit and currency.
Adding a fourth stand-alone debit action is not the correct repair either:
the host must supplement the existing purchase action, keeping its source
and its weapon/crew/ship target.
"""
import pytest

from roblox_mod_ai.semantic_preservation import source_intent_conflicts
from roblox_mod_ai.atomic_action_quotes import (
    eligible_atomic_action_spans, verify_or_bind_actions,
)
from roblox_mod_ai.source_owned_microplanning import (
    _coverage_issues, _coverage_improves,
    _repair_owned_purchase_effect, complete_source_owned_actions,
)


SOURCE = "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"
REJECTED = "Server debits the buyer's owned currency for the weapon purchase."


def _sid(part):
    return next(
        row["id"] for row in eligible_atomic_action_spans(SOURCE)
        if row["quote"] == part
    )


def _initial():
    return [
        {"source_id": _sid("무기"), "action":
            "Server purchases a weapon upgrade and increases weapon damage."},
        {"source_id": _sid("선원"), "action":
            "Server purchases a crew upgrade and improves crew capacity."},
        {"source_id": _sid("우주선"), "action":
            "Server purchases a ship upgrade and increases ship speed."},
    ]


class Router:
    def __init__(self, *answers):
        self.answers = iter(answers)
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return next(self.answers)


def test_exact_model_sentence_rejected_in_plan73_is_a_real_payment():
    assert not any(
        error.startswith(("SOURCE_PURCHASE_PAYMENT_MISSING:",
                          "SOURCE_TRADE_ACTION_MISSING:"))
        for error in source_intent_conflicts("무기 구매", REJECTED)
    ), "A word-boundary must not split 'owned currency' at its letter n"


def test_paid_debit_does_not_overwrite_other_upgrade_targets():
    initial = _initial()
    bound = verify_or_bind_actions(Router(), SOURCE, initial,
                                   require_complete=False, max_actions=6)
    before = _coverage_issues(SOURCE, bound)
    assert any(error.startswith("SOURCE_PURCHASE_PAYMENT_MISSING:")
               for error in before)
    router = Router({"action": (
        "Server validates the weapon purchase, debits the player's owned "
        "credits and installs the weapon upgrade into the owned loadout."
    )})
    result = complete_source_owned_actions(
        router, SOURCE, initial_actions=initial,
    )
    assert len(result) == 3, "Do not add a phantom payment-only fourth action"
    assert result[0]["source_quote"] == "무기"
    assert "debits" in result[0]["action"]
    assert result[1]["action"] == initial[1]["action"]
    assert result[2]["action"] == initial[2]["action"]
    assert not _coverage_issues(SOURCE, result)
    assert len(router.calls) == 1, "No 48-source-ID re-selection needed"
    assert set(router.calls[0][1]["json_schema"]["required"]) == {"action"}


def test_wrong_target_is_rejected_without_dropping_siblings():
    initial = _initial()
    bound = verify_or_bind_actions(Router(), SOURCE, initial,
                                   require_complete=False, max_actions=6)
    gaps = _coverage_issues(SOURCE, bound)
    router = Router(
        {"action": (
            "Server purchases and installs a crew upgrade by debiting "
            "the player's owned credits and increasing crew capacity."
        )},
        {"action": (
            "Server purchases and installs a weapon upgrade by debiting "
            "the player's owned credits and improving weapon damage."
        )},
    )
    evidence = []
    repaired = _repair_owned_purchase_effect(
        router, SOURCE, initial, gaps, 6, evidence,
    )
    assert repaired is not None
    assert repaired[0]["source_id"] == initial[0]["source_id"]
    assert repaired[1:] == initial[1:]
    assert any("TARGET_REPLACED" in item for item in evidence)


def test_unchanged_payment_claim_does_not_mask_semantic_failure():
    assert source_intent_conflicts(
        "무기 구매",
        "Server purchases a weapon and upgrades its damage without "
        "deducting any currency or resources.",
    )
    assert not _coverage_improves(
        ["SOURCE_PURCHASE_PAYMENT_MISSING: needed"],
        ["SOURCE_PURCHASE_PAYMENT_MISSING: needed"],
    )
    assert not _coverage_improves(
        ["SOURCE_PURCHASE_PAYMENT_MISSING: needed"],
        ["SOURCE_TRADE_ACTION_MISSING: new failure"],
    )
    assert _coverage_improves(
        ["SOURCE_PURCHASE_PAYMENT_MISSING: needed", "SOURCE_TRADE_ACTION_MISSING: needed"],
        ["SOURCE_TRADE_ACTION_MISSING: needed"],
    )
