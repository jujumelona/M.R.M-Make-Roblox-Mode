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

def test_blueprint_owned_attachment_requires_exact_provenance():
    from types import SimpleNamespace
    from roblox_mod_ai.host_ship_attachment import _source_linked_section_builder

    owner = SimpleNamespace(
        name="AttachVehicleSectionServer",
        description="Create one owned spacecraft section.",
    )
    trace = {
        "source": "Construct a spacecraft from separately attached sections.",
        "owners": [owner.name],
        "acceptance": "The owned spacecraft has one additional section attached.",
    }
    design = {
        "host_world_motion": {
            "DepartVehicleServer": {"kind": "vehicle_world_transition"}
        },
        "host_actions": {
            "DepartRemote": {
                "service": "DepartVehicleServer",
                "kind": "RemoteFunction",
            }
        },
        "host_typed_actions": {"DepartRemote": {"transport_only": True}},
        "remotes": {"DepartRemote": "RemoteFunction"},
    }
    proposal = SimpleNamespace(game_design={
        "implementation_blueprint": {"requirements": [trace]},
        "dynamic_design": design,
    })
    assert _source_linked_section_builder(owner, proposal)
    trace["owners"] = ["UnrelatedShopServer"]
    assert not _source_linked_section_builder(owner, proposal)


def test_vehicle_builder_identity_uses_same_named_action_in_all_gates():
    from types import SimpleNamespace
    from roblox_mod_ai.vehicle_identity_contract import (
        is_authored_vehicle_builder, relevant_candidates,
    )

    builder = SimpleNamespace(
        name="AttachVehicleSectionServer",
        module_id="dyn_attach_vehicle",
        file_path="src/server/AttachVehicleSectionServer.luau",
        description="Create one owned spacecraft section.",
    )
    consumer = SimpleNamespace(
        name="DepartVehicleServer",
        module_id="dyn_launch_vehicle",
        file_path="src/server/DepartVehicleServer.luau",
        description="Launch the player's spacecraft.",
    )
    assert is_authored_vehicle_builder(builder)
    assert relevant_candidates(
        {builder.name: builder, consumer.name: consumer}, consumer.name
    ) == [builder]
    assert not is_authored_vehicle_builder(SimpleNamespace(
        name="DisplayVehicleStatusServer",
        module_id="dyn_status",
        file_path="src/server/DisplayVehicleStatusServer.luau",
        description="Read the current status.",
    ))
