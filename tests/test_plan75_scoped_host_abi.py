"""Generic real codegen regressions from the first plan-74 production failure.

No test injects a special space/mining prompt into production behavior.
The same rules apply to any owned action with a host-validated client form.
"""
import pytest

from roblox_mod_ai.scoped_luau_abi import (
    host_abi_guidance, normalize_trusted_player_aliases,
    typed_input_abi_errors,
)

TYPED = {
    "inputs": [
        {"id": "selection", "label": "Selected option", "type": "text"},
        {"id": "quantity", "label": "Requested quantity", "type": "integer",
         "min": 1, "max": 20},
    ],
    "target": {"kind": "none"},
    "state_changes": [],
}


def test_remove_only_exact_client_identity_shadow():
    source = (
        "local player = args[1]\n"
        "local state = services.PlayerDataManager.GetState(player, 'Inventory')\n"
        "if not state then return false end\n"
        "state.count = (state.count or 0) + 1\n"
    )
    clean = normalize_trusted_player_aliases(source)
    assert "local player = args[1]" not in clean
    assert "GetState(player, 'Inventory')" in clean
    assert "state.count =" in clean


def test_uppercase_alias_uses_real_caller_not_client_payload():
    source = (
        "local Player = args[1]\n"
        "local Services = args[2]\n"
        "local session = Services.PlayerDataManager.GetState(Player, 'State')\n"
    )
    clean = normalize_trusted_player_aliases(source)
    assert "local Player = player" in clean
    assert "local Services = services" in clean


def test_bad_and_ambiguous_shadow_remain_rejected():
    for src in (
        "local player = actionArgs.player",
        "local player = args[2]",
        "local services = args[1]",
        "local player = args[1] or player",
    ):
        assert normalize_trusted_player_aliases(src) == src


def test_typed_contract_rejects_hallucinated_fields():
    bad = (
        "if not actionArgs.fieldId then return false end\n"
        "local amount = actionArgs.quantity\n"
        "local fakeBalance = actionArgs.available\n"
    )
    issues = typed_input_abi_errors(bad, TYPED)
    assert len(issues) == 1
    assert "fieldId" in issues[0] and "available" in issues[0]
    assert "selection" in issues[0] and "quantity" in issues[0]


def test_correct_typed_inputs_are_accepted():
    assert typed_input_abi_errors(
        "local choice = actionArgs.selection\n"
        'local requested = actionArgs["quantity"]\n',
        TYPED,
    ) == []


def test_comment_and_string_do_not_trigger_fake_input_field():
    assert typed_input_abi_errors(
        "-- actionArgs.fakeField\n"
        'local text = "actionArgs.notAField"\n'
        "local requested = actionArgs.quantity",
        TYPED,
    ) == []


def test_host_guidance_uses_actual_names_and_exported_apis():
    text = host_abi_guidance(
        TYPED, {"PlayerDataManager": ["GetState", "OnReady"]},
    )
    assert '"selection": "text"' in text
    assert '"quantity": "integer"' in text
    # Small-model gameplay bodies may use GetState only. OnReady registers
    # lifecycle callbacks and is host-owned, not an action-scoped capability.
    assert '"PlayerDataManager": ["GetState"]' in text
    assert '"PlayerDataManager": ["GetState", "OnReady"]' not in text
    assert "SetState/SaveState" in text
    assert "immutable" in text.lower() or "IMMUTABLE" in text


def test_full_scaffold_rejects_arbitrary_host_shadow():
    from roblox_mod_ai.host_service_codegen import (
        normalize_verified_server_body,
    )
    class Stub:
        modules = []

    with pytest.raises(ValueError, match="HOST_IDENTITY_SHADOWED"):
        normalize_verified_server_body(
            "local player = actionArgs.player\n"
            "local state = services.PlayerDataManager.GetState(player, 'State')",
            Stub(),
        )
    repaired = normalize_verified_server_body(
        "local player = args[1]\n"
        "local state = services.PlayerDataManager.GetState(player, 'State')",
        Stub(),
    )
    assert "local player = args[1]" not in repaired


def test_no_generated_gameplay_state_is_certified_by_inputs_alone():
    # This checks *only* input transport. Empty state_changes does not
    # prove gameplay: the coder still needs an executable, reviewed effect.
    assert typed_input_abi_errors(
        "return false", TYPED,
    ) == []
    assert TYPED["state_changes"] == []
