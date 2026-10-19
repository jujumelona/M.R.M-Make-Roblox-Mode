"""Regression for production of plan (11): scripts must share server services.

The host, not the 9B model, builds the startup entry point and validates the
ModuleScript contract. Static checks are not Roblox Studio playtests.
"""
import pytest

from roblox_mod_ai.agent_loop import LuauGenerationError, RobloxCodeRepairAgent
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.server_modules import (
    normalize_dynamic_server_modules, render_dynamic_server_bootstrap,
)
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal


def _proposal():
    econ = RobloxModuleSpec(
        module_id="dyn_ledger", name="EconomyLedger", kind="server_script",
        file_path="src/server/EconomyLedger.server.luau",
        roblox_service="ServerScriptService",
        description="Server authoritative currency ledger manages credits and balances.",
        depends_on=["mod_network_bridge"],
    )
    mine = RobloxModuleSpec(
        module_id="dyn_mine", name="MiningActionHandler", kind="server_script",
        file_path="src/server/MiningActionHandler.server.luau",
        roblox_service="ServerScriptService",
        description="Server validates mining reach and grants ore via economy ledger.",
        depends_on=["mod_network_bridge"],
    )
    return RobloxProposal(
        requested_prompt="Mine ore and sell it for credits",
        game_title="SpaceMiner", description="Mine and trade",
        game_design={"dynamic_design": {
            "remotes": {"RequestMineNode": "RemoteEvent"},
            "module_remotes": {"dyn_mine": ["RequestMineNode"]},
            "world_objects": [],
        }},
        modules=[econ, mine],
    )


def test_convert_legacy_dynamic_scripts_into_loadable_modules_and_one_bootstrap():
    plan = _proposal()
    assert normalize_dynamic_server_modules(plan)
    assert not normalize_dynamic_server_modules(plan)
    assert len(plan.modules) == 3
    assert {m.name for m in plan.modules} == {
        "EconomyLedger", "MiningActionHandler", "RMMServerBootstrap"
    }
    assert all(m.file_path.endswith(".luau") and
               not m.file_path.endswith(".server.luau")
               for m in plan.modules if m.module_id.startswith("dyn_"))
    assert all(m.kind == ModuleKind.SERVER_MODULE
               for m in plan.modules if m.module_id.startswith("dyn_"))
    boot = next(m for m in plan.modules if m.name == "RMMServerBootstrap")
    assert set(boot.depends_on) == {"dyn_ledger", "dyn_mine"}
    code = LuauCodeGenerator().generate_module_code(boot, plan)
    assert code == render_dynamic_server_bootstrap(plan)
    assert "require(scriptModule)" in code
    assert "service.start(services)" in code
    assert '"EconomyLedger"' in code
    assert '"MiningActionHandler"' in code
    assert not [d for d in LuauStaticAnalyzer().analyze_source(
        code, boot.file_path) if d.severity == "ERROR"]


def test_service_generator_rejects_bare_script_without_export(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    plan = _proposal()
    normalize_dynamic_server_modules(plan)
    mining = next(m for m in plan.modules if m.name == "MiningActionHandler")

    class Router:
        def complete(self, prompt, **kwargs):
            assert "SERVER MODULE CONTRACT" in prompt
            return ("--!strict\n"
                    "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                    "local remotes = ReplicatedStorage:WaitForChild('Remotes')\n"
                    "remotes:WaitForChild('RequestMineNode').OnServerEvent:Connect(function() end)\n")

    with pytest.raises(LuauGenerationError) as exc:
        RobloxCodeRepairAgent(Router()).repair(mining, plan, attempts=1)
    assert any("must return its service table" in item
               for item in exc.value.diagnostics)


def test_server_module_contract_accepts_real_remote_registration(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    plan = _proposal()
    normalize_dynamic_server_modules(plan)
    mining = next(m for m in plan.modules if m.name == "MiningActionHandler")

    class Router:
        def complete(self, prompt, **kwargs):
            return ("--!strict\n"
                    "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                    "local Mining = {}\n"
                    "function Mining.start(services)\n"
                    "    local mine = ReplicatedStorage:WaitForChild('Remotes'):WaitForChild('RequestMineNode')\n"
                    "    mine.OnServerEvent:Connect(function(player, node)\n"
                    "        if player.Parent ~= game:GetService('Players') then return end\n"
                    "        if not node or not node:IsA('BasePart') then return end\n"
                    "        services.EconomyLedger.Grant(player, 1)\n"
                    "    end)\n"
                    "end\n"
                    "return Mining\n")

    result = RobloxCodeRepairAgent(Router()).repair(mining, plan, attempts=1)
    assert "EconomyLedger.Grant" in result
    assert "function Mining.start" in result

def test_coder_contract_does_not_expose_unrelated_services():
    from roblox_mod_ai.server_modules import module_bootstrap_contract
    plan = _proposal()
    extra = RobloxModuleSpec(
        module_id="dyn_colony", name="PlanetColonizationServer",
        kind="server_script", file_path="src/server/PlanetColonizationServer.server.luau",
        roblox_service="ServerScriptService",
        description="Own planet colonization state.")
    plan.modules.append(extra)
    normalize_dynamic_server_modules(plan)
    mine = next(m for m in plan.modules if m.name == "MiningActionHandler")
    ledger = next(m for m in plan.modules if m.name == "EconomyLedger")
    ledger.code = ("local Service = {}\n"
                   "function Service.start(services) workspace:SetAttribute('Ready', true) end\n"
                   "function Service.Grant(player, amount) player:SetAttribute('Credits', amount) end\n"
                   "return Service")
    contract = module_bootstrap_contract(mine, plan)
    assert "PlanetColonizationServer" not in contract
    assert "EconomyLedger" in contract
    assert "Grant" in contract
