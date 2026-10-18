"""Regression for the real proposal (11) failure at EconomyLedger.

The ledger is a reusable server-only ModuleScript, not a huge generated Script
that invents Roblox APIs. The rest of the game must still be authored/verified.
"""
from roblox_mod_ai.economy_core import (
    is_supported_economy_ledger, normalize_economy_ledger, render_economy_ledger,
)
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def proposal(behavior="Server-authoritative currency ledger validates balances, "
                      "prevents overspending and persists player credits."):
    module = RobloxModuleSpec(
        module_id="dyn_economy", name="EconomyLedger", kind="server_script",
        file_path="src/server/EconomyLedger.server.luau",
        roblox_service="ServerScriptService", description=behavior,
        depends_on=["mod_network_bridge"],
    )
    plan = RobloxProposal(
        requested_prompt="Mining, trading and buying spaceship parts",
        game_title="SpaceGame", description="Space game",
        game_design={"dynamic_design": {"remotes": {"RequestMineNode": "RemoteEvent"},
                                        "module_remotes": {}}},
        modules=[module],
    )
    return plan, module


def test_old_failed_plan_upgrades_to_requireable_economy_service():
    plan, mod = proposal()
    assert is_supported_economy_ledger(mod)
    assert normalize_economy_ledger(plan) is True
    assert mod.file_path == "src/server/EconomyLedger.luau"
    assert mod.roblox_service == "ServerScriptService"
    assert mod.depends_on == []
    assert normalize_economy_ledger(plan) is False
    source = render_economy_ledger(mod)
    assert "function EconomyLedger.TrySpend" in source
    assert "function EconomyLedger.Grant" in source
    assert "function EconomyLedger.GetBalance" in source
    assert 'FindFirstChild("Coins")' in source
    assert "game.Players.LocalPlayer" not in source
    assert "GetDataStore" not in source
    # No model router call may be required for this inspected infrastructure.
    generated = LuauCodeGenerator().generate_module_code(mod, plan)
    assert generated == source
    assert not [d for d in LuauStaticAnalyzer().analyze_source(
        source, mod.file_path) if d.severity == "ERROR"]


def test_no_generic_economy_keyword_replacement():
    plan, mod = proposal("Server handles shop UI interactions and purchase effects.")
    assert not is_supported_economy_ledger(mod)
    assert not normalize_economy_ledger(plan)


def test_remote_owned_ledger_is_not_silently_replaced():
    plan, mod = proposal()
    plan.game_design["dynamic_design"]["module_remotes"] = {
        mod.module_id: ["PurchaseCredits"]
    }
    assert not normalize_economy_ledger(plan)
    assert mod.file_path.endswith(".server.luau")
