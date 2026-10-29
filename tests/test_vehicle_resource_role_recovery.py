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


def test_audited_world_extraction_materialization_provenance():
    from types import SimpleNamespace
    from roblox_mod_ai.host_mining_contract import _source_traced_extraction

    owner = SimpleNamespace(
        name="SourceOwnedExtraction820a4533281Server",
        description="Change the player's owned resource amount after an action.",
    )
    requirement = {
        "source": "Collect resources to construct and launch a vehicle.",
        "owners": [owner.name, "OtherClient"],
        "acceptance": (
            "After accepted world-resource extraction, the player's owned "
            "inventory increases by the resource quantity actually extracted "
            "from the validated world deposit; rejected requests change nothing."
        ),
    }
    proposal = SimpleNamespace(
        requested_prompt="Collect and sell world resources to build a ship.",
        game_design={"implementation_blueprint": {
            "requirements": [requirement],
        }},
    )
    assert _source_traced_extraction(owner, proposal)
    requirement["owners"] = ["UnrelatedTradeServer"]
    assert not _source_traced_extraction(owner, proposal)
    requirement["owners"] = [owner.name]
    requirement["acceptance"] = "Display the inventory but never alter it."
    assert not _source_traced_extraction(owner, proposal)
    requirement["acceptance"] = (
        "Extract world minerals into the player's owned inventory."
    )
    proposal.requested_prompt = "A spaceship game without mining or harvesting"
    assert not _source_traced_extraction(owner, proposal)


def test_audited_mining_does_not_steal_unrelated_world_targets():
    from types import SimpleNamespace
    from roblox_mod_ai.host_mining_contract import _source_traced_extraction

    owner = SimpleNamespace(name="OwnedResourceMarketSale4533282Server",
                            description="Sell ore for credits.")
    proposal = SimpleNamespace(
        requested_prompt="Mine world ore and trade it.",
        game_design={"implementation_blueprint": {"requirements": [{
            "source": "Sell mining products.",
            "owners": [owner.name],
            "acceptance": (
                "After the world resource extraction the player receives "
                "owned ore inventory."
            ),
        }]}},
    )
    assert not _source_traced_extraction(owner, proposal)



def test_source_owned_quantity_accounting_materializes_real_node_and_miner():
    from roblox_mod_ai.spec import (
        ModuleKind, RobloxModuleSpec, RobloxProposal,
    )
    from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
    from roblox_mod_ai.host_mining import render_host_mining

    server_name = "SourceOwnedExtraction820a4533281Server"
    client_name = "SourceOwnedExtraction820a4533281Client"
    remote = "SourceOwnedExtraction820a4533281Action"
    server = RobloxModuleSpec(
        module_id="dyn_extract_s", name=server_name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/SourceOwnedExtraction820a4533281Server.luau",
        roblox_service="ServerScriptService",
        description="Server transfers the resource quantity to owned inventory.",
    )
    client = RobloxModuleSpec(
        module_id="dyn_extract_c", name=client_name,
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/SourceOwnedExtraction820a4533281Client.client.luau",
        roblox_service="StarterPlayerScripts",
        description="Client requests a resource extraction.",
    )
    design = {
        "world_objects": [],
        "host_actions": {
            remote: {"service": server_name, "kind": "RemoteFunction",
                     "max_args": 2}
        },
        "remotes": {remote: "RemoteFunction"},
        "host_typed_actions": {remote: {
            "server": server_name,
            "client": client_name,
            "transport_only": True,
            "contract": {
                "inputs": [{"id": "selection"}, {"id": "quantity"}],
                "target": {"kind": "none"},
                "state_changes": [],
            },
        }},
        "module_world_objects": {
            server.module_id: [], client.module_id: [],
        },
        "module_remotes": {
            server.module_id: [remote], client.module_id: [remote],
        },
    }
    proposal = RobloxProposal(
        requested_prompt="Extract resources from world deposits to construct a ship.",
        game_title="GenericResourceVehicle",
        description="Test",
        game_design={
            "dynamic_design": design,
            "implementation_blueprint": {"requirements": [{
                "source": "Gather world resources.",
                "owners": [server_name, client_name],
                "acceptance": (
                    "Accepted world-resource extraction adds the actually "
                    "extracted mineral quantity to the player's owned inventory "
                    "from a validated deposit."
                ),
            }]},
        },
        modules=[server, client],
    )
    changes = ensure_mining_world_contract(proposal)
    assert len(changes) == 1
    assert changes[0]["transport_rebased"] is True
    assert changes[0]["resource_node"] in design["module_world_objects"][server.module_id]
    assert design["host_actions"][remote]["max_args"] == 0
    assert remote not in design["host_typed_actions"]
    assert render_host_mining(server, proposal) is not None
    assert render_host_mining(client, proposal) is not None



