"""Plan95: six completed source facets were discarded by pre-codegen proof.

This is about compilation stages, not a particular game or prompt. Typed
server routes with unverified effects survive as obligations, NEVER as
accepted executable features. Producer and source gates still reject stubs.
"""
import pytest

from roblox_mod_ai.authority_architecture_repair import (
    replan_unproven_authority, carried_codegen_authority,
    AuthorityArchitectureExhausted,
)
from roblox_mod_ai.model_action_authority import unproven_model_actions
from roblox_mod_ai.spec import (
    RobloxProposal, RobloxModuleSpec, ModuleKind, RobloxService,
)
from roblox_mod_ai.deferred_producer_evidence import has_authoritative_producer_write


def _six_owned_actions():
    modules = []
    routes = {}
    wires = {}
    links = {}
    descriptions = [
        "The server validates owned inventory and credits the requested resource.",
        "The server deducts owned stock and credits the priced payment.",
        "The server attaches owned component to a persisted owned actor.",
        "The server damages an authoritative owned world target.",
        "The server saves authoritative ownership of a world location.",
        "The server removes mined world stock and credits owned inventory.",
    ]
    for i, desc in enumerate(descriptions):
        name = f"GameplayAction{i}Server"
        module_id = f"dyn_action_{i}"
        remote = f"GameplayAction{i}Action"
        modules.append(RobloxModuleSpec(
            module_id=module_id, name=name,
            kind=ModuleKind.SERVER_MODULE,
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
            file_path=f"src/server/{name}.luau", description=desc,
        ))
        client = f"GameplayAction{i}Client"
        modules.append(RobloxModuleSpec(
            module_id=f"dyn_client_{i}", name=client,
            kind=ModuleKind.CLIENT_SCRIPT,
            roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
            file_path=f"src/client/{client}.client.luau",
            description="Collect validated player input",
        ))
        routes[remote] = {
            "service": name, "kind": "RemoteFunction", "max_args": 1,
        }
        wires[remote] = {
            "server": name, "client": client, "transport_only": True,
            "world_entities": [],
            "contract": {"inputs": [
                {"id": "selection", "label": "Selection", "type": "text"},
                {"id": "quantity", "label": "Quantity", "type": "integer",
                 "min": 1, "max": 10000},
            ], "target": {"kind": "none"}, "state_changes": []},
        }
        links[module_id] = [remote]
        links[f"dyn_client_{i}"] = [remote]
    design = {
        "modules": modules, "host_actions": routes,
        "host_typed_actions": wires, "module_remotes": links,
    }
    proposal = RobloxProposal(
        requested_prompt="Create all six interdependent requested mechanics",
        game_title="GenericProof", description="source-owned fixture",
        modules=modules, game_design={"dynamic_design": design},
    )
    scope = {"modules": [
        {"name": m.name, "strategy": "bounded_typed_server_action"}
        for m in modules if m.kind == ModuleKind.SERVER_MODULE
    ]}
    return proposal, scope


def test_plan95_preserves_all_six_planned_actions_without_fake_authority():
    proposal, scope = _six_owned_actions()
    issues = unproven_model_actions(proposal, scope)
    assert len(issues) == 6
    assert {x["reason"] for x in issues} == {"AUTHORITY_PRODUCER_NOT_DECLARED"}
    research = {}
    replans = []

    certified = replan_unproven_authority(
        proposal.game_design["dynamic_design"],
        existing_modules=[], requested_prompt=proposal.requested_prompt,
        research=research, redesign=lambda: replans.append("regenerated"),
        inspect=lambda _d, _e, _p: issues,
        allow_codegen_deferral=True,
    )
    assert not replans
    pending = carried_codegen_authority(certified)
    assert len(pending) == 6
    assert all(item["verified"] is False and
               item["verification_stage"] == "codegen"
               for item in pending)
    assert {item["module"] for item in pending} == {
        m.name for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE
    }
    assert research["authority_replan_attempts"][0]["passed"] is False
    assert len(research["authority_replan_attempts"][0]["deferred_until_codegen"]) == 6
    assert "_authority_feedback" not in research


def test_plan95_cannot_defer_missing_routes_as_a_valid_implementation():
    proposal, scope = _six_owned_actions()
    issues = unproven_model_actions(proposal, scope)
    invalid = {"module": "MissingRouteServer",
               "reason": "UNIQUE_AUTHORITY_ROUTE_NOT_FOUND"}
    with pytest.raises(AuthorityArchitectureExhausted):
        replan_unproven_authority(
            proposal.game_design["dynamic_design"], existing_modules=[],
            requested_prompt=proposal.requested_prompt, research={},
            redesign=lambda: None, max_repairs=0,
            inspect=lambda _d, _e, _p: issues + [invalid],
            allow_codegen_deferral=True,
        )


def test_plan95_transport_only_or_scratch_write_cannot_close_producer_gate():
    stub = """--!strict
local Service = {}
function Service.handleAction(player, services, payload)
    -- RMM_GAMEPLAY_BODY_BEGIN
    local temporary = {}
    temporary.money = payload.quantity
    return {success=true}
    -- RMM_GAMEPLAY_BODY_END
end
return Service
"""
    assert not has_authoritative_producer_write(stub)


def test_plan95_unauthenticated_deferred_route_cannot_be_serialized():
    proposal, scope = _six_owned_actions()
    issues = unproven_model_actions(proposal, scope)
    raw = proposal.game_design["dynamic_design"]
    compiled = replan_unproven_authority(
        raw, existing_modules=[], requested_prompt=proposal.requested_prompt,
        research={}, redesign=lambda: None,
        inspect=lambda _d, _e, _p: issues,
        allow_codegen_deferral=True,
    )
    corrupted = dict(compiled)
    corrupted["module_remotes"] = dict(compiled["module_remotes"])
    corrupted["module_remotes"]["dyn_action_0"] = ["DifferentRemote"]
    with pytest.raises(ValueError, match="DEFERRED_AUTHORITY_UNBOUND_OR_FORGED"):
        carried_codegen_authority(corrupted)
