"""Regression for upload failure_logs (11), proposal (23).

The generated server used non-existent APIs and unbound variables; the 9B
coder then tried to write a CLIENT service with malformed Luau syntax. Both
are now built from one literal shared upgrade catalog by the host.
"""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_upgrade_purchase import render_host_upgrade_purchase
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.luau_service_contract import service_contract_checks
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class NoModel:
    def complete(self, *_a, **_kw):
        raise AssertionError("Never use the small AI to generate the purchase service or UI")

    def complete_json(self, *_a, **_kw):
        raise AssertionError("Never use the small AI for an already authored purchase contract")


def proposal23_purchase():
    service = "TradingBasedWeaponCrewAndFEA0A71Server"
    remote = "TradingBasedWeaponCrewAndFEA0A71Action"
    owner = RobloxModuleSpec(
        module_id="dyn_e6632b081f21", name=service,
        kind=ModuleKind.SERVER_MODULE, file_path=f"src/server/{service}.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server maintains the player's owned upgrade inventory and validates "
            "every upgrade purchase against the player's available trading currency "
            "before applying it. A purchase is only committed when the player's "
            "currency balance covers the upgrade's full cost; otherwise the request "
            "is rejected and the balance is left unchanged. On a valid purchase, "
            "the server records the upgrade in the player's inventory, applies the "
            "corresponding stat increase to the player's weapon, crew, or spaceship, "
            "and deducts the currency. The server also prevents duplicate purchases."
        ),
    )
    ui = RobloxModuleSpec(
        module_id="dyn_5d3d15e75078",
        name="TradingBasedWeaponCrewAndFEA0A71Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/TradingBasedWeaponCrewAndFEA0A71Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=(
            "Client displays available trading currency, costs, and upgrade status. "
            "Client invokes a server-confirmed purchase."
        ),
        depends_on=["mod_network_bridge"],
    )
    return RobloxProposal(
        game_title="SpaceEconomy", description="Mine then purchase ship improvements",
        requested_prompt="우주모드 자원파밍 돈모으기 우주선 무기 선원 구매 거래 업그레이드",
        game_design={"dynamic_design": {
            "host_actions": {remote: {"service": service, "kind": "RemoteFunction"}},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {owner.module_id: [remote], ui.module_id: [remote]},
            "world_objects": [],
        }},
        modules=[owner, ui],
    )


def test_actual_failed_client_and_prior_server_are_both_host_owned():
    p = proposal23_purchase()
    generator = LuauCodeGenerator(NoModel())
    for module in p.modules:
        module.code = "-- obsolete model-generated bogus contract"
    rendered = generator.generate_all_modules(p)
    assert len(rendered) == 2
    for module in rendered:
        assert module.code == render_host_upgrade_purchase(module, p)
        assert module.code == render_host_gameplay(module, p)
        assert "GetService(\"PlayerDataManager\")" not in module.code
        assert "require(mod_network_bridge)" not in module.code
        assert "FireServerSide" not in module.code


def test_purchase_server_controls_cost_idempotence_and_saved_stats():
    p = proposal23_purchase()
    server = render_host_gameplay(p.modules[0], p)
    assert "local CATALOG =" in server
    assert "weapon = {cost = 50" in server
    assert "crew = {cost = 80" in server
    assert "ship = {cost = 120" in server
    assert 'GetState(player, "RMMUpgradePurchases")' in server
    assert "purchases[itemId] ~= nil" in server
    assert "coins.Value < item.cost" in server
    assert "coins.Value -= item.cost" in server
    assert "purchases[itemId] = true" in server
    assert "publish(player, purchases)" in server
    assert "OnReady(function(player)" in server
    assert "purchases[itemId] ~= nil" in server
    assert "select(\"#\", ...) ~= 1" in server
    assert "ServerScriptService" not in server
    assert all(r["passed"] for r in service_contract_checks(
        p.modules[0].name, server, require_start=True, needs_action=True
    ))


def test_exact_remote_and_host_rendered_ui_only_transmits_upgrade_id():
    p = proposal23_purchase()
    client = render_host_gameplay(p.modules[1], p)
    assert 'WaitForChild("TradingBasedWeaponCrewAndFEA0A71Action")' in client
    assert 'remote:InvokeServer(entry.id)' in client
    assert 'remote:IsA("RemoteFunction")' in client
    assert 'type(result) == "table" and result.success == true' in client
    assert "Coins" in client
    assert "player:SetAttribute" not in client
    assert "GetDataStore" not in client
    assert "local Service = {}" not in client
    bootstrap = render_dynamic_server_bootstrap(p)
    assert 'WaitForChild("TradingBasedWeaponCrewAndFEA0A71Action", 20)' in bootstrap
    assert "remote.OnServerInvoke = function(player, ...)" in bootstrap


