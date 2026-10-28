"""Regression for production failure-log 39: semantic extraction must survive.

The original model produced a physical world-source depletion AND a transfer
into player-owned inventory. The prior _GAIN-only gate lost that action and
spent all local retries on non-equivalent model rewrites.
"""
from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems
from roblox_mod_ai.grounded_atomic_source_effects import (
    preserved_world_inventory_extraction,
)

SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
    "부위마다 만들어서 만들수있고 무기 선원 우주선 성능을 "
    "거래 구매 등으로 업그레이드 확장 할 수 있고 "
    "그렇게해서 우주로 나갈수있고 우주로 나가면 다른행성의 "
    "특수 광물 외게인과 싸움 식민지화등 여러가지가 가능한 모드"
)
OWNED = {
    "source_quote": "자원파밍",
    "action": (
        "Server marks the authoritative mineable world source as harvested "
        "and extracts the corresponding resource into the player's owned "
        "resource inventory."
    ),
}
SCHEMA = {"type": "object", "properties": {
    "systems": {"type": "array", "items": {"type": "object"}},
}}


class NoModelRetry:
    def complete_json(self, *args, **kwargs):
        raise AssertionError(
            "Already-grounded physical extraction must not be regenerated"
        )


def test_log39_preserves_exact_authoritative_world_extraction_and_owned_gain():
    result = preserved_world_inventory_extraction(
        OWNED, original_prompt=SOURCE,
    )
    assert result is not None
    assert OWNED["action"] in result["server_behavior"]
    assert "actually extracted" in result["observable_result"]
    assert result["world_entities"] == []  # Not a fictitious Roblox Part


def test_log39_atomic_authoring_does_not_spend_three_local_retries():
    accepted = {}
    result = author_verified_atomic_systems(
        NoModelRetry(), [OWNED], source_clause=SOURCE,
        original_prompt=SOURCE, json_schema=SCHEMA,
        retained_verified=accepted,
    )
    assert len(result) == 1
    assert accepted[(OWNED["source_quote"], OWNED["action"])] == result[0]


def test_log39_does_not_accept_non_owned_or_unproven_resources():
    rejected = [
        OWNED["action"].replace(
            "into the player's owned resource inventory",
            "into a client-only popup",
        ),
        OWNED["action"].replace("mineable world source", "resource menu"),
        OWNED["action"].replace(
            "player's owned resource inventory",
            "NPC-owned inventory",
        ),
        OWNED["action"].replace(
            "and extracts", "and never extracts",
        ),
        ("Server extracts the corresponding resource into the player's "
         "owned resource inventory."),
        ("Server previews a resource source and opens the inventory UI "
         "without harvesting or transferring any resource."),
    ]
    for action in rejected:
        assert preserved_world_inventory_extraction(
            dict(OWNED, action=action), original_prompt=SOURCE,
        ) is None, action
