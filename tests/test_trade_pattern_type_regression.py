"""Regression for proposal 66: Match/None must never be treated as Patterns.

The production trace reached semantic_preservation.source_intent_conflicts
via both source-chunk classification and scoped architecture validation.
"""
import pytest

from roblox_mod_ai.semantic_preservation import (
    source_intent_conflicts,
    source_outcome_conflicts,
)


@pytest.mark.parametrize(("source", "description", "missing_trade"), [
    ("거래 구매", "The server opens a trade menu.", True),
    ("거래 구매", "Server displays the spaceship building guide.", True),
    ("거래 구매", "Server validates a purchase but does not transfer anything.", True),
    (
        "거래 구매",
        "Server validates a purchase, then transfers purchased items to inventory.",
        False,
    ),
    (
        "거래 구매",
        "Server validates a purchase. A different module consumes fuel on takeoff.",
        True,
    ),
    ("적과 전투", "Server updates an enemy's health on attack.", False),
])
def test_trade_action_match_or_none_never_crashes(
    source, description, missing_trade,
):
    issues = source_intent_conflicts(source, description)
    assert any("SOURCE_TRADE_ACTION_MISSING" in issue for issue in issues) == missing_trade


def test_original_request_with_many_actions_no_attribute_error():
    source = (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
        "부위마다 만들어서 만들수있고 무기 선원 우주선 성능을 "
        "거래 구매 등으로 업그레이드 확장 할 수 있고 "
        "그렇게해서 우주로 나갈수있고 "
        "우주로 나가면 다른행성의 특수 광물 "
        "외게인과 싸움 식민지화등 여러가지가 가능한 모드"
    )
    description = (
        "The server checks the player's craft section and consumes "
        "previously owned resources. After validating an action, "
        "the client opens a trade panel."
    )
    issues = source_intent_conflicts(source, description)
    assert "SOURCE_TRADE_ACTION_MISSING" in " ".join(issues)
    assert "RESOURCE_GATHER_ACTION_MISSING" in " ".join(issues)
    # Classification must not mistake its explanatory source text for a
    # completed gameplay action, and must not crash on absent trade effects.
    assert isinstance(source_intent_conflicts(
        source, description, require_implementation=False,
    ), list)
    assert isinstance(source_outcome_conflicts(source, description), list)
