"""37th failure: repeated third atomic child despite complete source effect."""
import json

from roblox_mod_ai.atomic_action_authoring import (
    author_verified_atomic_systems,
)
from roblox_mod_ai.grounded_atomic_source_effects import (
    preserved_world_inventory_extraction,
)

SOURCE = ("우주로 나가면 다른행성의 특수 광물 외게인과 싸움 "
          "식민지화등 여러가지가 가능한 모드")
EXTRACT = {
    "source_quote": "다른행성의 특수 광물",
    "action": ("Player extracts other-planet special minerals from a "
               "source-owned mineral deposit, incrementing the player's "
               "owned inventory."),
}


class NoUnnecessaryModelCalls:
    supports_host_standard_transport = True

    def complete_json(self, prompt, **kwargs):
        raise AssertionError(
            "Source already authors extraction, physical origin and owned "
            "inventory mutation; model must not repeat its semantic rewrite."
        )


def test_log37_exact_planet_mineral_source_effect_is_preserved_without_9b():
    result = preserved_world_inventory_extraction(
        EXTRACT, original_prompt=SOURCE,
    )
    assert result is not None
    assert EXTRACT["action"] in result["server_behavior"]
    assert result["name"].startswith("SourceOwnedExtraction")
    assert "inventory" in result["observable_result"]
    assert result["world_entities"] == []


def test_log37_authoring_can_finish_third_child_without_regeneration():
    original = NoUnnecessaryModelCalls()
    schema = {"type": "object", "properties": {
        "systems": {"type": "array", "items": {"type": "object"}}
    }}
    accepted = {}
    output = author_verified_atomic_systems(
        original, [EXTRACT], source_clause=SOURCE,
        original_prompt=SOURCE, json_schema=schema,
        retained_verified=accepted,
    )
    assert len(output) == 1
    assert output[0]["name"].startswith("SourceOwnedExtraction")
    assert accepted[(EXTRACT["source_quote"], EXTRACT["action"])] == output[0]


def test_log37_never_convert_unproven_model_descriptions_into_world_effects():
    cases = [
        dict(EXTRACT, action="Player is allowed to access the mining menu."),
        dict(EXTRACT, action="Server grants the player minerals for no mine."),
        dict(EXTRACT, action=(
            "Player extracts special minerals from the planet, "
            "incrementing the player's owned inventory.")),
        dict(EXTRACT, action=(
            "Player inspects a mineral deposit, incrementing the player's "
            "owned inventory.")),
        dict(EXTRACT, action=(
            "Player extracts a deposit, never increasing the "
            "player's owned inventory.")),
        dict(EXTRACT, source_quote="A fake source quote"),
        dict(EXTRACT, action=(
            "Player extracts from a source-owned deposit but updates "
            "only a client-side popup.")),
    ]
    for action in cases:
        assert preserved_world_inventory_extraction(
            action, original_prompt=SOURCE,
        ) is None, action


def test_log37_generic_physical_resource_source_not_hardcoded_to_space_game():
    source = "Mine wood from a forest node and collect it"
    action = {
        "source_quote": source,
        "action": (
            "Server mines wood from a source-owned world resource node, "
            "incrementing the player's owned inventory."
        ),
    }
    result = preserved_world_inventory_extraction(
        action, original_prompt=source,
    )
    assert result is not None
    assert action["action"] in result["server_behavior"]


def test_log37_same_proposed_effect_deterministically_keeps_same_identity():
    first = preserved_world_inventory_extraction(
        EXTRACT, original_prompt=SOURCE,
    )
    second = preserved_world_inventory_extraction(
        EXTRACT, original_prompt=SOURCE,
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
