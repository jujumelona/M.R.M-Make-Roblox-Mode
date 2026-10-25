"""General ordered construction -> passenger-preserving departure protocol.

This tests REAL host Luau generation from catalog DATA and the exported actor
provider ABI. No static scene dummy Part may masquerade as an assembled model.
"""
from types import SimpleNamespace as NS
import pytest

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.host_ordered_assembly import (
    eligible_ordered_assembly, render_ordered_assembly, _validate,
)
from roblox_mod_ai.host_vehicle_departure import eligible_departure, render_departure
from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols


class CatalogModel:
    calls = 0

    def complete_json(self, *args, **kwargs):
        self.calls += 1
        assert kwargs["role"] == "planner"
        assert kwargs["max_tokens"] <= 650
        return {"sections": [
            {"id": "Vehicle_PART_HULL", "parent": "Vehicle_ROOT",
             "label": "Hull", "cost": 10, "performance": 1},
            {"id": "Vehicle_PART_ENGINE", "parent": "Vehicle_PART_HULL",
             "label": "Engine", "cost": 20, "performance": 2},
        ]}


def sample():
    build = NS(
        name="ConstructionServer", module_id="dyn_builder",
        file_path="src/server/ConstructionServer.luau",
        kind=ModuleKind.SERVER_MODULE, code="",
        description="Server assembly uses a required parent part and a "
        "required attachment point, validates the build order, and persists "
        "saved construction state and costs.",
    )
    build_ui = NS(
        name="ConstructionClient", module_id="dyn_builder_ui",
        file_path="src/client/ConstructionClient.client.luau",
        kind=ModuleKind.CLIENT_SCRIPT, code="", description="Assembly UI",
    )
    move = NS(
        name="DepartureServer", module_id="dyn_launch",
        file_path="src/server/DepartureServer.luau",
        kind=ModuleKind.SERVER_MODULE, code="",
        description="Depart in the assembled vehicle, carrying occupants.",
    )
    move_ui = NS(
        name="DepartureClient", module_id="dyn_launch_ui",
        file_path="src/client/DepartureClient.client.luau",
        kind=ModuleKind.CLIENT_SCRIPT, code="", description="Departure UI",
    )
    ids = ["Vehicle_ROOT", "Vehicle_PART_HULL", "Vehicle_PART_ENGINE"]
    routes = [
        ("ConstructionRoute", build, build_ui, ids),
        ("DepartureRoute", move, move_ui,
         ["Vehicle_ROOT", "VehicleArrivalZone"]),
    ]
    form = {}
    host = {}
    remote_kinds = {}
    links = {}
    for route, server, client, entities in routes:
        host[route] = {"service": server.name, "kind": "RemoteFunction",
                       "max_args": 1}
        remote_kinds[route] = "RemoteFunction"
        form[route] = {
            "server": server.name, "client": client.name,
            "transport_only": True, "world_entities": entities,
            "contract": {"inputs": [], "target": {"kind": "none"},
                         "state_changes": []},
        }
        links[server.module_id] = [route]
        links[client.module_id] = [route]
    world = [
        {"name": name, "class": "Part"} for name in (
            "Vehicle_ROOT", "Vehicle_PART_HULL", "Vehicle_PART_ENGINE",
            "VehicleArrivalZone",
        )
    ]
    p = NS(
        modules=[build, build_ui, move, move_ui],
        game_design={"dynamic_design": {
            "host_actions": host, "remotes": remote_kinds,
            "host_typed_actions": form, "module_remotes": links,
            "world_objects": world,
            "host_world_motion": {move.name: {
                "kind": "vehicle_world_transition",
                "builder_module_id": build.module_id,
                "actor_world_name": "Vehicle_ROOT",
            }},
            "module_world_objects": {
                build.module_id: ids,
                build_ui.module_id: ids,
                move.module_id: ["Vehicle_ROOT", "VehicleArrivalZone"],
                move_ui.module_id: ["Vehicle_ROOT", "VehicleArrivalZone"],
            },
        }}
    )
    return p, build, build_ui, move, move_ui


