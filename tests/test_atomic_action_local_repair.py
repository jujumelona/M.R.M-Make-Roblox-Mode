"""Regression for production plan_failure_logs (10): colony outcome failed.

The three source-anchored atomic actions are selected once. When only the
third observable result is invalid, no second model call is made for
previously accepted ore gathering or alien combat.
"""
import json
import pytest

from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems
from roblox_mod_ai.atomic_action_quotes import SourceActionBindingError


SOURCE = (
    "우주로 나가면 다른행성의 특수 광물 외게인과 싸움 "
    "식민지화등 여러가지가 가능한 모드"
)
ACTIONS = [
    {
        "source_quote": "다른행성의 특수 광물",
        "action": "Harvest special planetary minerals",
    },
    {"source_quote": "싸움", "action": "Fight alien enemies"},
    {"source_quote": "식민지화등", "action": "Colonize settlements"},
]
VALID_SYSTEMS = [
    {
        "name": "OreHarvest",
        "server_behavior": (
            "Server validates the planetary mineral deposit and harvests "
            "new special ore from the world node into persistent inventory."
        ),
        "observable_result": "Newly mined special ore appears in player inventory.",
        "world_entities": [],
    },
    {
        "name": "AlienCombat",
        "server_behavior": (
            "Server verifies an alien NPC enemy and damages its health "
            "during player combat with the alien enemy."
        ),
        "observable_result": "The alien enemy loses health after player combat.",
        "world_entities": [],
    },
    {
        "name": "PlanetColony",
        "server_behavior": (
            "Server validates the planet and establishes a new colony, "
            "then records permanent colony ownership in player state."
        ),
        "observable_result": (
            "The planet now has a newly established colony settlement "
            "owned by the player."
        ),
        "world_entities": [],
    },
]
BAD_COLONY_RESULT = "The colonization mode becomes available in the menu."


class ScriptedRouter:
    def __init__(self, *, repeat_bad_result=False):
        self.calls = []
        self.repeat_bad_result = repeat_bad_result

    def complete_json(self, prompt, **kwargs):
        self.calls.append(prompt)
        payload = json.loads(prompt.split("\n")[-1])
        if "this_action" in payload:
            index = next(i for i, action in enumerate(ACTIONS)
                         if action["action"] == payload["this_action"]["action"])
            row = dict(VALID_SYSTEMS[index])
            if index == 2:
                row["observable_result"] = BAD_COLONY_RESULT
            return {"systems": [row]}
        assert "rejected_field" in payload
        assert payload["source_owned_action"] == ACTIONS[2]["action"]
        assert payload["rejected_field"] == BAD_COLONY_RESULT
        assert len(payload["exact_validator_errors"]) >= 1
        return {
            "observable_result": (
                BAD_COLONY_RESULT if self.repeat_bad_result
                else VALID_SYSTEMS[2]["observable_result"]
            )
        }


def test_colony_result_repair_preserves_accepted_atomic_siblings():
    router = ScriptedRouter()
    result = author_verified_atomic_systems(
        router, ACTIONS,
        source_clause=SOURCE, original_prompt=SOURCE,
        json_schema={"type": "object"},
    )
    assert len(router.calls) == 4, "3 initial actions and just 1 local repair"
    assert result == VALID_SYSTEMS
    assert sum("this_action" in x for x in router.calls) == 3
    assert sum("rejected_field" in x for x in router.calls) == 1


def test_repeated_colony_result_fails_fast_without_replanning_all_actions():
    router = ScriptedRouter(repeat_bad_result=True)
    with pytest.raises(SourceActionBindingError,
                       match="ATOMIC_LOCAL_REPAIR_NO_PROGRESS: 2"):
        author_verified_atomic_systems(
            router, ACTIONS,
            source_clause=SOURCE, original_prompt=SOURCE,
            json_schema={"type": "object"},
        )
    assert len(router.calls) == 4


def test_local_repair_must_be_bounded():
    with pytest.raises(ValueError, match="budget"):
        author_verified_atomic_systems(
            ScriptedRouter(), ACTIONS,
            source_clause=SOURCE, original_prompt=SOURCE,
            json_schema={"type": "object"},
            max_attempts_per_action=99,
        )
