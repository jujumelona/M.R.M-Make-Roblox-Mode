"""Log 31: all 26 files generated; production blocked on four Selene warnings.

The host may not turn off lint warnings. It must generate warning-free ABI
scaffolding and detect model bodies that fetch server state but never use it.
"""
from roblox_mod_ai.host_service_codegen import _shell, scoped_body_unused_locals
from roblox_mod_ai.host_verified_typed_effects import render_verified_effect
from roblox_mod_ai.typed_action_contract import lua_server_guard
from test_log27_orbit_world_abi import _log27


def _typed():
    return {
        "inputs": [
            {"id": "selection", "type": "text", "label": "Target"},
            {"id": "quantity", "type": "integer", "label": "Quantity",
             "min": 1, "max": 10000},
        ],
        "target": {"kind": "none"},
        "state_changes": [],
    }


def test_31_unused_alias_removed_when_model_uses_validated_actionargs():
    code = _shell(
        'local selection = actionArgs.selection\n'
        'local quantity = actionArgs.quantity\n'
        'if quantity < 1 or selection == "" then return false end\n'
        'return {success=true, amount=quantity}',
        typed_contract=_typed())
    assert 'local actionArgs = ...' in code
    assert 'local args = actionArgs' not in code
    assert 'local selection = actionArgs.selection' in code
    assert 'local quantity = actionArgs.quantity' in code


def test_31_alias_remains_when_the_actual_model_body_reads_it():
    code = _shell(
        'if args.quantity ~= 1 then return false end\n'
        'return {success=true}',
        typed_contract=_typed())
    assert 'local args = actionArgs' in code


def test_31_no_validated_input_is_silently_removed_from_guard():
    original = lua_server_guard(_typed())
    compiled = _shell(
        'if actionArgs.quantity > 100 then return false end\n'
        'return {success=true}',
        typed_contract=_typed())
    assert original.count('__rmmAllowedFields') == compiled.count('__rmmAllowedFields')
    assert 'actionArgs["quantity"]' in compiled
    assert 'actionArgs["selection"]' in compiled


def test_31_unused_server_profile_lookup_rejected_before_selene():
    from_log = '''
local selection = actionArgs.selection
local quantity = actionArgs.quantity
local state = services.PlayerDataManager.GetState(player, "RMMInventory")
local coins = player.leaderstats.Coins.Value
if not selection or quantity > coins then return false end
local planet = workspace:FindFirstChild("SpecialMineralDeposit77D3DB31")
if not planet then return false end
planet:SetAttribute("Colonized", true)
return true
'''
    errors = scoped_body_unused_locals(from_log)
    assert len(errors) == 1, errors
    assert "SCOPED_UNUSED_LOCAL: state" in errors[0]


def test_31_used_model_body_state_is_not_rejected_as_dead():
    valid = '''
local state = services.PlayerDataManager.GetState(player, "RMMInventory")
if not state then return false end
local owned = state.ore or 0
state.ore = owned + 1
return true
'''
    assert scoped_body_unused_locals(valid) == []


def test_31_comments_and_string_mentions_do_not_fake_state_usage():
    fake = '''
local state = services.PlayerDataManager.GetState(player, "RMMInventory")
-- state was used!
local msg = "state"
return false
'''
    errors = scoped_body_unused_locals(fake)
    assert any("state" in e for e in errors), errors
    assert any("msg" in e for e in errors), errors


def test_31_verified_combat_does_not_leave_unused_services_argument():
    proposal, module = _log27("combat")
    code = render_verified_effect(module, proposal)
    assert code is not None
    assert "function Service.handleAction(player, _services, ...)" in code
    assert "function Service.start(services)" in code
    assert "local valid, args = input(...)" in code


def test_31_verified_harvest_still_receives_services():
    proposal, module = _log27("harvest")
    code = render_verified_effect(module, proposal)
    assert code is not None
    assert "function Service.handleAction(player, services, ...)" in code
    assert 'services.PlayerDataManager.GetState(player, "RMMInventory")' in code


def test_31_local_unavailable_studio_is_not_offered_to_small_model(monkeypatch):
    from roblox_mod_ai.agent_tool_runtime import RobloxAgentToolRuntime
    from test_log25_verified_typed_effects import _fixture
    import roblox_mod_ai.studio_bridge as studio
    def unavailable():
        raise RuntimeError("Windows/macOS Studio unavailable in Colab")
    monkeypatch.setattr(studio, "studio_command", unavailable)
    plan, module = _fixture("combat")
    runtime = RobloxAgentToolRuntime(module, plan)
    offered = {tool["function"]["name"] for tool in runtime.definitions()}
    assert "roblox_official_docs_search" in offered
    assert "roblox_api_search" in offered
    assert "roblox_studio_status" not in offered
    assert "roblox_studio_inspect" not in offered
    denied = runtime.call("roblox_studio_inspect", {
        "tool": "script_read", "arguments": {"path": module.file_path}
    })
    assert denied["ok"] is False
    assert "TOOL_UNAVAILABLE_IN_ENVIRONMENT" in denied["error"]
    assert runtime.records[-1]["ok"] is False
