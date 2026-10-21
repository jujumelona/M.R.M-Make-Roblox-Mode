"""Real planned upgrade after capped construction cannot use fictional ownership."""
from copy import deepcopy
import pytest
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_capped_ship_parts import try_capped_ship_parts
from roblox_mod_ai.host_ship_owned_upgrades import (
    eligible_ship_owned_upgrades, try_ship_owned_upgrades, _validate,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class DataOnly:
    def __init__(self):
        self.calls=[]
    def complete(self,*a,**k):
        raise AssertionError("Never generate unrestricted purchase Luau")
    def complete_json(self,prompt,**kwargs):
        self.calls.append((prompt,kwargs))
        if "maxParts:integer" in prompt:
            return {"maxParts":2,"parts":[
                {"id":"Hull","label":"Hull","cost":6},
                {"id":"WeaponRack","label":"Weapon rack","cost":10},
                {"id":"CrewDeck","label":"Crew deck","cost":8}]}
        return {"upgrades":[
            {"id":"BetterHull","label":"Hull reinforcement","targetPart":"Hull",
             "effect":"hull","cost":15,"bonus":12},
            {"id":"ExtraCrew","label":"Crew support","targetPart":"CrewDeck",
             "effect":"crew","cost":20,"bonus":2},
            {"id":"AimAssist","label":"Weapon optics","targetPart":"WeaponRack",
             "effect":"weapon","cost":12,"bonus":4},
        ]}


def make_plan():
    def mod(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_"+name,name=name,kind=kind,
            file_path=("src/server/"+name+".luau" if kind==ModuleKind.SERVER_MODULE
                       else "src/client/"+name+".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE if kind==ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    ship=mod("GeneralShipPartsServer",ModuleKind.SERVER_MODULE,
        "The server validates construction by modular part types. Players buy "
        "parts using earned currency, deducts currency after validating ownership, and attaches each part to their spaceship assembly "
        "and reject any attempt to exceed the part cap or use invalid part IDs.")
    ship_ui=mod("GeneralShipPartsClient",ModuleKind.CLIENT_SCRIPT,
        "Client lets players select and buy modular parts.")
    upgrade=mod("GeneralOwnedShipUpgradeServer",ModuleKind.SERVER_MODULE,
        "The server owns all upgrade state and validates every purchase: it "
        "checks that the player has sufficient earned game currency, applies "
        "the selected upgrade to the ship's weapon, crew or hull performance, "
        "deducts the cost from the player's currency, and persists the "
        "resulting upgrade state through DataStore. Invalid purchases are rejected.")
    client=mod("GeneralOwnedShipUpgradeClient",ModuleKind.CLIENT_SCRIPT,
        "Client displays upgrade options, currency and a server-confirmed result.")
    design={
        "host_actions":{
            "BuildAction":{"service":ship.name,"kind":"RemoteFunction"},
            "UpgradeAction":{"service":upgrade.name,"kind":"RemoteFunction"},
        },
        "remotes":{"BuildAction":"RemoteFunction","UpgradeAction":"RemoteFunction"},
        "module_remotes":{
            ship.module_id:["BuildAction"],ship_ui.module_id:["BuildAction"],
            upgrade.module_id:["UpgradeAction"],client.module_id:["UpgradeAction"],
        },
    }
    p=RobloxProposal(
        requested_prompt="A modular vehicle economy",game_title="Any vehicle world",
        description="Build a modular ship and upgrade installed equipment",
        modules=[ship,ship_ui,upgrade,client],
        game_design={"dynamic_design":design},
    )
    return p,ship,ship_ui,upgrade,client


def test_next_real_ship_upgrade_contract_uses_host_and_real_installed_part_ids():
    p,ship,ship_ui,upgrade,client=make_plan()
    assert eligible_ship_owned_upgrades(upgrade,p)
    assert eligible_ship_owned_upgrades(client,p)
    scope=generation_scope(p)
    assert scope["counts"]["host_declarative_ship_upgrades"]==2
    coder=LuauCodeGenerator(DataOnly())
    for m in [ship,ship_ui,upgrade,client]:
        result=coder.generate_with_self_correction(m,p)
        assert result
        if m==upgrade:
            assert '["BetterHull"] = {part = "Hull", effect = "hull"' in result
            assert 'GetState(player, "RMMShipSections")' in result
            assert 'GetState(player, "RMMUpgradePurchases")' in result
            assert 'parts.sections[item.part]' in result
            assert 'installed.owned ~= true' in result
            assert 'coins.Value -= item.cost' in result
            assert 'purchases[id] = {owned = true, targetPart = item.part' in result
            assert 'player:SetAttribute("RMMShipUpgradeScore"' in result
            assert 'type(saved) == "table" and saved.owned == true' in result
            assert ':GetState' not in result
        if m==client:
            assert 'remote:InvokeServer(upgrade.id)' in result
            assert 'WaitForChild("UpgradeAction", 20)' in result
        errors=[d for d in LuauStaticAnalyzer().analyze_source(result,m.file_path)
                if d.severity=="ERROR"]
        assert not errors,[(m.name,d.rule,d.line_number,d.message) for d in errors]


def test_upgrade_catalog_must_reference_real_prior_builder_catalog():
    p,ship,ship_ui,upgrade,client=make_plan()
    with pytest.raises(ValueError, match="MISSING_PART_CATALOG"):
        try_ship_owned_upgrades(upgrade,p,DataOnly())
    router=DataOnly()
    assert try_capped_ship_parts(ship,p,router)
    assert try_ship_owned_upgrades(upgrade,p,router)
    assert len(router.calls)==2
    assert '"CrewDeck"' in router.calls[1][0]
    assert '"Hull"' in router.calls[1][0]
    assert try_ship_owned_upgrades(client,p,None)
    assert len(router.calls)==2
    p.game_design["_host_ship_owned_upgrades"][upgrade.name][0]["targetPart"]="PretendShip"
    with pytest.raises(ValueError,match="real available part"):
        try_ship_owned_upgrades(upgrade,p,None)


@pytest.mark.parametrize("data", [
    {"upgrades":[]},
    {"upgrades":[{"id":"Buy","label":"Buy","targetPart":"Absent",
                  "effect":"weapon","cost":1,"bonus":1}]},
    {"upgrades":[{"id":"Buy","label":"Buy","targetPart":"Hull",
                  "effect":"weapon","cost":0,"bonus":1}]},
    {"upgrades":[{"id":"Buy","label":"Buy","targetPart":"Hull",
                  "effect":"weapon","cost":1,"bonus":False}]},
    {"upgrades":[{"id":"Buy","label":"Buy","targetPart":"Hull",
                  "effect":"hack","cost":1,"bonus":1}]},
])
def test_bad_upgrade_data_refused(data):
    with pytest.raises(ValueError):
        _validate(data, {"Hull"})


def test_market_only_upgrade_without_build_contract_not_replaced():
    p,ship,ship_ui,upgrade,client=make_plan()
    p.modules.remove(ship)
    assert eligible_ship_owned_upgrades(upgrade,p) is None
    p,ship,ship_ui,upgrade,client=make_plan()
    upgrade.description="Sell ore to broker for credits."
    assert eligible_ship_owned_upgrades(upgrade,p) is None
