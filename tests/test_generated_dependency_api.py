"""Reject service misuse recorded in proposal15 after syntax is repaired."""
import pytest

from roblox_mod_ai.agent_loop import LuauGenerationError, RobloxCodeRepairAgent
from roblox_mod_ai.server_interface_audit import inspect_dynamic_server_interfaces
from roblox_mod_ai.spec import RobloxModuleSpec
from test_callable_host_data import _plan


def _service_plan():
    proposal, _data, module = _plan()
    proposal.game_design["pre_design_research"] = {"evidence": []}
    return module, proposal


def _source(body):
    return ("--!strict\nlocal Service = {}\nfunction Service.start(services)\n"
            + body + "\nworkspace:SetAttribute('ModeActive', true)\nend\nreturn Service\n")


@pytest.mark.parametrize("body", [
    'local data = game:GetService("PlayerDataManager")\nprint(data)',
    'local data = services.PlayerDataManager\ndata.start(services)',
    'local data = services.PlayerDataManager\nfunction data.OnReady(callback) callback(nil) end',
    'local data = services.PlayerDataManager\ndata.OnReady = function(callback) callback(nil) end',
    'local data = services.PlayerDataManager\nprint(data.GetBalance(nil))',
])
def test_syntax_valid_dependency_misuse_rejected_during_generation_and_final_audit(monkeypatch, body):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, proposal = _service_plan()
    module.code = _source(body)

    class Model:
        def complete(self, prompt, **kwargs):
            return module.code

    with pytest.raises(LuauGenerationError) as failure:
        RobloxCodeRepairAgent(Model()).repair(module, proposal, attempts=1)
    assert any("DEPENDENCY_API" in d for d in failure.value.diagnostics)
    audit = inspect_dynamic_server_interfaces(proposal)
    assert not audit["passed"]
    assert any("DEPENDENCY_API" in c["detail"] and not c["passed"] for c in audit["checks"])


def test_real_alias_api_and_quoted_diagnostics_are_accepted(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, proposal = _service_plan()
    module.code = _source('''local data = services.PlayerDataManager
data.OnReady(function(player)
    local state = data.GetState(player, "ShipService")
    if state then state.initialized = true end
end)
-- game:GetService("PlayerDataManager")
print('data.start(services); function data.OnReady(callback) end')''')

    class Model:
        def complete(self, prompt, **kwargs):
            return module.code

    actual = RobloxCodeRepairAgent(Model()).repair(module, proposal, attempts=1)
    assert "state.initialized = true" in actual
    assert inspect_dynamic_server_interfaces(proposal)["passed"]


def test_shadowed_local_alias_does_not_invent_a_dependency_error():
    module, proposal = _service_plan()
    module.code = _source('''local data = services.PlayerDataManager
local function readForeignData(data)
    return data.GetBalance(nil)
end
print(data, readForeignData)''')
    assert inspect_dynamic_server_interfaces(proposal)["passed"]


def test_dependency_return_value_is_not_an_alias_for_the_service_table():
    module, proposal = _service_plan()
    proposal.modules.append(RobloxModuleSpec(
        module_id="dyn_planets", name="PlanetService", kind="server_module",
        file_path="src/server/PlanetService.luau", roblox_service="ServerScriptService",
        code='''local Service = {}
function Service.start(services) workspace:SetAttribute("PlanetsReady", true) end
function Service.GetPlanet(player) return workspace:FindFirstChild("Planet") end
return Service'''))
    module.code = _source('''local planet = services.PlanetService.GetPlanet(nil)
if planet then print(planet:FindFirstChild("Spawn")) end''')
    assert inspect_dynamic_server_interfaces(proposal)["passed"]


def test_nested_table_member_with_same_name_as_alias_is_not_a_dependency():
    module, proposal = _service_plan()
    module.code = _source('''local data = services.PlayerDataManager
local snapshot = {}
snapshot.data = {}
function snapshot.data.GetBalance(player) return 10 end
print(snapshot. data.GetBalance(nil), data)''')
    assert inspect_dynamic_server_interfaces(proposal)["passed"]
