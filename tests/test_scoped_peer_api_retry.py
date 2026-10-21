"""Regression: peer API mistakes must retry INSIDE the bounded unit.

This reproduces the real bug where a bounded Luau body passed syntax checks
but only failed later in module_generation_gate after all model retries ended.
"""
from roblox_mod_ai.host_service_codegen import try_scaffolded_server
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.server_interface_audit import dependency_api_errors
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService

_BAD = """local profile = services.PlayerDataManager:GetState(player, "RMMInventory")
if not profile then return false end
services.PlayerDataManager:SetState(player, "RMMInventory", profile, true)
player:SetAttribute("ServerGrantedFlag", true)
return true
"""

_GOOD = """local profile = services.PlayerDataManager.GetState(player, "RMMInventory")
if not profile then return false end
if player:GetAttribute("ServerGrantedFlag") ~= true then return false end
player:SetAttribute("ServerGrantedFlag", false)
return true
"""


class RetryRouter:
    def __init__(self):
        self.calls = []
        self.last_generation_report = {}

    def complete(self, prompt, **kwargs):
        self.calls.append(prompt)
        return _BAD if len(self.calls) == 1 else _GOOD


def _plan():
    data = RobloxModuleSpec(
        module_id="mod_player_data", name="PlayerDataManager",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/PlayerDataManager.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Provides an already loaded, mutable server-owned player profile.",
        code="""local PlayerDataManager = {}
function PlayerDataManager.GetState(player, namespace)
    return {}
end
function PlayerDataManager.OnReady(callback)
end
return PlayerDataManager
""",
    )
    service = RobloxModuleSpec(
        module_id="dyn_server1", name="StateUpdaterServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/StateUpdaterServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Validate a server-owned progress flag and update the state "
                    "only when the saved profile exists.",
    )
    return service, RobloxProposal(
        requested_prompt="Player actions update valid server-owned progress",
        game_title="Arbitrary world", description="World",
        modules=[data, service],
        game_design={"dynamic_design": {
            "host_actions": {"UpdateStateAction": {
                "service": service.name, "kind": "RemoteFunction"}},
            "remotes": {"UpdateStateAction": "RemoteFunction"},
        }},
    )


def test_missing_and_colon_called_peer_methods_retry_short_body():
    service, plan = _plan()
    router = RetryRouter()
    code = try_scaffolded_server(service, plan, router, LuauStaticAnalyzer())
    assert code is not None
    assert len(router.calls) == 2
    assert "DEPENDENCY_API" in router.calls[1]
    assert "PlayerDataManager.SetState" in router.calls[1]
    assert "calling it with ':'" in router.calls[1]
    assert "services.PlayerDataManager.GetState(player," in code
    assert "services.PlayerDataManager:GetState(" not in code
    assert "services.PlayerDataManager:SetState(" not in code
    assert not dependency_api_errors(service, plan, code)


def test_replay_invalid_production_candidate_is_caught_in_scoped_attempt():
    service, plan = _plan()
    from roblox_mod_ai.host_service_codegen import _shell
    candidate = _shell("""if not #({ ... }) then return Service end
local args = { ... }
local amount = tonumber(args[1]) or 0
local profile = services.PlayerDataManager:GetState(player, "RMMInventory") or {}
profile.resources = (profile.resources or 0) + amount
services.PlayerDataManager:SetState(player, "RMMInventory", profile, true)
return true""")
    errors = dependency_api_errors(service, plan, candidate)
    assert any("GetState" in error and "dot function" in error for error in errors)
    assert any("SetState" in error and "not exported" in error for error in errors)
