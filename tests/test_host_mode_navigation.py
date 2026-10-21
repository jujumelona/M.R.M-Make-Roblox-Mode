"""ZIP18: mode UI model emitted HTML, fake action IDs, and server spent coins.

Server and client must share the same real action protocol rather than
independent model-invented Luau. This is a generic mode-navigation contract.
"""
from copy import deepcopy
import pytest
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_mode_navigation import (
    eligible_mode_navigation, try_mode_navigation, _validate,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class PlanetData:
    def __init__(self):
        self.calls=[]
        self.data={"planets":[
            {"id":"Initial","label":"Home"},
            {"id":"MineralPlanet","label":"Mineral planet"},
            {"id":"Frontier","label":"Unexplored frontier"},
        ]}
    def complete(self,*a,**k):
        raise AssertionError("Model may not author mode/planet actions or UI Luau")
    def complete_json(self,prompt,**kwargs):
        self.calls.append((prompt,kwargs))
        return deepcopy(self.data)


def plan(server_name="SpaceModeSetupF5E8F01Server"):
    client_name=server_name.removesuffix("Server")+"Client"
    server=RobloxModuleSpec(
        module_id="dyn_e60e61eddd7a",name=server_name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/"+server_name+".luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server owns the dedicated space-mode state: it validates "
                     "that the player is in the space mode before accepting any "
                     "space-mode action, and it owns the mode transition, planet "
                     "selection, and the special mineral, enemy, and colony "
                     "progression rules."),
    )
    client=RobloxModuleSpec(
        module_id="dyn_6e5885c1d145",name=client_name,
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/"+client_name+".client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=("The client only receives the server's mode state and "
                     "renders the space-mode UI, planet selection, and progression feedback."),
    )
    remote=server_name.removesuffix("Server")+"Action"
    proposal=RobloxProposal(
        requested_prompt="Planet exploration with gated mode access",
        game_title="Any Mode Exploration Game",description="Mode and planet navigation",
        modules=[server,client],game_design={"dynamic_design":{
            "host_actions":{remote:{"service":server.name,"kind":"RemoteFunction"}},
            "remotes":{remote:"RemoteFunction"},
            "module_remotes":{server.module_id:[remote],client.module_id:[remote]},
            "host_client_actions":{},"host_action_choices":{},
        }},
    )
    return proposal,server,client,remote


def test_exact_failure_is_host_bounded_data_not_scoped_client_luau():
    p,server,client,remote=plan()
    assert eligible_mode_navigation(server,p)==(server.name,remote,"Space Mode")
    assert eligible_mode_navigation(client,p)==(server.name,remote,"Space Mode")
    scope={r["name"]:r["strategy"] for r in generation_scope(p)["modules"]}
    assert scope[server.name]=="host_declarative_mode_navigation"
    assert scope[client.name]=="host_declarative_mode_navigation"
    router=PlanetData()
    generator=LuauCodeGenerator(router)
    src=generator.generate_with_self_correction(server,p)
    ui=generator.generate_with_self_correction(client,p)
    assert len(router.calls)==1
    assert router.calls[0][1]["max_tokens"]<=550
    assert "No Lua code" in router.calls[0][0]
    assert src==try_mode_navigation(server,p,None)
    assert ui==try_mode_navigation(client,p,None)
    for token in (
        'local MODE="Space Mode"', 'manager.GetState(player,"RMMGameMode")',
        'manager.GetState(player,"RMMTravelProgress")',
        'manager.GetState(player,"RMMPlanetSelection")',
        'if travel.inSpace~=true or mode.activeMode~=MODE then',
        'return deny("launch_required")',
        'if action~="select" or type(planetId)~="string"',
        'selection.planetId=planetId',
        'root.Name="RMMSelectablePlanets"',
        'part:SetAttribute("RMMPlanetId",id)',
        'return {success=true,action="select",planet=planetId,',
    ):
        assert token in src,token
    assert 'remote:InvokeServer(action,id)' in ui
    assert 'remote:InvokeServer(action)' in ui
    assert 'request("select",planet.id)' in ui
    assert 'request("status",nil)' in ui
    for forbidden in ('SelectPlanetAction','AdvanceColonyAction','specialMineral',
                      'state.resources = state.resources - 100','coins = coins - 50',
                      '<textbutton>','services:GetService','player.leaderstats.Coins.Value = coins'):
        assert forbidden not in src
        assert forbidden not in ui
    for mod,code in ((server,src),(client,ui)):
        errors=[d for d in LuauStaticAnalyzer().analyze_source(code,mod.file_path)
                if d.severity=="ERROR"]
        assert not errors, [(d.rule,d.line_number,d.message) for d in errors]


def test_other_mode_names_work_without_original_plan_title():
    p,server,client,_=plan("GeneralNavigationStateServer")
    assert eligible_mode_navigation(server,p)
    assert try_mode_navigation(client,p,PlanetData())
    server.description="The server draws decorative planets with no player mode state"
    assert eligible_mode_navigation(server,p) is None


def test_nonmatching_clients_and_actions_do_not_become_fake_mode_controls():
    p,server,client,remote=plan()
    p.game_design["dynamic_design"]["host_actions"][remote]["kind"]="RemoteEvent"
    assert eligible_mode_navigation(client,p) is None
    p,server,client,remote=plan()
    p.game_design["dynamic_design"]["host_actions"][remote]["max_args"]=1
    assert eligible_mode_navigation(server,p) is None
    p,server,client,remote=plan()
    p.game_design["dynamic_design"]["module_remotes"][client.module_id]=["MadeUpAction"]
    assert eligible_mode_navigation(client,p) is None
    p,server,client,remote=plan()
    p.modules.remove(server)
    assert eligible_mode_navigation(client,p) is None


@pytest.mark.parametrize("invalid",[
    {"planets":[]},
    {"planets":[{"id":"Only","label":"Only"}]},
    {"planets":[{"id":"Primary","label":"One"},{"id":"primary","label":"Duplicate"}]},
    {"planets":[{"id":"X;game","label":"Break"},{"id":"Other","label":"Fine"}]},
    {"planets":[{"id":"Home","label":""},{"id":"Other","label":"Fine"}]},
    {"planets":[{"id":True,"label":"Invalid"},{"id":"Other","label":"Fine"}]},
])
def test_never_emit_unvalidated_planet_ids(invalid):
    with pytest.raises(ValueError):
        _validate(invalid)


def test_cache_reuses_verified_planets_and_fails_closed_on_mutation():
    p,server,client,_=plan()
    planner=PlanetData()
    assert try_mode_navigation(server,p,planner)
    assert try_mode_navigation(client,p,None)
    assert len(planner.calls)==1
    p.game_design["_host_mode_planet_catalog"][server.name][0]["id"]="Invalid;ID"
    with pytest.raises(ValueError):
        try_mode_navigation(client,p,None)
