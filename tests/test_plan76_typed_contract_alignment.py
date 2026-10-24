"""Cross-genre contract invariants from proposal 76 codegen failure.

The host defines local args = actionArgs in the typed server guard.
A transport_only contract declares input wiring, not state semantics.
The per-module gate must accept host-generated transport that has a REAL
authoritative gameplay mutation, while still rejecting no-op handlers and
a genuinely committed effect key missing from implementation.
"""
from types import SimpleNamespace as Obj

import pytest

from roblox_mod_ai.scoped_luau_abi import (
    typed_input_abi_errors,
    typed_input_fields_used,
)
from roblox_mod_ai.typed_action_contract import lua_server_guard
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.spec import ModuleKind


INPUTS = {
    "inputs": [
        {"id": "selection", "label": "Selected item", "type": "text"},
        {"id": "quantity", "label": "Requested quantity", "type": "integer",
         "min": 1, "max": 20},
    ],
    "target": {"kind": "none"},
    "state_changes": [],
}


class Analyzer:
    def analyze_source(self, code, file_path):
        return []


def fixture(body, *, transport_only=True, state_changes=None):
    from roblox_mod_ai.host_service_codegen import _shell
    changes = INPUTS["state_changes"] if state_changes is None else state_changes
    contract = dict(INPUTS, state_changes=changes)
    module = Obj(
        module_id="dyn_generic_purchase", name="GenericPurchaseServer",
        file_path="src/server/GenericPurchaseServer.luau",
        kind=ModuleKind.SERVER_MODULE,
    )
    remote = "GenericPurchase"
    proposal = Obj(
        requested_prompt="A user buys a tool with earned credits",
        modules=[module],
        game_design={"dynamic_design": {
            "host_actions": {remote: {"kind": "RemoteFunction",
                                      "service": module.name, "max_args": 1}},
            "host_world_actions": {},
            "host_typed_actions": {remote: {
                "contract": contract, "server": module.name,
                "transport_only": transport_only,
            }},
        }},
    )
    code = _shell(body, typed_contract=contract)
    return module, proposal, code


def test_typed_server_shell_alias_is_declared():
    shell = lua_server_guard(INPUTS)
    assert "local actionArgs = ..." in shell
    assert "local args = actionArgs" in shell


@pytest.mark.parametrize("body", [
    'local selection = args.selection\nlocal quantity = args.quantity',
    'local selection = actionArgs.selection\nlocal quantity = args["quantity"]',
    'local selection = actionArgs["selection"]\nlocal quantity = actionArgs.quantity',
])
def test_valid_model_field_reads_do_not_fail_transport_contract(body):
    assert typed_input_abi_errors(body, INPUTS) == []
    assert typed_input_fields_used(body, INPUTS) == {"selection", "quantity"}


@pytest.mark.parametrize("body", [
    'local x = args[2]',
    'local x = actionArgs[1]',
    'local x = args.fieldId',
    'local x = actionArgs.fakeBalance',
    'local args = {}',
])
def test_positional_or_invented_input_names_are_rejected(body):
    assert typed_input_abi_errors(body, INPUTS)


def test_source_mutation_with_transport_only_does_not_require_unplanned_key():
    body = (
        'local selected = args.selection\n'
        'local requested = args.quantity\n'
        'if requested <= 0 then return false end\n'
        'local owned = services.PlayerDataManager.GetState(player, "Owned")\n'
        'if not owned then return false end\n'
        'owned.count = (owned.count or 0) + 1\n'
        'return true'
    )
    module, proposal, source = fixture(body)
    issues = generated_module_errors(module, proposal, source, Analyzer())
    assert not any("TYPED_STATE_CONTRACT_MISSING" in x for x in issues), issues
    assert not any("ACTION_EFFECT_UNIMPLEMENTED" in x for x in issues), issues


def test_genuine_state_contract_still_requires_exact_key():
    body = (
        'local selection = args.selection\n'
        'local owned = services.PlayerDataManager.GetState(player, "Owned")\n'
        'owned.count = (owned.count or 0) + 1\nreturn true'
    )
    module, proposal, source = fixture(
        body, transport_only=False,
        state_changes=[{"scope": "player", "key": "permanentUpgrade",
                        "operation": "set"}],
    )
    issues = generated_module_errors(module, proposal, source, Analyzer())
    assert any("TYPED_STATE_EFFECT_MISSING" in x for x in issues), issues


def test_noop_source_still_rejected_when_transport_only():
    module, proposal, source = fixture(
        "local selected = args.selection\nreturn true"
    )
    issues = generated_module_errors(module, proposal, source, Analyzer())
    assert any("ACTION_EFFECT_UNIMPLEMENTED" in x for x in issues), issues


def test_missing_state_changes_still_rejected_for_effectful_contract():
    module, proposal, source = fixture(
        "local selected = args.selection\n"
        "local stored = services.PlayerDataManager.GetState(player, 'A')\n"
        "stored.value = 3",
        transport_only=False,
    )
    issues = generated_module_errors(module, proposal, source, Analyzer())
    assert any("TYPED_STATE_CONTRACT_MISSING" in x for x in issues), issues