def test_real_luau_parser_static_checks_all_affected_sources():
    p = proposal23_purchase()
    analyzer = LuauStaticAnalyzer()
    for module in p.modules:
        source = render_host_gameplay(module, p)
        errors = [d for d in analyzer.analyze_source(source, module.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(d.rule, d.line_number, d.message) for d in errors]


def test_wrong_transport_missing_owner_and_unrelated_trade_fail_closed():
    p = proposal23_purchase()
    design = p.game_design["dynamic_design"]
    remote = "TradingBasedWeaponCrewAndFEA0A71Action"
    design["host_actions"][remote]["kind"] = "RemoteEvent"
    assert render_host_gameplay(p.modules[0], p) is None
    assert render_host_gameplay(p.modules[1], p) is None
    p = proposal23_purchase()
    p.modules.pop(0)
    assert render_host_gameplay(p.modules[0], p) is None
    p = proposal23_purchase()
    p.modules[0].description = "Generic currency trading between players"
    assert render_host_gameplay(p.modules[0], p) is None
    p = proposal23_purchase()
    p.game_design["dynamic_design"]["module_remotes"][p.modules[1].module_id] = []
    assert render_host_gameplay(p.modules[1], p) is None
    p = proposal23_purchase()
    p.game_design["dynamic_design"]["host_actions"][remote]["max_args"] = 0
    assert render_host_gameplay(p.modules[0], p) is None


def test_host_purchase_not_enabled_for_different_source_request():
    p = proposal23_purchase()
    p.requested_prompt = "Plant flowers and water a garden"
    assert render_host_gameplay(p.modules[0], p) is None
    assert render_host_gameplay(p.modules[1], p) is None



def test_next_purchase_service_after_combined_mining_and_ship_build_is_name_agnostic():
    # The real ZIP (14) has ShopPurchaseAndPerformanc... instead of the
    # historical TradingBasedWeaponCrewAnd... pattern.
    from roblox_mod_ai.generation_scope import generation_scope
    p=proposal23_purchase()
    owner,client=p.modules
    owner.name="ShopPurchaseAndPerformancFEA0A71Server"
    owner.file_path="src/server/"+owner.name+".luau"
    client.name="ShopPurchaseAndPerformancFEA0A71Client"
    client.file_path="src/client/"+client.name+".client.luau"
    owner.description=(
        "The server owns all purchase validation and upgrade application. "
        "When a player requests a purchase, the server checks the player's "
        "owned in-game currency against the item's price, deducts the "
        "currency only after the transaction is accepted, and applies "
        "the weapon, crew, or spaceship performance upgrade to the player's "
        "persistent inventory and spaceship stats. Each purchase is validated "
        "against the current currency balance, price and existing upgrade "
        "state to prevent overspending, duplicate purchases and concurrent "
        "transactions. Currency is stored in a server-owned data store with "
        "session locking, so reconnects cannot duplicate purchases."
    )
    remote="TradingBasedWeaponCrewAndFEA0A71Action"
    p.game_design["dynamic_design"]["host_actions"][remote]["service"]=owner.name
    scope=generation_scope(p)
    assert all(x["strategy"]=="host_verified_template"
               for x in scope["modules"] if x["name"] in {owner.name,client.name})
    for module in (owner,client):
        code=LuauCodeGenerator(NoModel()).generate_with_self_correction(module,p)
        assert code==render_host_upgrade_purchase(module,p)
        assert not [d for d in LuauStaticAnalyzer().analyze_source(code,module.file_path)
                    if d.severity=="ERROR"]
    owner.description="The server only provides an unrelated player inventory."
    assert render_host_upgrade_purchase(owner,p) is None



def test_generic_semantic_router_handles_legacy_lightweight_proposal_without_modules():
    from types import SimpleNamespace
    sample=proposal23_purchase()
    plan=SimpleNamespace(game_design=sample.game_design,
                         requested_prompt=sample.requested_prompt)
    assert render_host_upgrade_purchase(sample.modules[0],plan) is None
    assert render_host_upgrade_purchase(sample.modules[1],plan) is None
