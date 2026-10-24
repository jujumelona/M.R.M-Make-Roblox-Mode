"""Cross-cutting regression: invalid model output cannot become 'completed' code.

Prior failure ZIPs repeatedly had parser-acceptable Luau that called invented
PlayerDataManager/Roblox APIs. The previous pipeline checkpointed each module
after syntax alone; only the final all-file gate found interface mismatches.
"""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.module_generation_gate import (
    ModuleGenerationContractError, generated_module_errors,
    require_generated_module_contract,
)
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


def make_cross_module():
    data = RobloxModuleSpec(
        module_id="mod_player_data", name="PlayerDataManager",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/PlayerDataManager.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Profile API.",
        code="""--!strict
local PlayerDataManager = {}
function PlayerDataManager.start(services) end
function PlayerDataManager.GetState(player, namespace) return {} end
return PlayerDataManager
""",
    )
    name = "DynamicUpgradeServer"
    service = RobloxModuleSpec(
        module_id="dyn_upgrade001", name=name,
        kind=ModuleKind.SERVER_MODULE,
        file_path=f"src/server/{name}.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Upgrade a server-owned inventory only after a purchase.",
    )
    client = RobloxModuleSpec(
        module_id="dyn_upgradeclient001", name="DynamicUpgradeClient",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/DynamicUpgradeClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Client shows purchase UI.",
    )
    p = RobloxProposal(
        game_title="Gate", description="Codegen source contract",
        requested_prompt="Build a validated in-game upgrade shop",
        modules=[data, service, client],
        game_design={"dynamic_design": {
            "host_actions": {
                "PurchaseAction": {"service": name, "kind": "RemoteFunction"}
            },
            "remotes": {"PurchaseAction": "RemoteFunction"},
        }},
    )
    return p, service, client


def test_syntactically_valid_unexported_host_api_rejected_before_checkpoint():
    p, module, _ = make_cross_module()
    code = """--!strict
local Service = {}
function Service.start(services)
    assert(services.PlayerDataManager ~= nil)
end
function Service.handleAction(player, services, ...)
    local value = services.PlayerDataManager.GetCurrencyBalance(player)
    player:SetAttribute("AttemptedPurchase", value)
    return true
end
return Service
"""
    errors = generated_module_errors(module, p, code, LuauStaticAnalyzer())
    assert any("DEPENDENCY_API" in error and "GetCurrencyBalance" in error for error in errors)
    with pytest.raises(ModuleGenerationContractError, match="GetCurrencyBalance"):
        require_generated_module_contract(module, p, code, LuauStaticAnalyzer())


def test_wrong_roblox_realm_and_invoked_server_service_rejected_early():
    p, module, client = make_cross_module()
    source = """--!strict
local Players = game:GetService("Players")
local Service = {}
function Service.start(services)
    local user = Players.LocalPlayer
end
function Service.handleAction(player, services, ...)
    local result = game:GetService("PlayerDataManager")
    return result
end
return Service
"""
    errors = generated_module_errors(module, p, source, LuauStaticAnalyzer())
    assert any("REALM" in err for err in errors)
    assert any("DEPENDENCY_API" in err for err in errors)
    client_src = """--!strict
local service = game:GetService("ServerScriptService")
local button = Instance.new("TextButton")
button.Parent = service
button.Activated:Connect(function()
    local value = game:GetService("DataStoreService")
    button.Text = tostring(value)
end)
"""
    errs = generated_module_errors(client, p, client_src, LuauStaticAnalyzer())
    assert any("REALM" in err for err in errs)


def test_valid_existing_mining_host_code_passes_early_gate():
    from test_host_mining import make_plan
    server, client, p = make_plan()
    # The actual generated bootstrap always normalizes the PlayerDataManager
    # into the same server-only services registry. A fixture without that
    # dependency is NOT a valid host-mining program and must not be treated as
    # the reference for the production dependency audit.
    from roblox_mod_ai.spec import RobloxModuleSpec, RobloxService
    profile = RobloxModuleSpec(
        module_id="mod_player_data", name="PlayerDataManager",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/PlayerDataManager.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Host profile and saved game state API",
        code=(
            "local PlayerDataManager = {}\\n"
            "function PlayerDataManager.GetState(player, namespace) "
            "return {} end\\n"
            "function PlayerDataManager.OnReady(callback) return nil end\\n"
            "function PlayerDataManager.start(services) end\\n"
            "return PlayerDataManager\\n"
        ),
    )
    p.modules = [profile, server, client]
    analyzer = LuauStaticAnalyzer()
    for mod in (server, client):
        code = render_host_mining(mod, p)
        assert code
        assert generated_module_errors(mod, p, code, analyzer) == []


def test_host_action_with_constant_success_cannot_pass_as_implemented():
    p, module, _ = make_cross_module()
    code = """--!strict
local Service = {}
function Service.start(services)
    assert(type(services) == "table")
end
function Service.handleAction(player, services, ...)
    return true
end
return Service
"""
    errors = generated_module_errors(module, p, code, LuauStaticAnalyzer())
    assert any("SERVICE_ABI" in error for error in errors)


def test_actual_failure_log_colon_call_misplaces_player_data_args():
    p, module, _ = make_cross_module()
    code = """--!strict
local Service = {}
function Service.start(services)
    assert(type(services) == "table")
end
function Service.handleAction(player, services, ...)
    local inventory = services.PlayerDataManager:GetState(player, "OwnedShipParts")
    if not inventory then return false end
    player:SetAttribute("OwnedShipPartsLoaded", true)
    return true
end
return Service
"""
    errors = generated_module_errors(module, p, code, LuauStaticAnalyzer())
    assert any("DEPENDENCY_API" in error and "silently shifts" in error
               for error in errors)


def test_actual_failure_log_bare_plan_id_require_caught_as_undefined_variable():
    p, _server, client = make_cross_module()
    p.modules.append(RobloxModuleSpec(
        module_id="mod_network_bridge", name="NetworkRemotes",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/shared/NetworkRemotes.luau",
        roblox_service=RobloxService.REPLICATED_STORAGE,
        description="Host-owned network bridge",
    ))
    code = """--!strict
local bridge = require(mod_network_bridge)
local Players = game:GetService("Players")
local player = Players.LocalPlayer
local gui = Instance.new("ScreenGui")
gui.Parent = player:WaitForChild("PlayerGui")
local label = Instance.new("TextLabel")
label.Text = tostring(bridge)
label.Parent = gui
"""
    errors = generated_module_errors(client, p, code, LuauStaticAnalyzer())
    assert any("UNBOUND_MODULE_REQUIRE" in error and "mod_network_bridge" in error
               for error in errors)