def test_mining_to_assembled_vehicle_to_launch_is_one_host_actor():
    """Regression for preflight failure on disjoint Craft and assembled ship."""
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
    from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
    from roblox_mod_ai.host_vehicle_actor_capability import eligible_vehicle_actor_builder
    from roblox_mod_ai.vehicle_identity_binding import (
        bind_verified_vehicle_providers, materialize_source_linked_space_arrivals,
    )
    from roblox_mod_ai.vehicle_identity_contract import vehicle_identity_errors
    from roblox_mod_ai.host_ship_attachment import try_ship_attachment
    from roblox_mod_ai.host_vehicle_departure import eligible_departure

    names = (
        "SourceOwnedExtraction820a4533281",
        "AttachShipSection4533283",
        "LaunchCraftIntoSpace52E67D1",
    )
    modules = []
    design = {
        "world_objects": [
            {"name": "Craft52E67D11", "class": "Part",
             "position": [0, 10, 100], "size": [6, 2, 8]},
            {"name": "Occupants52E67D12", "class": "Part",
             "position": [0, 8, 110], "size": [3, 3, 3]},
        ],
        "host_actions": {}, "host_typed_actions": {}, "remotes": {},
        "module_remotes": {}, "module_world_objects": {},
        "host_world_motion": {},
    }
    for idx, stem in enumerate(names):
        srv = stem + "Server"
        cli = stem + "Client"
        remote = stem + "Action"
        desc = [
            "Server transfers the mined resource quantity into owned inventory.",
            "Server attaches spaceship sections using mined owned resources.",
            "Server launches a spacecraft and keeps passengers aboard.",
        ][idx]
        server = RobloxModuleSpec(
            module_id=f"dyn_feature_{idx}_server", name=srv,
            kind=ModuleKind.SERVER_MODULE,
            file_path=f"src/server/{srv}.luau",
            roblox_service="ServerScriptService", description=desc,
        )
        client = RobloxModuleSpec(
            module_id=f"dyn_feature_{idx}_client", name=cli,
            kind=ModuleKind.CLIENT_SCRIPT,
            file_path=f"src/client/{cli}.client.luau",
            roblox_service="StarterPlayerScripts", description=desc,
        )
        modules.extend((server, client))
        design["host_actions"][remote] = {
            "service": srv, "kind": "RemoteFunction", "max_args": 2,
        }
        design["remotes"][remote] = "RemoteFunction"
        design["host_typed_actions"][remote] = {
            "server": srv, "client": cli, "transport_only": True,
            "contract": {"inputs": [
                {"id": "selection"}, {"id": "quantity"},
            ], "target": {"kind": "none"}, "state_changes": []},
        }
        design["module_remotes"][server.module_id] = [remote]
        design["module_remotes"][client.module_id] = [remote]
        design["module_world_objects"][server.module_id] = (
            ["Craft52E67D11", "Occupants52E67D12"] if idx == 2 else []
        )
        design["module_world_objects"][client.module_id] = (
            ["Craft52E67D11", "Occupants52E67D12"] if idx == 2 else []
        )

    design["host_world_motion"][names[2] + "Server"] = {
        "kind": "vehicle_world_transition",
        "destination": "orbit",
        "occupant_rule": "keep occupants aboard",
    }
    req = {
        "source": "Mine resources and build a ship, then launch with passengers.",
        "owners": [m.name for m in modules],
        "acceptance": (
            "After world-resource extraction the player's owned inventory "
            "increases by the actually extracted quantity from a world deposit. "
            "The owned spaceship has one additional section attached by the "
            "server. The craft travels into space with occupants aboard."
        ),
    }
    proposal = RobloxProposal(
        requested_prompt="Mine resources, construct spacecraft sections and launch.",
        game_title="GenericVehicleProducer",
        description="Preflight integration fixture",
        game_design={
            "dynamic_design": design,
            "implementation_blueprint": {"requirements": [req]},
        },
        modules=modules,
    )
    mining = ensure_mining_world_contract(proposal)
    assert len(mining) == 1 and mining[0]["transport_rebased"]
    assert eligible_vehicle_actor_builder(modules[2], proposal) == "section_attachment"
    links = bind_verified_vehicle_providers(proposal)
    assert len(links) == 1
    assert links[0]["actor_provider"] == "GetOwnedActor"
    assert vehicle_identity_errors(proposal) == []
    arrivals = materialize_source_linked_space_arrivals(proposal)
    assert len(arrivals) == 1
    assert eligible_departure(modules[4], proposal) is not None

    class FixedCatalog:
        def complete_json(self, *args, **kwargs):
            return {"sections": [
                {"id": "Hull", "label": "Hull", "cost": 10, "performance": 2},
                {"id": "Engine", "label": "Engine", "cost": 20, "performance": 3},
                {"id": "Cabin", "label": "Cabin", "cost": 30, "performance": 4},
            ]}
    generated = try_ship_attachment(modules[2], proposal, FixedCatalog())
    assert generated is not None
    assert "function Service.GetOwnedActor(player)" in generated
    assert 'seat.Name = "PilotSeat"' in generated
    assert 'joint.Name = "SectionWeld"' in generated
    client_source = try_ship_attachment(modules[3], proposal, FixedCatalog())
    assert client_source is not None
    assert names[1] + "Action" in client_source
    from roblox_mod_ai.host_vehicle_departure import render_departure
    departure_source = render_departure(modules[4], proposal)
    assert departure_source is not None
    assert "GetOwnedActor(player)" in departure_source
    assert names[1] + "Server" in departure_source



