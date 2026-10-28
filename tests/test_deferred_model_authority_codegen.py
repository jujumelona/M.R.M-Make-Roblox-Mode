"""Transport ABI is a pre-codegen contract, not a proof of state writes.

Deferral is allowed only for *bounded typed* producer obligations. Failed
model code cannot discharge the obligations. Other architecture defects
still fail before generation.
"""
from roblox_mod_ai.model_action_authority import (
    unproven_model_actions, partition_codegen_authority,
)
from roblox_mod_ai.authority_architecture_repair import replan_unproven_authority
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer

from test_log32_model_authority import _log32_design


def test_only_bounded_typed_model_actions_can_defer_real_producer_proof():
    plan, scope = _log32_design()
    raw = unproven_model_actions(plan, scope)
    blocked, pending = partition_codegen_authority(raw)
    assert not blocked
    assert len(pending) == 2
    assert all(x["strategy"] == "bounded_typed_server_action" for x in pending)

    incorrect = dict(pending[0], strategy="whole_file_model_legacy")
    invalid = dict(pending[0], reason="UNIQUE_AUTHORITY_ROUTE_NOT_FOUND")
    blocked, pending = partition_codegen_authority([incorrect, invalid])
    assert len(blocked) == 2
    assert not pending


def test_real_producer_proof_is_deferred_not_claimed_verified():
    plan, scope = _log32_design()
    design = dict(plan.game_design["dynamic_design"], modules=plan.modules)
    attempts = []
    def never_redesign():
        attempts.append(True)
        raise AssertionError("Should compile bounded model body, not replan it")

    result = replan_unproven_authority(
        design, existing_modules=[], requested_prompt=plan.requested_prompt,
        research={}, redesign=never_redesign, allow_codegen_deferral=True,
        inspect=lambda d, e, p: unproven_model_actions(plan, scope),
    )
    deferred = result["deferred_model_authority"]
    assert len(deferred) == 2
    assert all(d["verified"] is False and
               d["verification_stage"] == "codegen" for d in deferred)
    assert not attempts


def test_fabricated_source_cannot_discharge_deferred_codegen_gate():
    plan, scope = _log32_design()
    source = plan.modules[0]
    remote = source.name.removesuffix("Server") + "Action"
    plan.game_design["dynamic_design"]["deferred_model_authority"] = [{
        "module": source.name, "remote": remote, "verified": False,
    }]
    # Valid-looking stub transports the input but does no gameplay write.
    stub = """
--!strict
local Service = {}
function Service.start(services) end
function Service.handleAction(player, services, actionArgs)
    return {success = true, reason = "OK"}
end
return Service
"""
    errors = generated_module_errors(source, plan, stub, LuauStaticAnalyzer())
    assert any("DEFERRED_AUTHORITY_PRODUCER_MISSING" in e for e in errors)
