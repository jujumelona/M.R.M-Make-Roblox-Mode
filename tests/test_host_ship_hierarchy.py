"""Reproduce second service after ZIP (14): parent-linked ship sections."""
from __future__ import annotations
import copy
import pytest
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_hierarchy import (
    eligible_ship_hierarchy, try_ship_hierarchy, _validate,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class RulesOnly:
    def __init__(self, response=None):
        self.calls=[]
        self.response=response or {
            "maxSections":3,
            "sections":[
                {"id":"CoreHull","label":"Hull","parent":"ROOT","cost":2,
                 "performance":35,"configurations":["compact","reinforced"]},
                {"id":"CargoDeck","label":"Cargo deck","parent":"CoreHull",
                 "cost":3,"performance":30,"configurations":["light","heavy"]},
                {"id":"Engine","label":"Engine","parent":"CoreHull","cost":4,
                 "performance":50,"configurations":["efficient","boosted"]},
            ],
        }
    def complete(self,*a,**k):
        raise AssertionError("Server code and profiles are host-owned")
    def complete_json(self,prompt,**kwargs):
        self.calls.append((prompt,kwargs))
        return copy.deepcopy(self.response)


def proposal():
    def mod(name,kind,desc):
        return RobloxModuleSpec(
            module_id="dyn_"+name,name=name,kind=kind,
            file_path=("src/server/"+name+".luau"
                       if kind==ModuleKind.SERVER_MODULE
                       else "src/client/"+name+".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind==ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    server=mod("SectionBySectionSpaceshipB327A61Server",ModuleKind.SERVER_MODULE,
        "The server owns the ship assembly and validates every construction action "
        "before applying it. A player may add a ship section only when the current "
        "ship has a valid parent section and the requested section type is one of "
        "the supported section types; the server then creates or configures the "
        "corresponding section instance, records the section in the ship's section "
        "list, and returns the resulting section state. Adding a section is rejected "
        "when the ship already has a section of the same type, when the section "
        "would exceed the ship's section limit, when the ship has no parent section, "
        "or when the requested section type is unsupported. The server also validates "
        "any section configuration change against the allowed values for that "
        "section type and rejects invalid changes without modifying the ship.")
    client=mod("SectionBySectionSpaceshipB327A61Client",ModuleKind.CLIENT_SCRIPT,
        "The client shows current sections and lets a player add or configure "
        "owned sections; it displays only server-confirmed results.")
    design={
        "host_actions":{"ShipAction":{"service":server.name,"kind":"RemoteFunction"}},
        "remotes":{"ShipAction":"RemoteFunction"},
        "module_remotes":{server.module_id:["ShipAction"],client.module_id:["ShipAction"]},
        "module_world_objects":{server.module_id:[],client.module_id:[]},
        "world_objects":[],
        "host_world_actions":{},
    }
    return (RobloxProposal(requested_prompt="Build a configurable multi-section vehicle",
        game_title="Arbitrary sectioned vehicle",
        description="Parent linked ship construction",
        game_design={"dynamic_design":design},modules=[server,client]),
        server,client)


def test_exact_followup_contract_is_bounded_data_and_host_code_only():
    p,server,client=proposal()
    assert eligible_ship_hierarchy(server,p)
    assert eligible_ship_hierarchy(client,p)
    roles={m["name"]:m["strategy"] for m in generation_scope(p)["modules"]}
    assert roles[server.name]=="host_declarative_ship_hierarchy"
    assert roles[client.name]=="host_declarative_ship_hierarchy"
    router=RulesOnly()
    coder=LuauCodeGenerator(router)
    host=coder.generate_with_self_correction(server,p)
    ui=coder.generate_with_self_correction(client,p)
    assert len(router.calls)==1
    assert router.calls[0][1]["max_tokens"] <= 1400
    assert '["Engine"] = {parent = "CoreHull", cost = 4, power = 50' in host
    assert 'default = "efficient"' in host
    assert 'GetState(player, "RMMShipSections")' in host
    assert 'GetState(player, "RMMInventory")' in host
    assert 'if before.partCount >= MAX_SECTIONS' in host
    assert 'if sections[payload] ~= nil then return reject("duplicate_section")' in host
    assert 'return reject("missing_parent_section")' in host
    assert 'return reject("invalid_configuration")' in host
    assert 'inventory.resources = resources - def.cost' in host
    assert 'sections[payload] = {owned = true, parent = def.parent' in host
    assert 'player:SetAttribute("RMMShipPerformance", status.performance)' in host
    assert 'player:SetAttribute("RMMShipAssemblyPerformance", status.performance)' in host
    assert 'part:SetAttribute("ParentSection", def.parent)' in host
    assert 'remote:InvokeServer(action, data)' in ui
    assert 'request("add", section.id)' in ui
    assert 'request("configure", {id = section.id, configuration = choice})' in ui
    assert "GetState(player, 'made_up')" not in host
    assert "PlayerDataManager:GetState" not in host
    for m,code in ((server,host),(client,ui)):
        errors=[d for d in LuauStaticAnalyzer().analyze_source(code,m.file_path)
                if d.severity=="ERROR"]
        assert not errors, [(m.name,d.rule,d.line_number,d.message) for d in errors]


def test_separate_names_same_contract_and_cache_resumption():
    p,server,client=proposal()
    server.name="IndependentVehiclePartsServer"
    server.file_path="src/server/"+server.name+".luau"
    client.name="IndependentVehiclePartsClient"
    client.file_path="src/client/"+client.name+".client.luau"
    p.game_design["dynamic_design"]["host_actions"]["ShipAction"]["service"]=server.name
    router=RulesOnly()
    assert try_ship_hierarchy(server,p,router)
    assert try_ship_hierarchy(client,p,None)
    assert len(router.calls)==1
    p.game_design["_host_ship_hierarchy"][server.name]["sections"][1]["parent"]="NoParent"
    with pytest.raises(ValueError,match="unavailable parent"):
        try_ship_hierarchy(server,p,None)


@pytest.mark.parametrize("bad", [
    {"maxSections":2,"sections":[
        {"id":"Hull","label":"Hull","parent":"Engine","cost":1,"performance":1,"configurations":["a"]},
        {"id":"Engine","label":"Engine","parent":"Hull","cost":1,"performance":1,"configurations":["a"]},
    ]},
    {"maxSections":1,"sections":[
        {"id":"Engine","label":"Engine","parent":"Missing","cost":1,"performance":1,"configurations":["a"]},
    ]},
    {"maxSections":1,"sections":[
        {"id":"Hull","label":"Hull","parent":"ROOT","cost":-1,"performance":1,"configurations":["a"]},
    ]},
    {"maxSections":1,"sections":[
        {"id":"Hull","label":"Hull","parent":"ROOT","cost":1,"performance":0,"configurations":["a"]},
    ]},
    {"maxSections":1,"sections":[
        {"id":"Hull","label":"Hull","parent":"ROOT","cost":1,"performance":1,"configurations":["a","a"]},
    ]},
])
def test_invalid_or_cyclic_ship_hierarchy_cannot_reach_source(bad):
    with pytest.raises(ValueError):
        _validate(bad)


def test_host_does_not_take_over_unrelated_ship_cosmetics_or_incompatible_remote():
    p,server,client=proposal()
    server.description="The server decorates a spacecraft hangar."
    assert eligible_ship_hierarchy(server,p) is None
    p,server,client=proposal()
    p.game_design["dynamic_design"]["host_actions"]["ShipAction"]["kind"]="RemoteEvent"
    assert eligible_ship_hierarchy(server,p) is None
    p,server,client=proposal()
    p.game_design["dynamic_design"]["module_remotes"][client.module_id]=["Wrong"]
    assert eligible_ship_hierarchy(client,p) is None
