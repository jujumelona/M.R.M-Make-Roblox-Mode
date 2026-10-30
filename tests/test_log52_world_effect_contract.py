"""Log52 regression: source-owned Part combat must use verified host code.

These tests validate the repository's compiler/source contracts only;
they do not claim a Roblox Studio gameplay playtest.
"""
from copy import deepcopy
from types import SimpleNamespace as NS

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.host_verified_typed_effects import (
    eligible_verified_effect, render_verified_effect,
)
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.world_object_abi import world_lookup_errors, world_names


def _proposal():
    actor = "AlienEntity77D3DB11"
    arrival = "RMMOrbitArrival_c2be30531a"
    combat = NS(
        name="AlienCombat77D3DB1Server", module_id="dyn_combat",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/AlienCombat77D3DB1Server.luau",
        description=(
            "Validate that the player is on the alien planet and that the "
            "target is a server-owned alien entity within range; then "
            "server-authoritatively mutate the target's health and apply "
            "the player's damage, rejecting invalid or out-of-range requests."
        ),
    )
    client = NS(
        name="AlienCombat77D3DB1Client", module_id="dyn_client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/AlienCombat77D3DB1Client.client.luau",
        description="Host-validated typed alien input form",
    )
    builder = NS(
        name="ShipAssemblyServer", module_id="dyn_builder",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ShipAssemblyServer.luau",
        description="Server-owned ship assembly",
    )
    launch = NS(
        name="ShipDepartureServer", module_id="dyn_launch",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ShipDepartureServer.luau",
        description="Server-owned flight and arrival",
    )
    data = NS(
        name="PlayerDataManager", module_id="mod_player_data",
        kind=ModuleKind.DATA_STORE,
        file_path="src/server/PlayerDataManager.luau",
        description="Loaded player profile state",
    )
    remote = "AlienCombat77D3DB1Action"
    design = {
        "host_actions": {remote: {
            "service": combat.name, "kind": "RemoteFunction", "max_args": 1,
        }},
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {
            combat.module_id: [remote], client.module_id: [remote],
        },
        "host_typed_actions": {remote: {
            "server": combat.name, "client": client.name,
            "transport_only": True,
            "world_entities": ["AlienEntity"],
            "contract": {
                "inputs": [
                    {"id": "selection", "label": "Target ID", "type": "text"},
                    {"id": "quantity", "label": "Attack count", "type": "integer",
                     "min": 1, "max": 10000},
                ],
                "target": {"kind": "none"}, "state_changes": [],
            },
        }},
        "world_objects": [
            {"name": actor, "class": "Part", "size": [4, 4, 4],
             "position": [36, 2, 24]},
            {"name": arrival, "class": "Part", "size": [96, 4, 96],
             "position": [0, 8000, 0]},
        ],
        "module_world_objects": {combat.module_id: [actor]},
        "host_vehicle_identity_bindings": [{
            "server": launch.name, "builder": builder.name,
        }],
        "host_arrival_materializations": [{
            "server": launch.name, "builder": builder.name, "arrival": arrival,
        }],
    }
    proposal = NS(
        requested_prompt="Explore a world and fight server-owned alien targets",
        game_design={"dynamic_design": design}, modules=[
            combat, client, builder, launch, data,
        ],
    )
    return proposal, combat, actor, arrival


def test_log52_full_logical_alias_compiles_with_no_small_model_server_body():
    proposal, combat, actor, arrival = _proposal()
    assert eligible_verified_effect(combat, proposal) == (
        "world_damage", "AlienCombat77D3DB1Action", actor, arrival,
    )
    code = render_verified_effect(combat, proposal)
    assert code is not None
    assert 'target:SetAttribute("RMMAlienHealth", remaining)' in code
    assert 'marker:SetAttribute("RMMAlienHealth", 100)' not in code
    assert 'marker:SetAttribute("RMMAlienHealth", 100)' not in code
    assert 'marker:SetAttribute("RMMAlienHealth", 100)' not in code
    assert 'marker:SetAttribute("RMMAlienHealth", 100)' not in code
    assert 'if args.quantity ~= 1 then' in code
    assert 'not_in_space' in code
    assert actor in world_names(proposal, combat)[1]
    assert arrival in world_names(proposal, combat)[1]
    assert world_lookup_errors(code, proposal, combat) == []


def test_log52_foreign_or_ambiguous_actor_must_not_compile():
    proposal, combat, actor, arrival = _proposal()
    for kind in ("not_owned", "wrong_class", "ambiguous", "no_arrival",
                 "not_damage"):
        p = deepcopy(proposal)
        m = p.modules[0]
        w = p.game_design["dynamic_design"]
        if kind == "not_owned":
            w["module_world_objects"][m.module_id] = []
        elif kind == "wrong_class":
            w["world_objects"][0]["class"] = "Model"
        elif kind == "ambiguous":
            extra = dict(w["world_objects"][0], name="AlienEntityAnotherPart")
            w["world_objects"].append(extra)
            w["module_world_objects"][m.module_id].append(extra["name"])
        elif kind == "no_arrival":
            w["host_arrival_materializations"] = []
        else:
            m.description = "Inspect the alien target without changing state"
        assert eligible_verified_effect(m, p) is None, kind
