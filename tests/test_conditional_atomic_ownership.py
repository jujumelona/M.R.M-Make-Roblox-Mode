"""The prerequisite 'when arriving in space' cannot become a second launch.

Replays the 2026-10-23 plan_failure_logs (9) source/action mapping, including
the erroneous ID s11. No Roblox Studio runtime claim is made by these tests.
"""
import pytest

from roblox_mod_ai.atomic_action_quotes import (
    SourceActionBindingError,
    indexed_source_spans,
    eligible_atomic_action_spans,
    action_claims_unowned_departure,
    verify_or_bind_actions,
    validate_atomic_system_ownership,
)
from roblox_mod_ai.semantic_preservation import source_intent_conflicts


SOURCE = (
    "우주로 나가면 다른행성의 특수 광물 외게인과 싸움 "
    "식민지화등 여러가지가 가능한 모드"
)


class NoRepair:
    def complete_json(self, *args, **kwargs):
        raise AssertionError("Valid source anchors must not require another model")


def test_conditional_span_is_stable_but_not_an_executable_action():
    all_spans = {row["id"]: row["quote"] for row in indexed_source_spans(SOURCE)}
    eligible = {row["id"]: row["quote"] for row in eligible_atomic_action_spans(SOURCE)}
    assert all_spans["s11"] == "우주로 나가면"
    assert "s11" not in eligible
    assert eligible["s6"] == "싸움"
    assert eligible["s7"] == "식민지화등"
    assert eligible["s23"] == "다른행성의 특수 광물"
    assert action_claims_unowned_departure(SOURCE, "Travel to space")
    assert not action_claims_unowned_departure(SOURCE, "Fight alien enemies")
    assert not source_intent_conflicts(
        SOURCE, "Mine special ore, fight alien enemies, establish a colony",
        require_implementation=False,
    )


def test_real_bad_selection_is_rejected_before_calling_action_implementer():
    actions = [
        {"source_id": "s6", "action": "Fight alien enemies"},
        {"source_id": "s7", "action": "Colonize planets"},
        {"source_id": "s11", "action": "Travel to space"},
    ]
    with pytest.raises(SourceActionBindingError,
                       match="ATOMIC_CONDITIONAL_PROMOTED_TO_ACTION"):
        verify_or_bind_actions(NoRepair(), SOURCE, actions)


def test_all_three_real_downstream_gameplay_actions_remain_eligible():
    actions = [
        {"source_id": "s23", "action": "Mine special minerals from other planets"},
        {"source_id": "s6", "action": "Fight hostile alien NPC enemies"},
        {"source_id": "s7", "action": "Establish a persistent colony on a planet"},
    ]
    bound = verify_or_bind_actions(NoRepair(), SOURCE, actions)
    assert len(bound) == 3
    assert {row["source_quote"] for row in bound} == {
        "다른행성의 특수 광물", "싸움", "식민지화등"
    }
    systems = [
        {
            "server_behavior": (
                "The server validates a world deposit and harvests special "
                "minerals from a planet node, adding mined ore to the player's "
                "persistent resource inventory."
            ),
            "observable_result": (
                "A newly mined special mineral appears in the saved inventory."
            ),
        },
        {
            "server_behavior": (
                "The server checks an alien NPC enemy in combat range, applies "
                "authoritative attack damage to the alien, and updates enemy health."
            ),
            "observable_result": "The alien NPC enemy loses health after combat.",
        },
        {
            "server_behavior": (
                "The server checks world ownership and then establishes a "
                "new colony on the planet, persisting settlement ownership."
            ),
            "observable_result": (
                "The planet now has a newly established colony settlement "
                "owned by the player."
            ),
        },
    ]
    validate_atomic_system_ownership(
        bound, systems, original_prompt=SOURCE,
    )


def test_independent_ship_launch_elsewhere_in_source_is_not_removed():
    original = (
        "우주선을 만들어서 우주로 나갈수있고 "
        "우주로 나가면 다른행성의 광물 파밍도 가능"
    )
    assert not action_claims_unowned_departure(original, "Launch ship into space")
    assert any(
        row["quote"] == "우주로 나가면"
        for row in eligible_atomic_action_spans(original)
    )
