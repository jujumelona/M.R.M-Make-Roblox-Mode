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
    assert 'InvokeServer("launch")' in departure_ui


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
