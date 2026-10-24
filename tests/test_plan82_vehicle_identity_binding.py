"""Plan82: verified host should REPAIR unique builder->launcher world identity.

Previously resolver rejected 9.77 ms after compilation. The hosted scene
already had one builder's physical root, but the launcher pointed at a separate
placeholder. The host owns the identities, so it can rebind the exact existing
root to both server AND client before codegen without another model call.

These are cross-genre physical-actor contracts, not bespoke source prompts.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.vehicle_identity_binding import bind_vehicle_actors
from roblox_mod_ai.vehicle_identity_contract import vehicle_identity_errors


def fixture(*, roots=("VehicleRootAlpha",), old="CraftProxyBeta",
            with_client=True):
    b = NS(name="Assembler", module_id="dyn_assembly",
           file_path="src/server/Assembler.luau",
           description="Server builds an assembled vehicle with fitted modules")
    s = NS(name="Departure", module_id="dyn_depart",
           file_path="src/server/Departure.luau",
           description="Server transports passengers and their craft")
    c = NS(name="DepartureClient", module_id="dyn_depart_ui",
           file_path="src/client/DepartureClient.client.luau",
           description="User launches the vehicle")
    unrelated = NS(name="Miner", module_id="dyn_mine",
                   file_path="src/server/Miner.luau",
                   description="Server collects resources")
    modules = [b, s, unrelated] + ([c] if with_client else [])
    source_world = list(roots) + [
        "ResourceNodeOther", "VehicleAttachedWing", old, "CrewSeatsBeta",
    ]
    world_objects = [{"name": name, "class": "Part"} for name in source_world]
    linked = {
        b.module_id: list(roots) + ["ResourceNodeOther", "VehicleAttachedWing"],
        s.module_id: [old, "CrewSeatsBeta"],
        unrelated.module_id: ["ResourceNodeOther"],
    }
    if with_client:
        linked[c.module_id] = [old, "CrewSeatsBeta"]
    p = NS(modules=modules, game_design={"dynamic_design": {
        "world_objects": world_objects,
        "module_world_objects": linked,
        "host_world_motion": {
            s.name: {"kind": "vehicle_world_transition",
                     "actor": "owned vehicle"}
        },
        "host_typed_actions": {
            "MoveRoute": {
                "server": s.name, "client": c.name,
                "contract": {"inputs": [], "target": {"kind": "none"},
                             "state_changes": []},
                "transport_only": True,
            },
        },
    }})
    return p


def test_uniquely_materialized_builder_root_rebinds_both_ends_atomically():
    p = fixture()
    d = p.game_design["dynamic_design"]
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in issue
               for issue in vehicle_identity_errors(p))
    changes = bind_vehicle_actors(p)
    assert len(changes) == 1
    assert changes[0]["actor"] == "VehicleRootAlpha"
    assert changes[0]["replaced_placeholder"] == "CraftProxyBeta"
    assert changes[0]["physical_assembly_verified"] is False
    assert d["module_world_objects"]["dyn_depart"] == [
        "VehicleRootAlpha", "CrewSeatsBeta"]
    assert d["module_world_objects"]["dyn_depart_ui"] == [
        "VehicleRootAlpha", "CrewSeatsBeta"]
    assert d["module_world_objects"]["dyn_mine"] == ["ResourceNodeOther"]
    assert d["host_world_motion"]["Departure"]["actor_world_name"] == "VehicleRootAlpha"
    assert d["host_world_motion"]["Departure"]["actor_world_class"] == "Part"
    assert vehicle_identity_errors(p) == []
    assert bind_vehicle_actors(p) == []
    assert len(d["host_vehicle_identity_bindings"]) == 1


def test_actual_failure_shape_shiproot_and_separate_craft_proxy():
    p = fixture(roots=("SHIPROOT45332831",), old="Craft52E67D11")
    results = bind_vehicle_actors(p)
    assert len(results) == 1
    assert results[0]["actor"] == "SHIPROOT45332831"
    assert vehicle_identity_errors(p) == []


def test_ambiguous_multiple_physical_roots_never_guessed():
    p = fixture(roots=("VehicleRootAlpha", "VehicleRootGamma"))
    previous = list(p.game_design["dynamic_design"][
        "module_world_objects"]["dyn_depart"])
    assert bind_vehicle_actors(p) == []
    assert p.game_design["dynamic_design"][
        "module_world_objects"]["dyn_depart"] == previous
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in x
               for x in vehicle_identity_errors(p))


def test_missing_pair_is_not_half_bound():
    p = fixture(with_client=False)
    previous = dict(p.game_design["dynamic_design"]["module_world_objects"])
    assert bind_vehicle_actors(p) == []
    assert p.game_design["dynamic_design"]["module_world_objects"] == previous


def test_unrelated_vehicle_without_root_is_not_invented():
    p = fixture(roots=("DecorativeWing",))
    assert bind_vehicle_actors(p) == []
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in x
               for x in vehicle_identity_errors(p))


def test_nonphysical_world_name_not_selected_as_root():
    p = fixture()
    d = p.game_design["dynamic_design"]
    d["world_objects"][0]["class"] = "Folder"
    assert bind_vehicle_actors(p) == []
    assert any("VEHICLE_ACTOR_NOT_BUILT_OBJECT" in x
               for x in vehicle_identity_errors(p))



def test_rebound_server_with_stale_client_is_still_rejected():
    p = fixture()
    assert len(bind_vehicle_actors(p)) == 1
    d = p.game_design["dynamic_design"]
    d["module_world_objects"]["dyn_depart_ui"] = ["CraftProxyBeta"]
    problems = vehicle_identity_errors(p)
    assert any("VEHICLE_ACTOR_CLIENT_NOT_BOUND" in x for x in problems), problems


def test_root_class_mismatch_is_not_hidden_by_shared_name():
    p = fixture()
    assert len(bind_vehicle_actors(p)) == 1
    p.game_design["dynamic_design"]["host_world_motion"][
        "Departure"]["actor_world_class"] = "Model"
    assert any("VEHICLE_ACTOR_CLASS_MISMATCH" in x
               for x in vehicle_identity_errors(p))
