"""A bounded data catalog replaces repeated invalid Luau purchase generation."""
from copy import deepcopy
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_catalog_purchase import (
    _validated_entries, eligible_catalog_purchase, try_catalog_purchase,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class DataOnlyModel:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"entries": [
            {"id": "laserA", "label": "Laser cannon", "cost": 25,
             "slot": "weapon", "effect": "damage", "bonus": 3},
            {"id": "shieldB", "label": "Shield package", "cost": 50,
             "slot": "shield", "effect": "shield", "bonus": 5},
        ]}

    def complete(self, *_args, **_kwargs):
        raise AssertionError("Never generate Luau source for host-owned purchase")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return deepcopy(self.result)


def _plan():
    server_name = "EquipmentTradingPurchaseServer"
    remote = "EquipmentTradingPurchaseAction"
    description = ("The server owns the trading purchase flow. It validates earned "
                   "currency and trading catalog item availability, validates the "
                   "requested spaceship part is owned by the player, then applies "
                   "the chosen item upgrade and deducts currency.")
    server = RobloxModuleSpec(
        module_id="dyn_purchase_server", name=server_name,
        kind=ModuleKind.SERVER_MODULE,
        file_path=f"src/server/{server_name}.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=description,
    )
    client = RobloxModuleSpec(
        module_id="dyn_purchase_client", name="EquipmentTradingPurchaseClient",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/EquipmentTradingPurchaseClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Show the purchase catalog and server-confirmed results.",
        depends_on=["mod_network_bridge"],
    )
    return RobloxProposal(
        game_title="Equipment shop", description="Buy shop equipment with earned currency",
        requested_prompt="Construct a ship and purchase upgrades for owned equipment",
        game_design={"dynamic_design": {
            "host_actions": {remote: {"service": server_name, "kind": "RemoteFunction"}},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {server.module_id: [remote], client.module_id: [remote]},
        }},
        modules=[server, client],
    )


