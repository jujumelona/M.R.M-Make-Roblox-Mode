"""General resource-paid modular ship assembly must not require 9B Luau.

Uses a verified miner as the authoritative resource producer. The market
receipt is not silently treated as a physical part or installed hull.
"""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_resource_ship_builder import eligible_resource_ship_builder
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class Model:
    def __init__(self):
        self.calls = []

    def complete(self, *_a, **_kw):
        raise AssertionError("The host must own all ship assembly Luau")

    def complete_json(self, _prompt, **kwargs):
        self.calls.append(kwargs)
        return {"sections": [
            {"id": "hull", "label": "Main Hull", "cost": 12, "performance": 4},
            {"id": "engine", "label": "Engine Module", "cost": 23, "performance": 9},
        ]}


def _plan():
    def mod(name, desc, client=False):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name, description=desc,
            kind=(ModuleKind.CLIENT_SCRIPT if client else ModuleKind.SERVER_MODULE),
            file_path=("src/client/" + name + ".client.luau" if client
                       else "src/server/" + name + ".luau"),
            roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS
            if client else RobloxService.SERVER_SCRIPT_SERVICE,
        )
    miner = mod("OreMiningServiceServer",
        "The server validates the player's proximity to a resource node "
        "before gathering it and credits the earned mining resources.")
    builder = mod("ShipConstructionServiceServer",
        "The server owns the ship assembly state and validates every section "
        "build. A player may only add a section when the ship has a valid "
        "parent hull, the section is one of the allowed section types, "
        "the player has enough of the required resource, and the ship has "
        "not exceeded its maximum section count. On a valid request the "
        "server adds the section to the ship assembly record, deducts "
        "the required resource, and returns the ship's new section count. "
        "Invalid requests are rejected without mutation.")
    client = mod("ShipConstructionServiceClient",
        "Select a ship section and request a resource-paid build.", True)
    dyn = {
        "host_actions": {
            "MiningAction": {"service": miner.name, "kind": "RemoteFunction"},
            "BuildAction": {"service": builder.name, "kind": "RemoteFunction"},
        },
        "remotes": {"MiningAction": "RemoteFunction", "BuildAction": "RemoteFunction"},
        "module_remotes": {
            miner.module_id: ["MiningAction"],
            builder.module_id: ["BuildAction"],
            client.module_id: ["BuildAction"],
        },
        "world_objects": [{"name": "ResourceNode031441", "class": "Part"}],
    }
    return RobloxProposal(
        requested_prompt="Mine resources and assemble ship sections",
        game_title="Ship", description="Source-owned workshop",
        game_design={"dynamic_design": dyn}, modules=[miner, builder, client],
    )


def test_resource_paid_ship_assembly_is_host_owned_and_uses_real_mining_balance():
    plan = _plan()
    miner, builder, client = plan.modules
    assert eligible_resource_ship_builder(builder, plan)
    assert eligible_resource_ship_builder(client, plan)
    assert [r["strategy"] for r in generation_scope(plan)["modules"]] == [
        "host_verified_template", "host_declarative_resource_ship_builder",
        "host_declarative_resource_ship_builder",
    ]
    model = Model()
    modules = LuauCodeGenerator(model).generate_all_modules(plan)
    assert len(model.calls) == 1
    for m in modules:
        errors = [d for d in LuauStaticAnalyzer().analyze_source(
            m.code, m.file_path) if d.severity == "ERROR"]
        assert not errors, errors
    assert 'GetState(player, "RMMInventory")' in builder.code
    assert 'GetState(player, "RMMShipSections")' in builder.code
    assert "inventory.resources = resources - definition.cost" in builder.code
    assert "sectionCount >= 8" in builder.code
    assert "RMMPlayerShips" in builder.code
    assert "placePart(parts, anchor, id)" in builder.code
    assert "remote:InvokeServer(section.id)" in client.code
    assert 'GetState(player, "RMMInventory")' in miner.code


def test_resource_ship_builder_fails_closed_for_unverified_producer():
    plan = _plan()
    miner, builder, client = plan.modules
    plan.game_design["dynamic_design"]["world_objects"] = []
    assert eligible_resource_ship_builder(builder, plan) is None
    assert eligible_resource_ship_builder(client, plan) is None
    plan = _plan()
    plan.game_design["dynamic_design"]["host_actions"]["BuildAction"]["max_args"] = 0
    assert eligible_resource_ship_builder(plan.modules[1], plan) is None
    plan = _plan()
    plan.modules[1].description += " Also permits removing and refunding parts."
    assert eligible_resource_ship_builder(plan.modules[1], plan) is None
