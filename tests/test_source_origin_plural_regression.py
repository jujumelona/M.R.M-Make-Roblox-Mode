"""Regression: legitimate plural resource origins must retain source ownership.

A semantic source gate must distinguish verified world extraction from a
balance-only fake. Plural resource nodes/deposits are the same world entity
class as a singular node/deposit, and are not a license to mint resources.
"""
import pytest

from roblox_mod_ai.semantic_preservation import source_intent_conflicts


@pytest.mark.parametrize("origin", [
    "resource nodes", "ore deposits", "ore veins", "resource node",
    "ore deposit", "ore vein",
])
def test_server_mining_with_concrete_origin_accepted(origin):
    server = (
        f"Server verifies nearby {origin}, mines the source and credits "
        "the extracted resources into the player's owned inventory."
    )
    errors = source_intent_conflicts("자원파밍", server)
    assert not any("RESOURCE_GATHER_SOURCE_UNBOUND" in issue for issue in errors)
    assert not any("RESOURCE_GATHER_ACTION_MISSING" in issue for issue in errors)


@pytest.mark.parametrize("fake_action", [
    "Server credits the player's resource balance without world extraction.",
    "Server shows the resource-gathering menu but does not harvest a node.",
    "Server consumes previously owned materials and credits earned coins.",
    "Server displays a resource-gathering menu beside world resource nodes.",
    "Server checks a nearby world node and says resource extraction is available.",
])
def test_non_mining_resource_mutation_still_rejected(fake_action):
    assert source_intent_conflicts("자원파밍", fake_action)


@pytest.mark.parametrize("description", [
    "Server harvests crops from a real farm field and grants them to the player's inventory.",
    "Server gathers wood from trees in the world and credits collected wood to owned inventory.",
    "Server collects resources from resource sources and stores the yield in the player's inventory.",
])
def test_non_ore_world_gathering_is_not_silently_lost(description):
    errors = source_intent_conflicts("자원파밍", description)
    assert not any(issue.startswith("RESOURCE_GATHER_") for issue in errors)
