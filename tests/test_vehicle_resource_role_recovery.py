"""Generic regression checks for source-owned resource -> vehicle handoff.

These tests check role classification only. They do not claim Roblox Studio
physics, code generation, or persistence integration has been executed.
"""
from roblox_mod_ai.host_mining_contract import _is_named_mining_service
from roblox_mod_ai.vehicle_identity_contract import _BUILD, _VEHICLE


PROMPT = "Gather ore from a mineable source, sell resources, build a spacecraft."


def test_attachment_builder_is_recognized_without_build_verb():
    description = "Server attaches an owned module to a spaceship section."
    assert _BUILD.search(description)
    assert _VEHICLE.search(description)
    assert not _BUILD.search("Server detaches a passenger from a spaceship.")


def test_world_to_owned_inventory_accepts_both_clause_orders():
    forward = (
        "Server marks the authoritative mineable world source as harvested "
        "and extracts the corresponding resource into the player's owned "
        "resource inventory."
    )
    reverse = (
        "Server checks the player's owned mineral inventory before "
        "extracting a mineral from a mineable deposit."
    )
    for description in (forward, reverse):
        assert _is_named_mining_service(
            "ResourceOwnershipTransferServer", description, PROMPT
        )


def test_unrelated_resource_reader_is_not_a_miner():
    description = (
        "Server advertises a mineable world resource node and the player's "
        "owned inventory for ship upgrades, without changing either."
    )
    assert not _is_named_mining_service(
        "UpgradeInventoryReaderServer", description, PROMPT
    )


def test_source_prohibition_overrides_role_words():
    description = (
        "Server extracts resources from a mineable world node into "
        "the player's owned inventory."
    )
    assert not _is_named_mining_service(
        "ResourceOwnershipTransferServer", description,
        "A spaceship shop with no mining or harvesting allowed."
    )
