"""Reject actual plan-78 broken saved code before calling a game complete.

These are universal Luau/Roblox engine value semantics, independent of
which user prompt caused the module to be created.
"""
from roblox_mod_ai.roblox_value_contract import roblox_value_contract_errors


def test_table_insert_returns_nil_not_a_serializable_attribute():
    code = (
        'local nextParts = {"a"}\n'
        'ship:SetAttribute("assembly", table.insert(nextParts, "b"))\n'
    )
    assert any("TABLE_INSERT_RETURNS_NIL" in error or
               "ATTRIBUTE_TABLE_UNSUPPORTED" in error
               for error in roblox_value_contract_errors(code))


def test_attributes_do_not_store_table_clones():
    code = (
        'local crew = workspace:FindFirstChild("Crew")\n'
        'crew:SetAttribute("State", table.clone({a = 1}))\n'
    )
    assert any("ATTRIBUTE_TABLE_UNSUPPORTED" in error
               for error in roblox_value_contract_errors(code))


def test_getattribute_cannot_be_event_or_player_instance():
    code = (
        'part:GetAttribute("completionEvent"):FireClient(player)\n'
        'if ship:GetAttribute("Owner") == player then return true end\n'
    )
    errors = roblox_value_contract_errors(code)
    assert any("ATTRIBUTE_NOT_REMOTE" in error for error in errors)
    assert any("ATTRIBUTE_NOT_INSTANCE" in error for error in errors)


def test_cannot_roundtrip_lua_array_via_instance_attribute():
    code = (
        'local assembly = ship:GetAttribute("assembly") or {}\n'
        'local next = table.clone(assembly)\n'
        'table.insert(next, "hull")'
    )
    assert any("ATTRIBUTE_TABLE_ROUNDTRIP" in error
               for error in roblox_value_contract_errors(code))


def test_actual_numeric_string_boolean_roblox_attributes_still_valid():
    code = (
        'part:SetAttribute("Count", 4)\n'
        'part:SetAttribute("Depleted", false)\n'
        'part:SetAttribute("OwnerUserId", player.UserId)\n'
        'if part:GetAttribute("Depleted") then return false end'
    )
    assert roblox_value_contract_errors(code) == []


def test_comment_or_literal_evidence_is_not_executable():
    code = (
        '-- ship:SetAttribute("State", table.clone({}))\n'
        'local debug = "ship:SetAttribute(\\"State\\", table.clone({}))"\n'
    )
    assert roblox_value_contract_errors(code) == []



def test_cross_gameplay_handler_not_a_valid_peer_transaction_api():
    from types import SimpleNamespace as Obj
    from roblox_mod_ai.server_interface_audit import dependency_api_errors
    from roblox_mod_ai.spec import ModuleKind
    peer = Obj(
        name="PeerActionService", module_id="dyn_peer",
        kind=ModuleKind.SERVER_MODULE, file_path="src/server/PeerActionService.luau",
        code=(
            "local Service = {}\n"
            "function Service.handleAction(player, services, ...)\n"
            "  return true\n"
            "end\nreturn Service\n"
        ),
    )
    caller = Obj(
        name="CallerService", module_id="dyn_caller",
        kind=ModuleKind.SERVER_MODULE, file_path="src/server/CallerService.luau",
        code="",
    )
    source = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "  return services.PeerActionService.handleAction("
        "player, services, {selection = 'free'})\n"
        "end\nreturn Service\n"
    )
    issues = dependency_api_errors(
        caller, Obj(modules=[caller, peer]), source,
    )
    assert any("DEPENDENCY_ACTION_DISPATCH_FORBIDDEN" in x for x in issues)
