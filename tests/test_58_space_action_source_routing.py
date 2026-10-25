"""58: typed combat/colony exhaustion because independent HarvestSpecialMinerals
does not have the literal ExtractOtherPlanetMineral prefix.

The source-bound owner, player action ABI, one physical planet target and real
launched spacecraft must be validated before choosing deterministic host Luau.
"""
from copy import deepcopy
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_space_actions import render_host_space_action
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec
from tests.test_report41_host_space_actions import fixture


PROMPT=("우주모드 자원파밍 돈모으기 거래 우주선 조립과 우주 출항 "
        "다른행성 특수 광물 외계인과 싸움 식민지화")


def _report58():
    p=fixture()
    p.requested_prompt=PROMPT
    # Report58 uses host-mining HarvestSpecialMinerals with a zero-argument
    # Remote; requiring ExtractOtherPlanetMineral misroutes BOTH remaining
    # server actions to the bounded small-model coder.
    p.modules=[m for m in p.modules
               if not m.name.startswith("ExtractOtherPlanetMineral")]
    d=p.game_design["dynamic_design"]
    old="PlayerOwnedPlanet77D3DB21"
    new="TargetPlanet77D3DB21"
    for row in d["world_objects"]:
        if row["name"]==old:
            row["name"]=new
    for key,values in d["module_world_objects"].items():
        d["module_world_objects"][key]=[new if v==old else v for v in values]
    combat=next(m for m in p.modules if m.name.startswith("AlienCombat")
                and m.kind==ModuleKind.SERVER_MODULE)
    colony=next(m for m in p.modules if m.name.startswith("MarkPlanetColonized")
                and m.kind==ModuleKind.SERVER_MODULE)
    combat.description=("Validate that the player is on the alien planet "
        "and has a valid combat target; on approval, server-owned state "
        "mutation sets the player's combat state to attacking and marks "
        "the target as engaged.")
    colony.description=("Validate that the request is a signed, in-world action "
        "from the player's own character targeting a planet entity, then "
        "server-authoritatively set the planet's Colonized property to true "
        "and record the colonizing player's name and timestamp.")
    # Keep a differently-named mineral producer; it has its own host mining
    # contract and does not need to be forged as an Extract service.
    p.modules.append(RobloxModuleSpec(
        module_id="dyn_report58_harvest",name="HarvestSpecialMinerals77D3DB3Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/HarvestSpecialMinerals77D3DB3Server.luau",
        roblox_service="ServerScriptService",
        description="Harvest server-owned special minerals from resource nodes"
    ))
    return p,combat,colony


def test_58_combat_and_colony_use_verified_host_not_small_model():
    p,combat,colony=_report58()
    for server in (combat,colony):
        code=render_host_space_action(server,p)
        assert code is not None,server.name
        assert "function Service.handleAction" in code
        assert 'services.PlayerDataManager.GetState(player,"RMMPlanetProgress")' in code
        assert 'RMMOrbitArrival_7c3d1fecc9' in code
        assert "placePlanetActionTarget()" in code
        assert "return {success=true" in code
        assert LuauCodeGenerator().generate_module_code(server,p)==code
    client=next(m for m in p.modules if m.name=="MarkPlanetColonized77D3DB2Client")
    ui=render_host_space_action(client,p)
    assert ui and 'selection="planet"' in ui and "TextBox" not in ui
    s={row["name"]:row["strategy"] for row in generation_scope(p)["modules"]}
    assert s[combat.name]=="host_space_action"
    assert s[colony.name]=="host_space_action"
    assert s[client.name]=="host_space_action"


def test_58_fails_closed_without_world_target_binding():
    p,combat,colony=_report58()
    d=p.game_design["dynamic_design"]
    d["module_world_objects"][colony.module_id].remove("TargetPlanet77D3DB21")
    assert render_host_space_action(colony,p) is None
    assert render_host_space_action(combat,p) is not None


def test_58_fails_closed_without_launcher_or_arrival():
    p,combat,colony=_report58()
    p.game_design["dynamic_design"]["host_arrival_materializations"].clear()
    assert render_host_space_action(colony,p) is None
    assert render_host_space_action(combat,p) is None


def test_58_fails_closed_without_actual_colonization_user_request():
    p,combat,colony=_report58()
    p.requested_prompt="우주 우주선만 제작하는 게임"
    assert render_host_space_action(colony,p) is None
    assert render_host_space_action(combat,p) is not None


def test_58_fails_closed_without_typed_remote_contract():
    p,combat,colony=_report58()
    remote="MarkPlanetColonized77D3DB2Action"
    p.game_design["dynamic_design"]["host_typed_actions"][remote]["contract"]["inputs"][0]["id"]="amount"
    assert render_host_space_action(colony,p) is None
