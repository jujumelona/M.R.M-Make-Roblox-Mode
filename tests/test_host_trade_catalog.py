"""Host-owned shop transactions replacing small-model Luau failure 26.

Tests use arbitrary module names and gameplay obligations, not the prompt,
source hash or exact failed module name. The same data ABI supports several
separately designed market entry points and one shared persistent ledger.
"""
from copy import deepcopy

import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_trade_catalog import (
    _required_categories, _validate, eligible_trade_catalog,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class Model:
    def __init__(self):
        self.calls = []

    def complete(self, *_a, **_kw):
        raise AssertionError("No model-authored purchase Luau is permissible")

    def complete_json(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if {"section", "weapon", "crew", "ship"} == set(
                _required_categories(prompt)):
            kinds = ("section", "weapon", "crew", "ship")
        else:
            kinds = ("weapon", "crew", "ship")
        return {"items": [
            {"id": "product_" + kind, "label": "Option " + kind,
             "category": kind, "cost": 20 + i * 10,
             "bonus": 0 if kind == "section" else i + 1}
            for i, kind in enumerate(kinds)
        ]}


def _plan():
    def mod(name, description, client=False):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name, description=description,
            kind=ModuleKind.CLIENT_SCRIPT if client else ModuleKind.SERVER_MODULE,
            file_path=("src/client/" + name + ".client.luau" if client
                       else "src/server/" + name + ".luau"),
            roblox_service=(RobloxService.STARTER_PLAYER_SCRIPTS
                            if client else RobloxService.SERVER_SCRIPT_SERVICE),
        )

    market = mod("SpaceGoodsMarketServer",
        "The server maintains a fixed, server-priced catalog of tradeable "
        "ship sections, weapon upgrades, crew upgrades and ship-performance "
        "upgrades. Every trade request validates earned currency and the "
        "item in the catalog, checks ownership, deducts currency and grants "
        "a new owned item or upgrade in the inventory. It rejects invalid "
        "requests without changing inventory or currency.")
    market_ui = mod("SpaceGoodsMarketClient",
                    "Show server-priced goods and trade feedback.", True)
    second = mod("ArmamentMarketServer",
        "The server maintains a validated catalog of weapon, crew and "
        "ship-performance items at fixed prices in earned currency. "
        "A trade request validates inventory and player-owned currency, "
        "deducts coins and adds the item into inventory, records each "
        "accepted transaction, and rejects untrusted input without changing "
        "inventory or balance.")
    second_ui = mod("ArmamentMarketClient",
                    "Display catalog prices and accepted purchases.", True)
    remotes = {
        "BuyGoods": {"service": market.name, "kind": "RemoteFunction"},
        "BuyEquipment": {"service": second.name, "kind": "RemoteFunction"},
    }
    return RobloxProposal(
        requested_prompt="Build a ship with earned items and equip a crew",
        game_title="Economy", description="Two independent catalogs",
        game_design={"dynamic_design": {
            "host_actions": remotes,
            "remotes": {key: "RemoteFunction" for key in remotes},
            "module_remotes": {
                market.module_id: ["BuyGoods"], market_ui.module_id: ["BuyGoods"],
                second.module_id: ["BuyEquipment"],
                second_ui.module_id: ["BuyEquipment"],
            },
        }},
        modules=[market, market_ui, second, second_ui],
    )


def test_trade_catalog_has_no_model_luau_and_two_shops_share_state():
    plan = _plan()
    scope = generation_scope(plan)
    assert [row["strategy"] for row in scope["modules"]] == [
        "host_declarative_trade_catalog"] * 4
    assert scope["model_action_risk_modules"] == []
    model = Model()
    generated = LuauCodeGenerator(model).generate_all_modules(plan)
    assert len(model.calls) == 2  # only two small JSON price/item lists
    assert all(kw["json_schema"]["required"] == ["items"]
               for _, kw in model.calls)
    for module in generated:
        assert module.code
        issues = [i for i in LuauStaticAnalyzer().analyze_source(
            module.code, module.file_path) if i.severity == "ERROR"]
        assert not issues, issues
    for server in (generated[0], generated[2]):
        assert 'GetState(player, "RMMTradeEntitlements")' in server.code
        assert "coins.Value -= item.cost" in server.code
        assert "owned[canonical]" in server.code
        assert 'services.PlayerDataManager:GetState' not in server.code
        assert "local ALIASES" in server.code
        assert "if coins.Value < item.cost then" in server.code
        assert "player:SetAttribute" in server.code
        assert "section" in server.code
    for client in (generated[1], generated[3]):
        assert "remote:InvokeServer(upgrade.id)" in client.code


def test_catalog_rejects_invalid_model_output_without_fabricating_prices():
    required = {"section", "weapon", "crew", "ship"}
    valid = {"items": [
        {"id": "one_" + kind, "label": "Item " + kind, "category": kind,
         "cost": 10, "bonus": 0}
        for kind in sorted(required)
    ]}
    assert len(_validate(valid, required)) == 4
    for changed in [
        dict(valid, items=[valid["items"][0]]),
        {"items": [dict(row, cost=-5) for row in valid["items"]]},
        {"items": [dict(row, id="same") for row in valid["items"]]},
        {"items": [dict(row, bonus=50000) for row in valid["items"]]},
    ]:
        with pytest.raises(ValueError):
            _validate(changed, required)


def test_unsupported_trading_and_transport_does_not_get_fake_host_success():
    for variant in ("p2p", "zero_args", "wrong_remote", "removed_server"):
        plan = _plan()
        server = plan.modules[0]
        if variant == "p2p":
            server.description += " Players use peer-to-peer item exchange."
        elif variant == "zero_args":
            plan.game_design["dynamic_design"]["host_actions"]["BuyGoods"]["max_args"] = 0
        elif variant == "wrong_remote":
            plan.game_design["dynamic_design"]["module_remotes"][
                plan.modules[1].module_id] = ["AnotherAction"]
        else:
            plan.modules.remove(server)
        assert eligible_trade_catalog(plan.modules[0] if variant != "removed_server"
                                      else plan.modules[0], plan) is None if variant != "wrong_remote" else True
        if variant == "wrong_remote":
            assert eligible_trade_catalog(plan.modules[1], plan) is None