def test_both_server_and_client_use_verified_host_protocol():
    p, b, bc, m, mc = sample()
    assert eligible_ordered_assembly(b, p)
    assert eligible_ordered_assembly(bc, p)
    assert eligible_departure(m, p)
    assert eligible_departure(mc, p)
    scope = {"modules": [
        {"name": x.name, "strategy": strategy}
        for x, strategy in (
            (b, "host_declarative_ordered_assembly"),
            (bc, "host_declarative_ordered_assembly"),
            (m, "host_declarative_vehicle_departure"),
            (mc, "host_declarative_vehicle_departure"),
        )
    ]}
    changes = rebase_complete_host_protocols(p, scope)
    assert {row["protocol"] for row in changes} == {
        "host_declarative_ordered_assembly", "host_declarative_vehicle_departure"
    }
    assert eligible_ordered_assembly(b, p)
    assert eligible_departure(m, p)

    model = CatalogModel()
    builder = render_ordered_assembly(b, p, model)
    builder_ui = render_ordered_assembly(bc, p, model)
    departure = render_departure(m, p)
    departure_ui = render_departure(mc, p)
    assert model.calls == 1  # one compact JSON, no AI Luau calls
    assert "local function placePart" in builder
    assert "WeldConstraint" in builder
    assert 'if ship then ship:Destroy() end' in builder
    assert 'local position = layout[definition.ordinal]' in builder
    # The compiler must emit one spatial cell per ACTUAL declared section;
    # padding every model to the old fixed eight-piece ship layout is wrong.
    for ordinal in range(1, 3):
        assert f'[{ordinal}] = {{Vector3.new(' in builder
    assert '[3] = {Vector3.new(' not in builder
    assert "local ROOT_ID = " in builder
    assert '["Vehicle_PART_ENGINE"]' in builder
    assert 'parent = "Vehicle_PART_HULL"' in builder
    assert 'reason = "parent_not_built"' in builder
    assert 'function Service.GetOwnedActor(player)' in builder
    assert 'Instance.new("VehicleSeat")' in builder
    assert 'local ship = shipModels[player]' in builder
    assert 'function Service.handleAction' in builder
    assert 'inventory.resources = resources - definition.cost' in builder
    assert 'return Service' in builder
    assert '"Vehicle_PART_ENGINE"' in builder_ui
    assert ':InvokeServer(section.id)' in builder_ui
    assert 'services.ConstructionServer.GetOwnedActor(player)' in departure
    assert "seat.Occupant~=humanoid" in departure
    assert "vehicle:PivotTo" in departure
    assert '"VehicleArrivalZone"' in departure
    assert 'InvokeServer(action)' in departure_ui
    assert 'Return to ground' in departure_ui


def test_invalid_parent_graph_fails_without_writing_luau():
    bad = {"sections": [
        {"id": "Vehicle_PART_HULL", "parent": "Vehicle_PART_ENGINE",
         "label": "Hull", "cost": 10, "performance": 1},
        {"id": "Vehicle_PART_ENGINE", "parent": "Vehicle_ROOT",
         "label": "Engine", "cost": 20, "performance": 2},
    ]}
    with pytest.raises(ValueError, match="PARENT"):
        _validate(bad, "Vehicle_ROOT",
                  ["Vehicle_PART_HULL", "Vehicle_PART_ENGINE"])


def test_no_arrival_marker_never_invents_a_destination():
    p, b, bc, move, _ = sample()
    p.game_design["dynamic_design"]["module_world_objects"][move.module_id] = [
        "Vehicle_ROOT"
    ]
    assert eligible_departure(move, p) is None


def test_no_real_builder_contract_never_launches_dummy():
    p, b, bc, move, _ = sample()
    b.description = "Unrelated decorative component"
    assert eligible_departure(move, p) is None


def test_report15_partadded_ship_builds_host_model_before_passenger_launch():
    """Regression from the real failure-15 partial world and action transport."""
    from roblox_mod_ai.vehicle_identity_binding import materialize_source_linked_space_arrivals
    from roblox_mod_ai.vehicle_identity_contract import vehicle_identity_errors
    p, builder, ui, launch, launch_ui = sample()
    builder.description = (
        "Server owns the ship assembly state machine: each part is a "
        "server-authoritative Part with a PartAdded signal that validates "
        "the part's required parent, attachment point, and build order; "
        "on success the server adds the part to the ship's assembly table, "
        "emits a PartAdded event, and applies the performance record."
    )
    ids = [
        "ShipHull", "ShipEngine", "ShipCabin", "ShipCannon",
        "ShipFuelTank", "ShipArmorPlate", "ShipBridge", "ShipThruster",
    ]
    design = p.game_design["dynamic_design"]
    actual = [name + "4533283" + str(i+1) for i, name in enumerate(ids)]
    design["host_typed_actions"]["ConstructionRoute"]["world_entities"] = ids
    design["world_objects"] = [
        {"name": name, "class": "Part",
         "position": [float(24+i*12), 2.0, 24.0],
         "size": [4.0, 4.0, 4.0]}
        for i, name in enumerate(actual)
    ]
    for mod in (builder, ui):
        design["module_world_objects"][mod.module_id] = list(actual)
    for mod in (launch, launch_ui):
        design["module_world_objects"][mod.module_id] = [actual[0]]
    motion = design["host_world_motion"][launch.name]
    motion.update(
        actor_world_name=actual[0], actor_world_class="Part",
        actor_identity_source="unique_host_materialized_builder_root",
        occupant_rule="players remain aboard the vehicle",
        destination="playable space / orbit",
    )
    assert eligible_ordered_assembly(builder, p) == (
        builder.name, "ConstructionRoute", "RMMAssemblyAnchor", ids,
    )
    assert eligible_ordered_assembly(ui, p)
    assert vehicle_identity_errors(p) == []
    arrivals = materialize_source_linked_space_arrivals(p)
    assert len(arrivals) == 1 and arrivals[0]["builder"] == builder.name
    assert "RMMOrbitArrival_" in arrivals[0]["arrival"]
    assert eligible_departure(launch, p)
    assert eligible_departure(launch_ui, p)

    class RealShipData:
        def complete_json(self, *_args, **_kwargs):
            return {"sections": [
                {"id": name,
                 "parent": ids[i-1] if i else "RMMAssemblyAnchor",
                 "label": name, "cost": 10+i, "performance": 1+i}
                for i, name in enumerate(ids)
            ]}

    host = RealShipData()
    builder_code = render_ordered_assembly(builder, p, host)
    launcher_code = render_departure(launch, p)
    assert "function Service.GetOwnedActor(player)" in builder_code
    assert "Instance.new(\"VehicleSeat\")" in builder_code
    assert '["ShipHull"]' in builder_code
    assert '["ShipThruster"]' in builder_code
    assert "services.ConstructionServer.GetOwnedActor(player)" in launcher_code
    assert "vehicle:PivotTo" in launcher_code
    assert arrivals[0]["arrival"] in launcher_code


