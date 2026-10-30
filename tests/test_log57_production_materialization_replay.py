"""Production-log 57 replay: declared world, immutable source owner and arrival.

This fixture mirrors the *preflight materialized* architecture in the failed
proposal_partial.json, not the earlier unmaterialized proposal (100). No
production branch depends on particular game nouns or IDs.
"""
from copy import deepcopy

from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec, ModuleKind, RobloxService
from roblox_mod_ai.world_object_abi import world_lookup_errors, world_names

ARRIVAL = "RMMOrbitArrival_af1004269b"
NODE = "ResourceNode1600771"
MINER = "SourceOwnedExtraction160077D3DB3Server"
BUILDER = "AttachShipSection4533283Server"
LAUNCHER = "SpaceflightDeparture52E67D1Server"
MINER_ID = "dyn_50cb986d2bd4"


def production_57_minimal():
    modules = [
        RobloxModuleSpec(
            module_id=MINER_ID, name=MINER, kind=ModuleKind.SERVER_MODULE,
            file_path="src/server/" + MINER + ".luau",
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
            description=(
                "The authenticated player's extraction request is accepted "
                "only after the server checks the real server-owned world "
                "resource source, proximity, positive available yield and "
                "the player's authority; invalid or repeated requests "
                "produce no state change. On valid extraction, Player "
                "extracts other-planet special minerals from a source-owned "
                "mineral deposit, incrementing the player's owned inventory."
            ),
        ),
        RobloxModuleSpec(
            module_id="dyn_33e2a6592d3c", name=LAUNCHER,
            kind=ModuleKind.SERVER_MODULE,
            file_path="src/server/" + LAUNCHER + ".luau",
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        ),
        RobloxModuleSpec(
            module_id="dyn_23edde48817d", name=BUILDER,
            kind=ModuleKind.SERVER_MODULE,
            file_path="src/server/" + BUILDER + ".luau",
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        ),
    ]
    design = {
        "host_actions": {
            "SourceOwnedExtraction160077D3DB3Action": {
                "service": MINER, "kind": "RemoteFunction", "max_args": 0,
            },
        },
        "module_world_objects": {
            MINER_ID: ["AlienEntity77D3DB11", NODE],
        },
        "module_requirements": {MINER_ID: ["req-004"]},
        "world_objects": [
            {"name": "AlienEntity77D3DB11", "class": "Part"},
            {"name": NODE, "class": "Part"},
            {"name": ARRIVAL, "class": "Part"},
            {"name": "UnrelatedScenePart", "class": "Part"},
        ],
        "host_materialized_world": [{
            "service": MINER,
            "resource_node": NODE,
            "transport_rebased": True,
            "input": "RemoteFunction_server_selected_nearest_Part",
            "basis": "user_requested_resource_mining",
        }],
        "host_vehicle_identity_bindings": [{
            "server": LAUNCHER, "builder": BUILDER,
            "actor_provider": "GetOwnedActor",
            "actor": None, "physical_assembly_verified": False,
        }],
        "host_arrival_materializations": [{
            "server": LAUNCHER, "builder": BUILDER,
            "arrival": ARRIVAL, "studio_verified": False,
        }],
    }
    proposal = RobloxProposal(
        requested_prompt=(
            "우주로 나가면 다른행성의 특수 광물 외계인과 싸움 식민지화"
        ),
        game_title="Log57Fixture", description="Source contract replay",
        game_design={
            "dynamic_design": design,
            "pre_design_research": {"ledger": {"requirements": [{
                "id": "req-004",
                "statement": (
                    "우주로 나가면 다른행성의 특수 광물 외계인과 싸움 식민지화"
                ),
            }]}},
        },
        modules=modules,
    )
    return proposal, modules[0]


def test_log57_real_authorized_arrival_looked_up_in_generated_miner():
    proposal, miner = production_57_minimal()
    luau = render_host_mining(miner, proposal)
    assert luau and f'workspace:FindFirstChild("{ARRIVAL}", true)' in luau
    assert "progress.specialMinerals = balance + 1" in luau
    declared, authorized = world_names(proposal, miner)
    assert ARRIVAL in declared and ARRIVAL in authorized
    assert NODE in authorized
    assert "UnrelatedScenePart" not in authorized
    assert world_lookup_errors(luau, proposal, miner) == []
    violations = generated_module_errors(
        miner, proposal, luau, LuauStaticAnalyzer()
    )
    assert not any(
        "WORLD_OBJECT_NAME_UNDECLARED" in message for message in violations
    ), violations


def test_log57_arrival_access_requires_producer_identity_and_real_mine():
    for variant in (
        "no_producer", "wrong_builder", "duplicate_arrival",
        "invalid_resource", "unowned_miner", "invalid_destination",
    ):
        proposal, miner = production_57_minimal()
        design = proposal.game_design["dynamic_design"]
        if variant == "no_producer":
            design["host_vehicle_identity_bindings"].clear()
        elif variant == "wrong_builder":
            design["host_vehicle_identity_bindings"][0]["builder"] = "WrongBuilder"
        elif variant == "duplicate_arrival":
            design["host_arrival_materializations"].append(deepcopy(
                design["host_arrival_materializations"][0]
            ))
        elif variant == "invalid_resource":
            design["host_materialized_world"][0]["resource_node"] = "WrongNode"
        elif variant == "unowned_miner":
            design["module_world_objects"][MINER_ID] = ["AlienEntity77D3DB11"]
        elif variant == "invalid_destination":
            design["world_objects"][2]["class"] = "Model"
        _, authorized = world_names(proposal, miner)
        assert ARRIVAL not in authorized, (variant, authorized)
        lookup = f'local p = workspace:FindFirstChild("{ARRIVAL}", true)'
        assert world_lookup_errors(lookup, proposal, miner), variant
