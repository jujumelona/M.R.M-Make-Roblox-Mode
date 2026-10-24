"""Plan 70: one original sentence contains distinct weapon, crew and ship actions.

Prior architect asked for one 1,400-token JSON and then accepted two ship-only
action names; the existing whole-clause validation raised
ATOMIC_SOURCE_COLLECTIVE_ACTIONS_DROPPED and discarded the plan.

The new planner retains accepted action IDs and asks the 9B model for only
missing source-owned targets, one small JSON response at a time.
"""
import pytest

from roblox_mod_ai.atomic_action_quotes import (
    SourceActionBindingError, eligible_atomic_action_spans,
    verify_or_bind_actions,
)
from roblox_mod_ai.source_owned_microplanning import (
    complete_source_owned_actions,
)
from roblox_mod_ai.semantic_preservation import source_intent_conflicts


SOURCE = "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"


def sid(fragment, *, exclude=()):
    return next(
        row["id"] for row in eligible_atomic_action_spans(SOURCE)
        if fragment in row["quote"] and row["id"] not in exclude
    )


class Router:
    def __init__(self, results):
        self.results = iter(results)
        self.requests = []

    def complete_json(self, prompt, **kwargs):
        self.requests.append((prompt, kwargs))
        answer = next(self.results)
        if isinstance(answer, Exception):
            raise answer
        return answer


def action(source_id, text):
    return {"source_id": source_id, "action": text}


def test_legacy_source_completeness_still_rejects_ship_only_actions():
    # Default API remains strict; it must never accept two ship features
    # as if they covered explicitly requested crew and weapons.
    actions = [
        action(sid("우주선"),
               "Server purchases a ship performance upgrade and deducts currency."),
        action(sid("성능을", exclude={sid("우주선")}),
               "Server upgrades ship engines and increases their speed."),
    ]
    with pytest.raises(SourceActionBindingError,
                       match="ATOMIC_SOURCE_COLLECTIVE_ACTIONS_DROPPED"):
        verify_or_bind_actions(Router([]), SOURCE, actions)


def test_incremental_missing_targets_are_requested_one_at_a_time():
    ship_a = sid("우주선")
    ship_b = sid("성능을", exclude={ship_a})
    weapon = sid("무기", exclude={ship_a, ship_b})
    crew = sid("선원", exclude={ship_a, ship_b, weapon})
    initial = [
        action(ship_a,
               "Server purchases a ship performance upgrade and deducts currency."),
        action(ship_b,
               "Server upgrades ship engines and increases their speed."),
    ]
    additions = [
        action(weapon,
               "Server purchases a weapon upgrade, deducts coins, and improves "
               "the equipped weapon's attack stats."),
        action(crew,
               "Server hires a crew member, deducts credits, and adds the "
               "recruited crew member to the player's ship roster."),
    ]
    router = Router([
        {"actions": initial},
        {"actions": [additions[0]]},
        {"actions": [additions[1]]},
    ])
    result = complete_source_owned_actions(router, SOURCE)
    assert len(result) == 4
    assert {a["source_quote"] for a in result} == {
        next(row["quote"] for row in eligible_atomic_action_spans(SOURCE)
             if row["id"] == item["source_id"])
        for item in [*initial, *additions]
    }
    assert not source_intent_conflicts(
        SOURCE, ". ".join(row["action"] for row in result),
        require_implementation=True,
    )
    assert [call[1]["max_tokens"] for call in router.requests] == [
        340, 180, 180,
    ]
    assert all(call[1]["json_schema"]["properties"]["actions"]["items"]
                   ["properties"]["action"]["maxLength"] == 150
               for call in router.requests)
    assert [call[1]["json_schema"]["properties"]["actions"]["maxItems"]
            for call in router.requests] == [3, 1, 1]