def test_world_action_mining_is_recognized_without_inventing_a_second_node():
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
    from roblox_mod_ai.host_mining_contract import (
        ensure_mining_world_contract, inspect_mining_contract_gates,
    )
    from roblox_mod_ai.host_mining import render_host_mining

    server = RobloxModuleSpec(
        module_id="dyn_extract_from_world",
        name="GatherDepositServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/GatherDepositServer.luau",
        roblox_service="ServerScriptService",
        description="Server harvests resources from a world deposit into owned inventory.",
    )
    design = {
        "world_objects": [{
            "name": "HarvestableDeposit",
            "class": "Part",
            "position": [14, 3, 0],
            "size": [4, 4, 4],
        }],
        "host_actions": {},
        "host_world_actions": {"HarvestableDeposit": {
            "service": server.name, "kind": "ProximityPrompt",
        }},
        "module_world_objects": {server.module_id: []},
    }
    proposal = RobloxProposal(
        requested_prompt="Gather resources from world deposits.",
        game_title="GenericGatheringWorldAction", description="Test",
        game_design={
            "dynamic_design": design,
            "implementation_blueprint": {"requirements": [{
                "source": "Gather the mineral from an actual world node.",
                "owners": [server.name],
                "acceptance": (
                    "The player's owned inventory receives resources "
                    "extracted from a validated world deposit."
                ),
            }]},
        },
        modules=[server],
    )
    before_count = len(design["world_objects"])
    changed = ensure_mining_world_contract(proposal)
    assert len(changed) == 1
    assert changed[0]["resource_node"] == "HarvestableDeposit"
    assert changed[0]["input"] == "host_verified_world_action_Part"
    assert len(design["world_objects"]) == before_count
    assert design["module_world_objects"][server.module_id] == [
        "HarvestableDeposit",
    ]
    source = render_host_mining(server, proposal)
    assert source is not None and "HarvestableDeposit" in source
    gates = inspect_mining_contract_gates(proposal)
    assert len(gates) == 1
    assert gates[0]["host_mining_renderer_eligible"] is True


