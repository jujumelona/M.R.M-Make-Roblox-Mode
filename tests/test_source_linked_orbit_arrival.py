"""Regression: ship builder -> actual Model departure needs a real arrival Part."""
from types import SimpleNamespace

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.vehicle_identity_binding import materialize_source_linked_space_arrivals
from roblox_mod_ai.host_vehicle_departure import eligible_departure
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols


def _mod(name, ident, kind, description):
    return SimpleNamespace(
        name=name, module_id=ident, kind=kind, description=description,
        file_path=("src/client/" + name + ".client.luau"
                   if kind == ModuleKind.CLIENT_SCRIPT
                   else "src/server/" + name + ".luau"),
    )


def _plan():
    builder = _mod("ModularShipServer", "dyn_ship",
                   ModuleKind.SERVER_MODULE,
                   "Attach each parent part in build order to assemble a ship and persist changes.")
    builder_ui = _mod("ModularShipClient", "dyn_ship_ui",
                      ModuleKind.CLIENT_SCRIPT, "Ship assembly user interface")
    launch = _mod("LaunchCraftServer", "dyn_launch",
                  ModuleKind.SERVER_MODULE,
                  "Launch an assembled spacecraft into space with its occupants aboard.")
    launch_ui = _mod("LaunchCraftClient", "dyn_launch_ui",
                     ModuleKind.CLIENT_SCRIPT, "Space launch action")
    plan = SimpleNamespace(
        modules=[builder, builder_ui, launch, launch_ui],
        game_design={"dynamic_design": {
            "world_objects": [
                {"name": "SHIPROOT", "class": "Part", "position": [1, 2, 3], "size": [4, 4, 4]},
                {"name": "SHIPPARTENGINE", "class": "Part", "position": [5, 2, 3], "size": [4, 4, 4]},
                {"name": "SHIPPARTCOCKPIT", "class": "Part", "position": [9, 2, 3], "size": [4, 4, 4]},
            ],
            "module_world_objects": {
                builder.module_id: ["SHIPROOT", "SHIPPARTENGINE", "SHIPPARTCOCKPIT"],
                launch.module_id: ["SHIPROOT"],
                launch_ui.module_id: ["SHIPROOT"],
            },
            "remotes": {"BuildAction": "RemoteFunction", "LaunchAction": "RemoteFunction"},
            "host_actions": {
                "BuildAction": {"service": builder.name, "kind": "RemoteFunction", "max_args": 1},
                "LaunchAction": {"service": launch.name, "kind": "RemoteFunction", "max_args": 1},
            },
            "module_remotes": {
                builder.module_id: ["BuildAction"],
                builder_ui.module_id: ["BuildAction"],
                launch.module_id: ["LaunchAction"],
                launch_ui.module_id: ["LaunchAction"],
            },
            "host_typed_actions": {
                "BuildAction": {
                    "server": builder.name, "client": builder_ui.name,
                    "transport_only": True, "world_entities":
                        ["SHIPROOT", "SHIPPARTENGINE", "SHIPPARTCOCKPIT"],
                    "contract": {"inputs": [], "target": {"kind": "none"}, "state_changes": []},
                },
                "LaunchAction": {
                    "server": launch.name, "client": launch_ui.name,
                    "transport_only": True, "world_entities": ["SHIPROOT"],
                    "contract": {"inputs": [], "target": {"kind": "none"}, "state_changes": []},
                },
            },
            "host_world_motion": {
                launch.name: {
                    "kind": "vehicle_world_transition",
                    "destination": "playable space / orbit",
                    "actor_world_name": "SHIPROOT",
                    "builder_module_id": builder.module_id,
                }
            },
        }},
    )
    return plan, launch, launch_ui


def test_real_orbit_arrival_enables_full_host_departure_handoff():
    plan, launch, client = _plan()
    assert eligible_departure(launch, plan) is None
    created = materialize_source_linked_space_arrivals(plan)
    assert len(created) == 1
    arrival = created[0]["arrival"]
    design = plan.game_design["dynamic_design"]
    assert arrival in design["module_world_objects"][launch.module_id]
    assert arrival in design["module_world_objects"][client.module_id]
    assert any(obj["name"] == arrival and obj["class"] == "Part"
               for obj in design["world_objects"])
    assert eligible_departure(launch, plan) is not None
    assert eligible_departure(client, plan) is not None
    assert materialize_source_linked_space_arrivals(plan) == []
    assert len([obj for obj in design["world_objects"] if obj["name"] == arrival]) == 1
    scope = generation_scope(plan)
    strategy = {row["name"]: row["strategy"] for row in scope["modules"]}
    assert strategy[launch.name] == "host_declarative_vehicle_departure"
    assert strategy[client.name] == "host_declarative_vehicle_departure"
    rebased = rebase_complete_host_protocols(plan, scope)
    assert len(rebased) == 1 and rebased[0]["remote"] == "LaunchAction"
    assert "LaunchAction" not in design["host_typed_actions"]
    assert "LaunchAction" in design["host_launch_contracts"]


def test_missing_verified_builder_does_not_fabricate_space_arrival():
    plan, launch, _ = _plan()
    plan.game_design["dynamic_design"]["host_world_motion"][launch.name][
        "builder_module_id"] = "dyn_unknown"
    before = list(plan.game_design["dynamic_design"]["world_objects"])
    assert materialize_source_linked_space_arrivals(plan) == []
    assert plan.game_design["dynamic_design"]["world_objects"] == before
