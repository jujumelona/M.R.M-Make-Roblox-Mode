"""One ship builder must own transactions across market and assembly routes."""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_purchase_facade import (
    eligible_ship_purchase_facade, try_ship_purchase_facade,
)
from roblox_mod_ai.host_ship_sections import eligible_ship_sections
from roblox_mod_ai.host_upgrade_declarative import eligible_declarative_upgrade
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class DataOnly:
    def __init__(self):
        self.calls = []

    def complete(self, *_args, **_kwargs):
        raise AssertionError("Ship currency and installed-parts code must be host-owned")

    def complete_json(self, _prompt, **kwargs):
        self.calls.append(kwargs)
        return deepcopy({"slots": [
            {"id": "engine", "label": "Engine", "options": [
                {"id": "thruster", "label": "Thruster", "cost": 40, "performance": 8},
                {"id": "booster", "label": "Booster", "cost": 70, "performance": 14},
            ]},
            {"id": "hull", "label": "Hull", "options": [
                {"id": "armor", "label": "Armor", "cost": 55, "performance": 9},
            ]},
        ]})


def _plan():
    def mod(name, description, client=False):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name,
            kind=ModuleKind.CLIENT_SCRIPT if client else ModuleKind.SERVER_MODULE,
            file_path=("src/client/" + name + ".client.luau" if client
                       else "src/server/" + name + ".luau"),
            roblox_service=(RobloxService.STARTER_PLAYER_SCRIPTS if client
                            else RobloxService.SERVER_SCRIPT_SERVICE),
            description=description,
        )
    market = mod("PhysicalShipMarketServer",
        "The server owns the ship assembly state and validates every part purchase. "
        "Players request specific ship parts using earned game currency. "
        "After checking ownership and valid cost, the server deducts currency, "
        "marks the part as owned, and adds it to the ship assembly state. "
        "The assembled ship's performance and expansion properties also "
        "include weapon and crew upgrades.")
    market_ui = mod("PhysicalShipMarketClient",
                    "Display catalog and request valid part purchases.", True)
    builder = mod("VehicleConfigurationServer",
        "The server owns the ship assembly registry and validates every part "
        "creation, placement and removal action. Players may add a modular "
        "ship part using earned game currency, provided it is not installed. "
        "The server deducts the part cost, records the installed part in the "
        "ship assembly registry, updates performance and on removal refunds "
        "the part cost, removing the part and recalculating performance. "
        "Invalid purchases and duplicates are rejected.")
    builder_ui = mod("VehicleConfigurationClient",
                     "Choose parts to install, replace and remove.", True)
    actions = {
        "BuyPart": {"service": market.name, "kind": "RemoteFunction"},
        "EditShip": {"service": builder.name, "kind": "RemoteFunction"},
    }
    dynamic = {
        "host_actions": actions,
        "remotes": {"BuyPart": "RemoteFunction", "EditShip": "RemoteFunction"},
        "module_remotes": {
            market.module_id: ["BuyPart"], market_ui.module_id: ["BuyPart"],
            builder.module_id: ["EditShip"], builder_ui.module_id: ["EditShip"],
        },
    }
    return RobloxProposal(
        requested_prompt="Craft modular vehicles from earned currency",
        game_title="Generic ship workshop", description="Ship market and builder",
        game_design={"dynamic_design": dynamic},
        modules=[market, market_ui, builder, builder_ui],
    )


def test_market_delegates_to_one_builder_and_never_owns_a_second_ledger():
    plan = _plan()
    market, market_ui, builder, builder_ui = plan.modules
    assert eligible_ship_sections(builder, plan) is not None
    assert eligible_ship_purchase_facade(market, plan) == (
        market.name, "BuyPart", builder.name)
    assert eligible_ship_purchase_facade(market_ui, plan) is not None
    assert eligible_declarative_upgrade(market, plan) is None
    strategies = [row["strategy"] for row in generation_scope(plan)["modules"]]
    assert strategies == [
        "host_ship_purchase_facade", "host_ship_purchase_facade",
        "host_declarative_ship_sections", "host_declarative_ship_sections",
    ]
    model = DataOnly()
    coder = LuauCodeGenerator(model)
    sources = [coder.generate_with_self_correction(m, plan) for m in plan.modules]
    assert len(model.calls) == 1
    assert model.calls[0]["json_schema"]["required"] == ["slots"]
    service = sources[0]
    builder_code = sources[2]
    assert 'local BUILDER_NAME = "VehicleConfigurationServer"' in service
    assert 'builder.handleAction(player, services, "create", part.slot, part.variant)' in service
    assert 'local MARKET = {' in service
    assert '["engine/thruster"] = {slot = "engine"' in service
    assert 'services.PlayerDataManager.GetState(player, "RMMShipSections")' not in service
    assert 'manager.GetState(player, "RMMShipSections")' in service
    assert 'RMMUpgradePurchases' not in service
    assert 'coins.Value -= netCharge' in builder_code
    assert 'sections[slotId] = nil' in builder_code
    assert 'remote:InvokeServer("buy", part.id)' in sources[1]
    assert 'remote:InvokeServer(action, slotId, optionId)' in sources[3]
    for m, src in zip(plan.modules, sources):
        errors = [diag for diag in LuauStaticAnalyzer().analyze_source(
            src, m.file_path) if diag.severity == "ERROR"]
        assert not errors, [(x.rule, x.line_number, x.message) for x in errors]


def test_market_requires_single_valid_builder_and_cannot_forge_a_purchase():
    p = _plan()
    m, ui, b, b_ui = p.modules
    p.modules.remove(b)
    assert eligible_ship_purchase_facade(m, p) is None
    assert eligible_declarative_upgrade(m, p) is None

    p = _plan()
    m, ui, b, b_ui = p.modules
    p.game_design["dynamic_design"]["host_actions"]["EditShip"]["kind"] = "RemoteEvent"
    assert eligible_ship_purchase_facade(m, p) is None

    p = _plan()
    m, ui, b, b_ui = p.modules
    p.game_design["dynamic_design"]["module_remotes"][ui.module_id] = ["WrongRemote"]
    assert eligible_ship_purchase_facade(ui, p) is None

    p = _plan()
    m, ui, b, b_ui = p.modules
    p.modules.append(deepcopy(b))
    p.modules[-1].name = "AnotherBuilderServer"
    p.game_design["dynamic_design"]["host_actions"]["AnotherEdit"] = {
        "service": "AnotherBuilderServer", "kind": "RemoteFunction"}
    p.game_design["dynamic_design"]["remotes"]["AnotherEdit"] = "RemoteFunction"
    assert eligible_ship_purchase_facade(m, p) is None
