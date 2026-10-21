"""Follow-on ZIP17: level-capped ship upgrades only target real installed slots."""
from copy import deepcopy
import pytest
from test_host_ship_slot_configuration import plan, DataOnly
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_slot_levels import eligible_ship_slot_levels, try_ship_slot_levels, _validate
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxService, ModuleKind


class TwoDatasets(DataOnly):
    def complete_json(self,prompt,**kw):
        if "maxLevel" in prompt:
            self.calls.append((prompt,kw))
            return {"upgrades":[
                {"slot":"HullSlot","maxLevel":4,"baseCost":25,"bonusPerLevel":10},
                {"slot":"EngineSlot","maxLevel":3,"baseCost":40,"bonusPerLevel":15},
            ]}
        return super().complete_json(prompt,**kw)


def plan_with_upgrade():
    p,builder,builder_client=plan()
    description=(
        "The server owns the ship upgrade and expansion state. When a "
        "player requests an upgrade or expansion, the server validates "
        "that the player owns the target ship, has sufficient earned game "
        "currency, and has not already reached the maximum level for that "
        "ship part. The server applies the upgrade, deducts the required "
        "earned game currency, and persists the resulting ship configuration. "
        "The server rejects any request that fails validation, including "
        "requests from players who are not the owner of the target ship and "
        "requests that would exceed the maximum level for a ship part."
    )
    owner=RobloxModuleSpec(
        module_id="dyn_0af01c0dc8ff",name="ShipUpgradeAndExpansionF063101Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ShipUpgradeAndExpansionF063101Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,description=description)
    client=RobloxModuleSpec(
        module_id="dyn_73d996bb9615",name="ShipUpgradeAndExpansionF063101Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ShipUpgradeAndExpansionF063101Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="The client shows purchased levels, prices and server responses.")
    p.modules.extend([owner,client])
    d=p.game_design["dynamic_design"]
    key="ShipUpgradeAndExpansionF063101Action"
    d["host_actions"][key]={"service":owner.name,"kind":"RemoteFunction"}
    d["remotes"][key]="RemoteFunction"
    d["module_remotes"][owner.module_id]=[key]
    d["module_remotes"][client.module_id]=[key]
    return p,builder,owner,client


def test_actual_followup_upgrades_use_canonical_ship_slots_and_short_data_only():
    p,builder,owner,client=plan_with_upgrade()
    assert eligible_ship_slot_levels(owner,p)
    assert eligible_ship_slot_levels(client,p)
    scope={m["name"]:m["strategy"] for m in generation_scope(p)["modules"]}
    assert scope[owner.name]=="host_declarative_ship_slot_levels"
    assert scope[client.name]=="host_declarative_ship_slot_levels"
    router=TwoDatasets()
    coder=LuauCodeGenerator(router)
    builder_code=coder.generate_with_self_correction(builder,p)
    server=coder.generate_with_self_correction(owner,p)
    ui=coder.generate_with_self_correction(client,p)
    assert len(router.calls)==2
    assert 'Use ONLY existing host-built slots: ["EngineSlot", "HullSlot"]' in router.calls[1][0]
    assert server==try_ship_slot_levels(owner,p,None)
    assert ui==try_ship_slot_levels(client,p,None)
    assert '["HullSlot"]={max=4,base=25,bonus=10}' in server
    assert 'manager.GetState(player,"RMMShipSections")' in server
    assert 'manager.GetState(player,"RMMShipSectionUpgradeLevels")' in server
    assert 'installed.owned~=true' in server
    assert 'if current>=rule.max then return reject("maximum_level") end' in server
    assert 'coins.Value-=charge' in server
    assert 'levels[slot]={level=nextLevel,typeId=installed.typeId}' in server
    assert 'remote:InvokeServer(entry.slot)' in ui
    assert 'GetState(player, "RMMShipSections")' not in server
    for module,text in ((builder,builder_code),(owner,server),(client,ui)):
        errors=[d for d in LuauStaticAnalyzer().analyze_source(text,module.file_path)
                if d.severity=="ERROR"]
        assert not errors,[(module.name,d.rule,d.message) for d in errors]


def test_undisclosed_part_and_tampered_price_cannot_enter_upgrade_catalog():
    actual={"HullSlot","EngineSlot"}
    with pytest.raises(ValueError):
        _validate({"upgrades":[{"slot":"NotOwnedCatalogSlot","maxLevel":2,
            "baseCost":1,"bonusPerLevel":20}]},actual)
    for bad in (True,-1,0,100001):
        with pytest.raises(ValueError):
            _validate({"upgrades":[{"slot":"HullSlot","maxLevel":2,
                "baseCost":bad,"bonusPerLevel":20}]},actual)


def test_server_does_not_claim_upgrades_without_real_builder_or_remote():
    p,builder,owner,client=plan_with_upgrade()
    p.modules.remove(builder)
    assert eligible_ship_slot_levels(owner,p) is None
    p,builder,owner,client=plan_with_upgrade()
    p.game_design["dynamic_design"]["remotes"]["ShipUpgradeAndExpansionF063101Action"]="RemoteEvent"
    assert eligible_ship_slot_levels(owner,p) is None


def test_cached_level_catalog_must_match_exact_host_built_slot_ids():
    p,builder,owner,client=plan_with_upgrade()
    router=TwoDatasets()
    coder=LuauCodeGenerator(router)
    assert coder.generate_with_self_correction(builder,p)
    assert coder.generate_with_self_correction(owner,p)
    assert coder.generate_with_self_correction(client,p)
    assert len(router.calls)==2
    p.game_design["_host_ship_level_upgrades"][owner.name][0]["slot"]="Forged"
    with pytest.raises(ValueError):
        try_ship_slot_levels(owner,p,None)
