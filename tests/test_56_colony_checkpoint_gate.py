"""56: checkpoint contract must recognize the approved host colony proxy,
without permitting arbitrary no-effect delegates or disabling generic safety.

This reproduces the failure AFTER generation scope accepted host_space_colony_alias.
"""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_space_colonization import render_colony_alias
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.module_generation_gate import (
    generated_module_errors, require_generated_module_contract,
    ModuleGenerationContractError,
)
from tests.test_55_space_colony_alias import reproduce


def _errors(plan, server, code):
    return generated_module_errors(server, plan, code, LuauStaticAnalyzer())


def test_56_exact_verified_colony_alias_can_be_checkpointed():
    plan, server, client = reproduce()
    code = render_colony_alias(server, plan)
    assert code and "owner.handleAction" in code
    assert _errors(plan, server, code) == []
    require_generated_module_contract(server, plan, code, LuauStaticAnalyzer())
    generator = LuauCodeGenerator()
    assert generator.generate_with_self_correction(server, plan) == code


def test_56_arbitrary_success_stub_still_rejected_as_no_effect():
    plan, server, _ = reproduce()
    trusted = render_colony_alias(server, plan)
    bogus = trusted.replace(
        'return owner.handleAction(player,services,{selection="planet",quantity=1})',
        'return {success=true,colonized=true}'
    )
    assert bogus != trusted
    assert any("ACTION_EFFECT_UNIMPLEMENTED" in item for item in
               _errors(plan, server, bogus))


def test_56_modified_delegate_cannot_pass_as_trusted_host_source():
    plan, server, _ = reproduce()
    trusted=render_colony_alias(server,plan)
    bypass=trusted.replace('{selection="planet",quantity=1}',
                            '{selection="mine",quantity=1}')
    assert bypass!=trusted
    assert any("ACTION_EFFECT_UNIMPLEMENTED" in item for item in
               _errors(plan,server,bypass))


def test_56_unverified_original_plan_cannot_enable_effect_exemption():
    plan,server,_=reproduce()
    trusted=render_colony_alias(server,plan)
    altered=deepcopy(plan)
    altered.modules=[m for m in altered.modules
                     if not m.name.startswith("MarkPlanetColonized")]
    assert any("ACTION_EFFECT_UNIMPLEMENTED" in item for item in
               _errors(altered,server,trusted))


def test_56_invalid_luau_still_rejected_even_for_alias():
    plan,server,_=reproduce()
    trusted=render_colony_alias(server,plan)
    poisoned=trusted.replace('local canonicalName=',
                             'local canonicalName=loadstring("return 1") or ')
    errors=_errors(plan,server,poisoned)
    assert any("UNSAFE_DYNAMIC_CODE" in item for item in errors)
