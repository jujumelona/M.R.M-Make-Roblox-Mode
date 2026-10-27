"""Reproduce real failure bundle (10): the fourth 'money + farming' action
is a stronger implementation of an existing weak farming owner, not a new
requirement for money to be minted at the mine.

Do not disable whole-clause or per-action validators. Never mutate verified
unrelated resource sale or ship assembly entries.
"""
from copy import deepcopy

from roblox_mod_ai.atomic_action_quotes import eligible_atomic_action_spans
from roblox_mod_ai.source_owned_microplanning import (
    complete_source_owned_actions,
    _replace_weak_owner_with_stronger_overlapping_action,
    _coverage_issues,
)

SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)
WEAK = "Server grants resources to the player for resource-gathering."
TRADE = (
    "Server trades collected resources for money at a server-priced market: "
    "it deducts owned resource inventory and credits earned currency "
    "to the same player's balance."
)
SHIP = (
    "Server attaches a server-owned ship section to the player's "
    "owned spaceship, completing the piece-by-piece construction."
)
REAL_MINE = (
    "Server marks the authoritative mineable world source as harvested "
    "and extracts the corresponding resource into the player's owned "
    "resource inventory."
)


class NoModel:
    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Do not ask a 9B model to repeat the same action")


def rows(actions, source=SOURCE):
    by_quote = {span["quote"]: span["id"]
                for span in eligible_atomic_action_spans(source)}
    return [{"source_id": by_quote[quote], "action": action}
            for quote, action in actions]


def failed_plan80_actions():
    return rows([
        ("자원파밍", WEAK),
        ("돈모으기 거래", TRADE),
        ("부위마다", SHIP),
        ("자원파밍 돈모으기", REAL_MINE),
    ])


def test_actual_four_actions_promote_real_mining_into_existing_owner():
    raw = failed_plan80_actions()
    saved = deepcopy(raw)
    fixed = _replace_weak_owner_with_stronger_overlapping_action(
        NoModel(), SOURCE, raw, max_actions=6,
    )
    assert len(fixed) == 3
    assert fixed[0]["source_id"] == raw[0]["source_id"]
    assert fixed[0]["action"] == REAL_MINE
    assert fixed[1] == raw[1]
    assert fixed[2] == raw[2]
    assert raw == saved
    result = complete_source_owned_actions(
        NoModel(), SOURCE, initial_actions=raw,
    )
    assert len(result) == 3
    assert [row["source_quote"] for row in result] == [
        "자원파밍", "돈모으기 거래", "부위마다"
    ]
    assert result[0]["action"] == REAL_MINE
    assert result[1]["action"] == TRADE
    assert result[2]["action"] == SHIP
    assert not _coverage_issues(SOURCE, result)


def test_no_auto_replace_a_complete_world_harvest():
    source_actions = rows([
        ("자원파밍", REAL_MINE),
        ("돈모으기 거래", TRADE),
        ("부위마다", SHIP),
        ("자원파밍 돈모으기", (
            "Server grants a unique mission reward for the player's "
            "completed mining and credits money to their balance."
        )),
    ])
    assert _replace_weak_owner_with_stronger_overlapping_action(
        NoModel(), SOURCE, source_actions, max_actions=6,
    ) == source_actions


def test_non_overlapping_source_owners_are_not_conflated():
    actions = rows([
        ("자원파밍", WEAK),
        ("돈모으기 거래", TRADE),
        ("부위마다", REAL_MINE),
    ])
    assert _replace_weak_owner_with_stronger_overlapping_action(
        NoModel(), SOURCE, actions, max_actions=6,
    ) == actions


def test_no_removal_when_replacement_loses_a_requested_effect():
    original = rows([
        ("자원파밍", WEAK),
        ("돈모으기 거래", TRADE),
        ("부위마다", SHIP),
        ("자원파밍 돈모으기", (
            "Server grants a fixed mining mission reward and credits "
            "the player's earned money balance."
        )),
    ])
    result = _replace_weak_owner_with_stronger_overlapping_action(
        NoModel(), SOURCE, original, max_actions=6,
    )
    assert result == original


def test_validator_root_cause_is_wrong_owner_not_missing_global_money():
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    weak = source_intent_conflicts("자원파밍", WEAK)
    strong = source_intent_conflicts("자원파밍", REAL_MINE)
    overloaded = source_intent_conflicts("자원파밍 돈모으기", REAL_MINE)
    assert "RESOURCE_GATHER_SOURCE_UNBOUND" in " ".join(weak)
    assert not strong
    assert "SOURCE_CURRENCY_EARNING_MISSING" in " ".join(overloaded)