def test_verified_actions_are_reused_without_a_new_model_call():
    ship_a = sid("우주선")
    ship_b = sid("성능을", exclude={ship_a})
    weapon = sid("무기", exclude={ship_a, ship_b})
    crew = sid("선원", exclude={ship_a, ship_b, weapon})
    combined = [
        action(ship_a,
               "Server purchases a ship performance upgrade and deducts currency."),
        action(ship_b,
               "Server upgrades ship engines and increases their speed."),
        action(weapon,
               "Server purchases a weapon upgrade, deducts coins, and improves "
               "the equipped weapon's attack stats."),
        action(crew,
               "Server hires a crew member, deducts credits, and adds the "
               "recruited crew member to the player's ship roster."),
    ]
    first = complete_source_owned_actions(
        Router([]), SOURCE, initial_actions=combined,
    )
    empty = Router([])
    second = complete_source_owned_actions(
        empty, SOURCE, initial_actions=first,
    )
    assert first == second
    assert empty.requests == []


def test_no_unrelated_action_can_bypass_exact_source_ownership():
    ship_a = sid("우주선")
    ship_b = sid("성능을", exclude={ship_a})
    actions = [
        action(ship_a,
               "Server purchases a ship upgrade and deducts currency."),
        action(ship_b, "Server awards free Robux as player compensation."),
    ]
    with pytest.raises(SourceActionBindingError):
        verify_or_bind_actions(
            Router([]), SOURCE, actions,
            require_complete=False, max_actions=6,
        )


def test_never_silently_accept_uncovered_6_action_source():
    ship_a = sid("우주선")
    ship_b = sid("성능을", exclude={ship_a})
    invalid = [
        action(ship_a,
               "Server purchases a ship performance upgrade and deducts credits."),
        action(ship_b,
               "Server upgrades ship propulsion performance."),
    ]
    router = Router([
        {"actions": [action(sid("무기", exclude={ship_a, ship_b}),
                            "Server upgrades only the ship's navigation speeds.")]},
        {"actions": [action(sid("선원", exclude={ship_a, ship_b}),
                            "Server upgrades only the ship's navigation speeds.")]},
    ])
    with pytest.raises(SourceActionBindingError):
        complete_source_owned_actions(
            router, SOURCE, initial_actions=invalid,
        )



def test_four_source_facets_choose_correct_planning_mode():
    from roblox_mod_ai.source_owned_microplanning import (
        needs_compound_microplanning,
    )
    assert needs_compound_microplanning(
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
        "우주선을 부위마다 만들어서 만들수있고"
    )
    assert needs_compound_microplanning(SOURCE)
    assert needs_compound_microplanning(
        "우주로 나가면 다른행성의 특수 광물 외게인과 싸움 "
        "식민지화등 여러가지가 가능한 모드"
    )
    assert not needs_compound_microplanning(
        "그렇게해서 우주로 나갈수있고"
    )


def test_source_action_count_cap_cannot_hide_missing_mechanics():
    # Without this guard a six-item plan could be certified even though
    # require_implementation=False misses money earning and actual resource
    # harvesting requirements from the original language.
    from roblox_mod_ai.source_owned_microplanning import (
        _coverage_issues,
    )
    source = (
        "자원파밍 돈모으기 거래 등으로 우주선을 "
        "부위마다 만들어서 만들수있고"
    )
    planned = [
        {"action": "Server purchases a craft section and deducts credits."},
        {"action": "Server validates craft section costs and updates inventory."},
        {"action": "Server constructs a new craft section using owned material."},
        {"action": "Server installs a finished craft section into the ship."},
    ]
    errors = _coverage_issues(source, planned)
    assert any("RESOURCE_GATHER_ACTION_MISSING" in error for error in errors)
    assert any("SOURCE_CURRENCY_EARNING_MISSING" in error for error in errors)


def test_exact_default_bindings_remain_strict():
    # Old callers must still reject missing source activities; the optional
    # partial admission cannot silently change the established API contract.
    only_ship = [
        {"source_id": sid("우주선"),
         "action": "Server purchases a ship performance upgrade and deducts currency."},
        {"source_id": sid("성능을", exclude={sid("우주선")}),
         "action": "Server upgrades ship engines and increases their speed."},
    ]
    with pytest.raises(SourceActionBindingError, match="COLLECTIVE"):
        verify_or_bind_actions(Router([]), SOURCE, only_ship)