def test_replay_purchase_requires_only_two_short_data_entries_and_host_owns_code():
    p = _plan()
    model = DataOnlyModel()
    coder = LuauCodeGenerator(model)
    for m in p.modules:
        assert eligible_catalog_purchase(m, p) is not None
    server = coder.generate_module_code(p.modules[0], p)
    client = coder.generate_module_code(p.modules[1], p)
    assert len(model.calls) == 1
    assert model.calls[0][1]["max_tokens"] <= 700
    assert model.calls[0][1]["json_schema"]["required"] == ["entries"]
    assert "local CATALOG = {" in server
    assert '["laserA"] = {cost = 25, slot = "weapon"' in server
    assert 'GetState(player, "RMMShipSections")' in server
    assert 'section.owned ~= true then return false' in server
    assert 'coins.Value -= item.cost' in server
    assert 'purchased[itemId] = true' in server
    assert "remote:InvokeServer(item.id)" in client
    assert 'WaitForChild("EquipmentTradingPurchaseAction", 20)' in client
    assert "GetDataStore" not in server + client
    assert "local Service = {}" in server
    analyzer = LuauStaticAnalyzer()
    for m, code in zip(p.modules, (server, client)):
        errors = [d for d in analyzer.analyze_source(code, m.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(e.rule, e.message) for e in errors]


@pytest.mark.parametrize("entry", [
    {"id": "a", "label": "Laser", "cost": -1, "slot": "weapon",
     "effect": "damage", "bonus": 3},
    {"id": "a", "label": "Laser", "cost": 20, "slot": "weapon",
     "effect": "inject_code", "bonus": 3},
    {"id": "a", "label": "Laser", "cost": True, "slot": "weapon",
     "effect": "damage", "bonus": 3},
    {"id": "function()", "label": "Laser", "cost": 20, "slot": "weapon",
     "effect": "damage", "bonus": 3},
    {"id": "a", "label": "Laser", "cost": 20, "slot": "weapon\nend",
     "effect": "damage", "bonus": 3},
])
def test_model_catalog_cannot_inject_source_or_free_items(entry):
    with pytest.raises(ValueError):
        _validated_entries({"entries": [entry]})


def test_fail_closed_when_model_does_not_supply_valid_game_specific_data():
    p = _plan()
    model = DataOnlyModel({"entries": [{"id": "free", "cost": 0}]})
    with pytest.raises(ValueError, match="HOST_DECLARATIVE_CATALOG_EXHAUSTED"):
        LuauCodeGenerator(model).generate_module_code(p.modules[0], p)
    assert len(model.calls) == 2



def test_upgrade_market_uses_same_host_transaction_without_full_luau():
    # An upgrade *market* is semantically different from a new ship-part
    # installation. A purchase requires an already installed ship section.
    p = _plan()
    p.modules[0].description = (
        "The server owns a catalog of purchasable ship upgrades at fixed "
        "cost in earned game currency. Every purchase validates ownership "
        "and the balance; purchased upgrades cannot be bought twice. "
        "The upgrade adds a performance effect to the player's ship."
    )
    assert eligible_catalog_purchase(p.modules[0], p) is not None
    assert eligible_catalog_purchase(p.modules[1], p) is not None
    model = DataOnlyModel()
    gen = LuauCodeGenerator(model)
    s = gen.generate_module_code(p.modules[0], p)
    c = gen.generate_module_code(p.modules[1], p)
    assert len(model.calls) == 1
    assert 'GetState(player, "RMMShipSections")' in s
    assert "slot" in s and "coins.Value -= item.cost" in s
    assert "remote:InvokeServer(item.id)" in c


def test_irrelevant_plan_and_transport_never_become_host_owned_purchase():
    p = _plan()
    p.modules[0].description = "Server offers a menu of cosmetic clothes."
    assert eligible_catalog_purchase(p.modules[0], p) is None
    p = _plan()
    p.game_design["dynamic_design"]["host_actions"]["EquipmentTradingPurchaseAction"]["kind"] = "RemoteEvent"
    assert eligible_catalog_purchase(p.modules[0], p) is None
    p = _plan()
    p.modules.pop(0)
    assert eligible_catalog_purchase(p.modules[0], p) is None


def test_catalog_is_reusable_without_asking_the_model_again_after_checkpoint():
    p = _plan()
    model = DataOnlyModel()
    s = try_catalog_purchase(p.modules[0], p, model)
    saved = deepcopy(p.game_design["_host_declarative_catalogs"])
    next_plan = _plan()
    next_plan.game_design["_host_declarative_catalogs"] = saved
    assert try_catalog_purchase(next_plan.modules[0], next_plan, None) == s



def test_market_catalog_must_reference_real_host_ship_section_slots():
    p = _plan()
    p.game_design["_host_ship_part_catalogs"] = {
        "ShipBuilder": [{"slot": "propulsion"}, {"slot": "defense"}],
    }
    model = DataOnlyModel({"entries": [{
        "id": "badUpgrade", "label": "Bad upgrade", "cost": 10,
        "slot": "madeUpSlot", "effect": "speed", "bonus": 3,
    }]})
    with pytest.raises(ValueError, match="HOST_DECLARATIVE_CATALOG_EXHAUSTED"):
        LuauCodeGenerator(model).generate_module_code(p.modules[0], p)
    assert len(model.calls) == 2
    assert all("propulsion" in prompt and "defense" in prompt
               for prompt, _options in model.calls)


def test_market_accepts_actual_ship_slot_and_checks_restored_cache():
    p = _plan()
    p.game_design["_host_ship_part_catalogs"] = {"Builder": [
        {"slot": "weapon"}, {"slot": "shield"},
    ]}
    router = DataOnlyModel()
    source = LuauCodeGenerator(router).generate_module_code(p.modules[0], p)
    assert 'ship.sections[item.slot]' in source
    assert 'coins.Value -= item.cost' in source
    p.game_design["_host_ship_part_catalogs"]["Builder"][0]["slot"] = "newSlot"
    with pytest.raises(ValueError, match="Cached purchase catalog references missing ship section"):
        LuauCodeGenerator(router).generate_module_code(p.modules[0], p)
