"""Log32: 24/26 files generated because 9B was asked to invent a planet owner.

The source plan's two transport-only actions have NO state producer,
no declared effect, and the declared world Parts are unrelated to colonized
planet or owned ship performance. These tests assert the contract blocker is
found *before* requesting any Luau and in the MCP context.
"""
from roblox_mod_ai.model_action_authority import unproven_model_actions
from roblox_mod_ai.agent_tool_runtime import (
    RobloxAgentToolRuntime, module_contract_snapshot,
)
from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec, ModuleKind, RobloxService


def _log32_design():
    # Source-grounded reduction of proposal_partial.json in upload 32, not
    # a world that might conveniently grant the intended ownership.
    server_names = {
        "dyn_colonize": ("ColonizePlanet77D3DB2Server",
            "Validate that the request references a planet already owned by "
            "the server and that the colonizer is the server-owned owner of "
            "that planet. Mutate the server-owned planet record."),
        "dyn_ship": ("ShipPerformanceUpgrade213E1D3Server",
            "For the requested purchase or trade, validate the server-owned "
            "catalog cost and owned balance, then upgrade the buyer's owned "
            "spaceship performance state."),
        "dyn_stateless": ("ActivateBeaconServer",
            "When player presses a button, update the visible warning beacon "
            "color with an authenticated Remote."),
    }
    modules = []
    actions = {}
    typed = {}
    world_access = {}
    for ident, (name, description) in server_names.items():
        modules.append(RobloxModuleSpec(
            module_id=ident, name=name, description=description,
            kind=ModuleKind.SERVER_MODULE,
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
            file_path="src/server/" + name + ".luau"))
        remote = name.removesuffix("Server") + "Action"
        actions[remote] = {"service": name, "kind": "RemoteFunction", "max_args": 1}
        typed[remote] = {
            "server": name, "client": name.removesuffix("Server") + "Client",
            "transport_only": True,
            "world_name": None, "world_entities": [],
            "contract": {
                "inputs": [{"id": "selection", "label": "Selection",
                             "type": "text"},
                           {"id": "quantity", "label": "Quantity",
                             "type": "integer", "min": 1, "max": 10000}],
                "target": {"kind": "none"}, "state_changes": [],
            }}
        world_access[ident] = (
            ["AlienEntitiesSpawnedOnT77D3DB11",
             "SpecialMineralDeposit77D3DB31"] if ident == "dyn_colonize" else []
        )
    plan = RobloxProposal(
        requested_prompt="A space game with colony ownership and upgrades",
        game_title="Test32", description="fixture", modules=modules,
        game_design={"dynamic_design": {
            "host_actions": actions, "host_typed_actions": typed,
            "module_world_objects": world_access,
            "world_objects": [
                {"name": "AlienEntitiesSpawnedOnT77D3DB11", "class": "Part"},
                {"name": "SpecialMineralDeposit77D3DB31", "class": "Part"},
            ],
        }},
    )
    scope = {"modules": [
        {"name": m.name, "strategy": "bounded_typed_server_action"}
        for m in modules
    ]}
    return plan, scope


def test_log32_both_unproven_prior_state_consumers_fail_before_codegen():
    plan, scope = _log32_design()
    gaps = unproven_model_actions(plan, scope)
    assert {row["module"] for row in gaps} == {
        "ColonizePlanet77D3DB2Server", "ShipPerformanceUpgrade213E1D3Server"
    }
    assert all(row["reason"] == "AUTHORITY_PRODUCER_NOT_DECLARED"
               for row in gaps)
    colony = next(row for row in gaps if row["module"].startswith("Colonize"))
    assert colony["declared_target_kind"] == "none"
    assert "SpecialMineralDeposit77D3DB31" in colony["declared_physical_objects"]


def test_log32_stateless_action_and_deterministic_host_compiler_not_blocked():
    plan, scope = _log32_design()
    assert all(row["module"] != "ActivateBeaconServer"
               for row in unproven_model_actions(plan, scope))
    scope["modules"][0]["strategy"] = "host_space_colony_alias"
    gaps = unproven_model_actions(plan, scope)
    assert len(gaps) == 1 and gaps[0]["module"].startswith("ShipPerformance")


def test_log32_evidence_requires_nontransport_effect_and_real_ir():
    plan, scope = _log32_design()
    design = plan.game_design["dynamic_design"]
    remote = "ShipPerformanceUpgrade213E1D3Action"
    spec = design["host_typed_actions"][remote]
    # An empty schema plus a reassuring phrase cannot prove a real effect.
    spec["transport_only"] = False
    assert any(x["remote"] == remote
               for x in unproven_model_actions(plan, scope))
    spec["contract"]["state_changes"] = [
        {"key": "RMMShipSpeed", "op": "increment", "value": 1}
    ]
    assert any(x["remote"] == remote
               for x in unproven_model_actions(plan, scope))
    design["host_executable_actions"] = {
        remote: {"schema": "rmm/atomic-effect-v1",
                 "namespace": "ship", "field": "RMMShipSpeed",
                 "operation": "add", "amount": 1, "limit": 500}
    }
    assert all(x["remote"] != remote for x in unproven_model_actions(plan, scope))


def test_log32_read_only_contract_inspector_admits_missing_authority():
    plan, scope = _log32_design()
    mod = plan.modules[0]
    report = module_contract_snapshot(mod, plan)
    assert not report["authority_provenance"]["passed"]
    assert report["authority_provenance"]["unresolved"][0]["module"] == mod.name
    assert report["scope"] == "source_plan_only_not_runtime_verified"


def test_log32_placeholder_luau_does_not_count_as_real_validation():
    plan, scope = _log32_design()
    module = plan.modules[0]
    class FakeMCP:
        calls = []
        def call_tool(self, name, args):
            self.calls.append(name)
            return {"passed": True, "diagnostics": []}
    stub = FakeMCP()
    runtime = RobloxAgentToolRuntime(module, plan, stub)
    invalid = runtime.call("roblox_luau_validate", {
        "code": "-- Placeholder: actual source not provided in the prompt.",
        "file_path": module.file_path,
    })
    assert not invalid["ok"]
    assert "LUAU_NO_EXECUTABLE_SOURCE" in invalid["error"]
    assert stub.calls == []
    valid = runtime.call("roblox_luau_validate", {
        "code": "local price = 100\nreturn price",
        "file_path": module.file_path,
    })
    assert valid["ok"]
    assert stub.calls == ["roblox_luau_validate"]