def test_world_mining_route_must_not_take_non_part_or_another_service():
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
    from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract

    server = RobloxModuleSpec(
        module_id="dyn_gather", name="GatherDepositServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/GatherDepositServer.luau",
        roblox_service="ServerScriptService",
        description="Server harvests resources from world nodes into owned inventory.",
    )
    design = {
        "world_objects": [{
            "name": "HarvestableDeposit", "class": "Model",
            "position": [14, 3, 0], "size": [4, 4, 4],
        }],
        "host_world_actions": {
            "HarvestableDeposit": {
                "service": server.name, "kind": "ProximityPrompt",
            },
        },
        "host_actions": {},
        "module_world_objects": {server.module_id: []},
    }
    proposal = RobloxProposal(
        requested_prompt="Harvest world resources.",
        game_title="NegativeMiningFixture", description="Test",
        game_design={"dynamic_design": design},
        modules=[server],
    )
    assert ensure_mining_world_contract(proposal) == []
    assert design["module_world_objects"][server.module_id] == []
    assert len(design["world_objects"]) == 1



def test_source_traced_generic_resource_event_can_use_host_mining():
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
    from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
    from roblox_mod_ai.host_mining import render_host_mining

    stem = "SourceOwnedExtraction"
    server = RobloxModuleSpec(
        module_id="dyn_s", name=stem + "Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/SourceOwnedExtractionServer.luau",
        roblox_service="ServerScriptService",
        description="Server transfers extracted resources into owned inventory.",
    )
    client = RobloxModuleSpec(
        module_id="dyn_c", name=stem + "Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/SourceOwnedExtractionClient.client.luau",
        roblox_service="StarterPlayerScripts",
        description="Client requests a harvest.",
    )
    remote = "ExtractResourceAction"
    design = {
        "world_objects": [], "host_actions": {remote: {
            "service": server.name, "kind": "RemoteEvent",
            "max_args": 2,
        }},
        "host_typed_actions": {remote: {
            "server": server.name, "client": client.name,
            "transport_only": True,
            "contract": {
                "target": {"kind": "none"}, "state_changes": [],
                "inputs": [{"id": "selection"}, {"id": "quantity"}],
            },
        }},
        "remotes": {remote: "RemoteEvent"},
        "module_world_objects": {
            server.module_id: [], client.module_id: [],
        },
        "module_remotes": {
            server.module_id: [remote], client.module_id: [remote],
        },
    }
    proposal = RobloxProposal(
        requested_prompt="Gather world resources and use them to build vehicles.",
        game_title="GenericGatherer", description="Test",
        game_design={
            "dynamic_design": design,
            "implementation_blueprint": {"requirements": [{
                "source": "Gather world resources into the inventory.",
                "owners": [server.name, client.name],
                "acceptance": (
                    "Extracted world resources increase the player's owned "
                    "inventory only after the server validates a deposit."
                ),
            }]},
        },
        modules=[server, client],
    )
    changes = ensure_mining_world_contract(proposal)
    assert len(changes) == 1 and changes[0]["transport_rebased"]
    assert design["host_actions"][remote]["kind"] == "RemoteFunction"
    assert design["remotes"][remote] == "RemoteFunction"
    assert design["host_actions"][remote]["max_args"] == 0
    assert remote not in design["host_typed_actions"]
    assert render_host_mining(server, proposal) is not None
    assert render_host_mining(client, proposal) is not None


def test_nontransport_resource_event_retains_its_original_contract():
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal
    from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract

    server = RobloxModuleSpec(
        module_id="dyn_server", name="GatherResourceServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/GatherResourceServer.luau",
        roblox_service="ServerScriptService",
        description="Server gathers owned ore from world deposits.",
    )
    design = {
        "world_objects": [], "host_actions": {"GatherAction": {
            "service": server.name, "kind": "RemoteEvent",
        }},
        "host_typed_actions": {"GatherAction": {
            "server": server.name, "transport_only": False,
            "contract": {"inputs": [{"id": "resourceId"}]},
        }},
        "remotes": {"GatherAction": "RemoteEvent"},
        "module_world_objects": {server.module_id: []},
    }
    proposal = RobloxProposal(
        requested_prompt="Gather resources from world deposits.",
        game_title="ActualEventContract", description="Test",
        game_design={"dynamic_design": design}, modules=[server],
    )
    assert ensure_mining_world_contract(proposal) == []
    assert design["host_actions"]["GatherAction"]["kind"] == "RemoteEvent"
    assert design["world_objects"] == []