def test_multiple_craft_proxies_use_verified_owned_model_provider():
    """Failure 20: two Craft Parts must never be arbitrarily chosen as the ship."""
    from roblox_mod_ai.vehicle_identity_binding import (
        bind_verified_vehicle_providers, bind_vehicle_actors,
        materialize_source_linked_space_arrivals,
    )
    from roblox_mod_ai.vehicle_identity_contract import vehicle_identity_errors

    p, builder, _ui, launch, launch_ui = sample()
    builder.description = "Ship construction. " + builder.description
    d = p.game_design["dynamic_design"]
    d["world_objects"].extend([
        {"name": "CraftProxyOne", "class": "Part"},
        {"name": "CraftProxyTwo", "class": "Part"},
        {"name": "OccupantsProxy", "class": "Part"},
    ])
    d["module_world_objects"][launch.module_id] = [
        "CraftProxyOne", "CraftProxyTwo", "OccupantsProxy"]
    d["module_world_objects"][launch_ui.module_id] = [
        "CraftProxyOne", "CraftProxyTwo", "OccupantsProxy"]
    motion = d["host_world_motion"][launch.name]
    motion["destination"] = "playable space / orbit"
    motion["occupant_rule"] = "passengers remain aboard"
    motion["actor_world_name"] = "CraftProxyOne"
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in error
               for error in vehicle_identity_errors(p))
    changes = bind_verified_vehicle_providers(p)
    assert len(changes) == 1
    assert changes[0]["builder"] == builder.name
    assert changes[0]["actor_provider"] == "GetOwnedActor"
    assert changes[0]["physical_assembly_verified"] is False
    assert bind_vehicle_actors(p) == []
    assert motion["actor_identity_source"] == "verified_owned_actor_provider"
    assert motion["builder_module_id"] == builder.module_id
    assert "actor_world_name" not in motion
    # Preserve decorative proxies, never claim one is the physical craft.
    assert d["module_world_objects"][launch.module_id] == [
        "CraftProxyOne", "CraftProxyTwo", "OccupantsProxy"]
    assert vehicle_identity_errors(p) == []
    arrivals = materialize_source_linked_space_arrivals(p)
    assert len(arrivals) == 1
    assert arrivals[0]["builder"] == builder.name
    assert eligible_departure(launch, p) is not None
    assert eligible_departure(launch_ui, p) is not None
    assert "GetOwnedActor(player)" in render_departure(launch, p)
    # Running preflight twice must neither create a second actor nor landing.
    assert bind_verified_vehicle_providers(p) == []
    assert materialize_source_linked_space_arrivals(p) == []
    motion["actor_provider"] = "unverified_placeholder"
    assert any("VEHICLE_ACTOR_PROVIDER_INVALID" in error
               for error in vehicle_identity_errors(p))


def test_multiple_proxies_are_not_connected_without_a_verified_builder():
    from roblox_mod_ai.vehicle_identity_binding import bind_verified_vehicle_providers
    p, builder, _ui, launch, launch_ui = sample()
    builder.description = "Decorative starship icon without assembled state"
    d = p.game_design["dynamic_design"]
    d["world_objects"].extend([
        {"name": "CraftProxyOne", "class": "Part"},
        {"name": "CraftProxyTwo", "class": "Part"},
    ])
    for mod in (launch, launch_ui):
        d["module_world_objects"][mod.module_id] = ["CraftProxyOne", "CraftProxyTwo"]
    assert bind_verified_vehicle_providers(p) == []
    assert eligible_departure(launch, p) is None
