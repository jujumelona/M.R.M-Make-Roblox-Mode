"""Real plan-84 failure: compiled 26-module gameplay had disjoint static
OwnedSpacecraft and AttachShipSection actor world objects.

A source-linked attachment service must export the same actually assembled,
player-owned passenger Model consumed by the departure service. Never equate
a standalone decorative World Part with a boardable spaceship.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.vehicle_identity_binding import (
    bind_verified_vehicle_providers,
    materialize_source_linked_space_arrivals,
)
from roblox_mod_ai.vehicle_identity_contract import vehicle_identity_errors
from roblox_mod_ai.host_ship_attachment import (
    eligible_ship_attachment, try_ship_attachment,
)
from roblox_mod_ai.host_vehicle_departure import eligible_departure, render_departure
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer


class DataOnly:
    def __init__(self):
        self.calls = 0

    def complete_json(self, *args, **kwargs):
        self.calls += 1
        assert kwargs["max_tokens"] <= 950
        return {"sections": [
            {"id": "ShipHull", "label": "Hull", "cost": 5, "performance": 3},
            {"id": "ShipEngine", "label": "Engine", "cost": 10, "performance": 8},
        ]}


def sample(*, terse=False):
    description = (
        "Server attaches ship sections to an owned spaceship, validates "
        "the selected component, and saves the installed sections."
        if terse else
        "The server owns the spaceship assembly state and validates each build. "
        "Player may add a modular section in a valid build context only when "
        "that section is not already present. Server records the attached "
        "section, applies its performance contribution, and persists the "
        "assembly state. Server rejects invalid or duplicate sections outside "
        "the build range."
    )
    builder = NS(name="AttachShipSectionServer", module_id="dyn_build",
                 file_path="src/server/AttachShipSectionServer.luau",
                 kind=ModuleKind.SERVER_MODULE, description=description)
    builder_client = NS(name="AttachShipSectionClient", module_id="dyn_build_ui",
                        file_path="src/client/AttachShipSectionClient.client.luau",
                        kind=ModuleKind.CLIENT_SCRIPT, description="Build section")
    miner = NS(name="MineResourceNodeServer", module_id="dyn_mine",
               file_path="src/server/MineResourceNodeServer.luau",
               kind=ModuleKind.SERVER_MODULE,
               description="Server harvests real resource nodes with proximity and depletion checks.")
    launcher = NS(name="SpaceflightDepartureServer", module_id="dyn_launch",
                  file_path="src/server/SpaceflightDepartureServer.luau",
                  kind=ModuleKind.SERVER_MODULE,
                  description="Server moves assembled spaceship and passengers into orbit.")
    launcher_client = NS(name="SpaceflightDepartureClient", module_id="dyn_launch_ui",
                         file_path="src/client/SpaceflightDepartureClient.client.luau",
                         kind=ModuleKind.CLIENT_SCRIPT, description="Launch craft UI")
    mods = [builder, builder_client, miner, launcher, launcher_client]
    routes = {
        "BuildPart": {"service": builder.name, "kind": "RemoteFunction", "max_args": 1},
        "LaunchCraft": {"service": launcher.name, "kind": "RemoteFunction", "max_args": 1},
        "MineOre": {"service": miner.name, "kind": "RemoteFunction", "max_args": 1},
    }
    typed = {
        route: {"server": server.name, "client": client.name,
                "transport_only": True, "world_entities": objects,
                "contract": {"inputs": [], "target": {"kind": "none"}, "state_changes": []}}
        for route, server, client, objects in [
            ("BuildPart", builder, builder_client, ["ShipHull", "ShipEngine"]),
            ("LaunchCraft", launcher, launcher_client, ["OwnedSpacecraft", "SpaceRegion"]),
        ]
    }
    d = {
        "host_actions": routes,
        "remotes": {k: "RemoteFunction" for k in routes},
        "host_typed_actions": typed,
        "module_remotes": {
            builder.module_id: ["BuildPart"],
            builder_client.module_id: ["BuildPart"],
            launcher.module_id: ["LaunchCraft"],
            launcher_client.module_id: ["LaunchCraft"],
            miner.module_id: ["MineOre"],
        },
        "host_world_motion": {launcher.name: {
            "kind": "vehicle_world_transition",
            "destination": "playable space / orbit",
            "occupant_rule": "all players remain aboard the vehicle",
        }},
        "world_objects": [
            {"name": x, "class": "Part"} for x in (
                "ResourceNode11", "ShipBuildPad11", "OwnedSpacecraft11",
                "SpaceRegion11", "SpaceNavigationControls11",
            )
        ],
        "module_world_objects": {
            builder.module_id: ["ShipBuildPad11"],
            builder_client.module_id: ["ShipBuildPad11"],
            miner.module_id: ["ResourceNode11"],
            launcher.module_id: ["OwnedSpacecraft11", "SpaceRegion11",
                                 "SpaceNavigationControls11"],
            launcher_client.module_id: ["OwnedSpacecraft11", "SpaceRegion11",
                                        "SpaceNavigationControls11"],
        },
    }
    prompt = ("우주모드인데 자원파밍 돈모으기 거래 등으로 "
              "우주선을 부위마다 만들어서 만들수있고 "
              "그렇게해서 우주로 나갈수있고")
    p = NS(modules=mods, requested_prompt=prompt,
           game_design={"dynamic_design": d})
    return p, builder, builder_client, launcher, launcher_client


def test_disjoint_real_world_objects_bind_to_same_real_owned_model():
    p, builder, ui, launcher, launch_ui = sample(terse=True)
    d = p.game_design["dynamic_design"]
    from roblox_mod_ai.host_ship_attachment import _source_linked_section_builder
    from roblox_mod_ai.host_mining import render_host_mining
    assert _source_linked_section_builder(builder, p), "source-linked author / launch relation failed"
    assert render_host_mining(p.modules[2], p) is not None, "mining source unbound"
    assert eligible_ship_attachment(builder, p) is not None
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in error
               for error in vehicle_identity_errors(p))
    changes = bind_verified_vehicle_providers(p)
    assert len(changes) == 1
    assert changes[0]["builder"] == builder.name
    assert changes[0]["actor_provider"] == "GetOwnedActor"
    motion = d["host_world_motion"][launcher.name]
    assert motion["actor_identity_source"] == "verified_owned_actor_provider"
    assert motion["builder_module_id"] == builder.module_id
    assert d["host_flight_ready_builders"][builder.name] == "section_attachment"
    assert "actor_world_name" not in motion
    assert vehicle_identity_errors(p) == []
    assert d["module_world_objects"][launcher.module_id][0] == "OwnedSpacecraft11"

    arrivals = materialize_source_linked_space_arrivals(p)
    assert len(arrivals) == 1
    assert eligible_departure(launcher, p)
    assert eligible_departure(launch_ui, p)
    preliminary = generation_scope(p, for_protocol_handoff=True)
    strategies = {row["name"]: row["strategy"] for row in preliminary["modules"]}
    assert strategies[builder.name] == "host_declarative_ship_attachment"
    assert strategies[ui.name] == "host_declarative_ship_attachment"
    assert strategies[launcher.name] == "host_declarative_vehicle_departure"
    assert strategies[launch_ui.name] == "host_declarative_vehicle_departure"

    rebase_complete_host_protocols(p, preliminary)
    model = DataOnly()
    assembly = try_ship_attachment(builder, p, model)
    client_code = try_ship_attachment(ui, p, model)
    flight = render_departure(launcher, p)
    flight_ui = render_departure(launch_ui, p)
    assert model.calls == 1
    assert 'function Service.GetOwnedActor(player)' in assembly
    assert 'Instance.new("VehicleSeat")' in assembly
    assert 'Instance.new("WeldConstraint")' in assembly
    assert "seat:Sit(humanoid)" in assembly
    assert "part.Anchored = false" in assembly
    assert "GetState(player, \"RMMShipSections\")" in assembly
    assert "profile.sections[id]" in assembly
    assert "GetOwnedActor(player)" in flight
    assert "vehicle:PivotTo(" in flight
    assert arrivals[0]["arrival"] in flight
    assert "BoardVehicle" in assembly
    assert 'remote:InvokeServer(section.id)' in client_code
    assert 'InvokeServer(action)' in flight_ui
    assert not [e for e in LuauStaticAnalyzer().analyze_source(
        assembly, builder.file_path) if e.severity == "ERROR"]


def test_no_launch_does_not_silently_enable_a_flying_model():
    p, builder, _ui, launcher, _client = sample(terse=True)
    p.game_design["dynamic_design"]["host_world_motion"].clear()
    assert eligible_ship_attachment(builder, p) is None
    assert bind_verified_vehicle_providers(p) == []


def test_missing_mining_implementation_never_claims_launchable_ship():
    p, builder, _ui, launcher, _client = sample(terse=True)
    p.game_design["dynamic_design"]["module_world_objects"]["dyn_mine"] = []
    assert eligible_ship_attachment(builder, p) is None
    assert bind_verified_vehicle_providers(p) == []


def test_does_not_guess_builder_when_two_independent_vehicles_match():
    p, builder, ui, launcher, launch_ui = sample(terse=True)
    from copy import copy
    another = copy(builder)
    another.name = "SecondShipAssemblyServer"
    another.module_id = "dyn_build2"
    another.file_path = "src/server/SecondShipAssemblyServer.luau"
    p.modules.append(another)
    d = p.game_design["dynamic_design"]
    d["host_actions"]["Build2"] = {
        "service": another.name, "kind": "RemoteFunction", "max_args": 1}
    d["remotes"]["Build2"] = "RemoteFunction"
    d["module_remotes"][another.module_id] = ["Build2"]
    d["module_world_objects"][another.module_id] = ["ShipBuildPad11"]
    assert bind_verified_vehicle_providers(p) == []
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in e
               for e in vehicle_identity_errors(p))


def test_without_verified_pair_no_cross_stage_identity_success():
    p, builder, ui, launcher, launch_ui = sample(terse=True)
    p.game_design["dynamic_design"]["host_typed_actions"]["LaunchCraft"]["client"] = "ImaginaryUI"
    assert bind_verified_vehicle_providers(p) == []
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in e
               for e in vehicle_identity_errors(p))


def test_actual_failure_prompt_invariance_after_host_protocol_handoff():
    """Failure (12): four host routes must never depend on raw prompt tokens."""
    from roblox_mod_ai.generation_scope import assert_prompt_invariant_routing
    p, builder, ui, departure, departure_ui = sample(terse=True)
    assert bind_verified_vehicle_providers(p)
    assert materialize_source_linked_space_arrivals(p)
    preliminary = generation_scope(p, for_protocol_handoff=True)
    rebase_complete_host_protocols(p, preliminary)
    real = generation_scope(p)
    by_name = {r["name"]: r["strategy"] for r in real["modules"]}
    assert by_name[builder.name] == "host_declarative_ship_attachment"
    assert by_name[ui.name] == "host_declarative_ship_attachment"
    assert by_name[departure.name] == "host_declarative_vehicle_departure"
    assert by_name[departure_ui.name] == "host_declarative_vehicle_departure"
    # This assertion produced PROMPT_DEPENDENT_GENERATOR_ROUTE in the
    # uploaded failure bundle even though the vehicle provider was valid.
    assert_prompt_invariant_routing(p, original_scope=real)
    previous = p.requested_prompt
    p.requested_prompt = "[raw prompt withheld: use validated contracts]"
    try:
        after = generation_scope(p)
        assert {r["module_id"]: r["strategy"] for r in real["modules"]} == {
            r["module_id"]: r["strategy"] for r in after["modules"]}
        assert eligible_ship_attachment(builder, p) is not None
        assert eligible_departure(departure, p)
    finally:
        p.requested_prompt = previous


def test_unverified_extra_launch_without_unique_source_contract_rejected():
    p, builder, _ui, departure, _client = sample(terse=True)
    d = p.game_design["dynamic_design"]
    d["host_world_motion"]["SecondLaunchServer"] = {
        "kind": "vehicle_world_transition",
        "destination": "playable space",
    }
    d["host_actions"]["SecondLaunch"] = {
        "service": "SecondLaunchServer", "kind": "RemoteFunction"
    }
    d["remotes"]["SecondLaunch"] = "RemoteFunction"
    d["host_typed_actions"]["SecondLaunch"] = {
        "transport_only": True, "server": "SecondLaunchServer",
        "client": "ImaginaryLaunchClient",
    }
    # Multiple launch motions make a short model-authored builder ambiguous.
    assert eligible_ship_attachment(builder, p) is None
