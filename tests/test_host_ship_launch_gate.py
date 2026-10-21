"""Real ZIP17 follow-on launch only after server-confirmed currency and ship levels."""
from copy import deepcopy
import pytest
from test_host_ship_slot_levels import plan_with_upgrade, TwoDatasets
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_launch_gate import eligible_ship_launch_gate, try_ship_launch_gate, _validate
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxService, ModuleKind


class ThreeDatasets(TwoDatasets):
    def complete_json(self,prompt,**kw):
        if "currencyThreshold" in prompt:
            self.calls.append((prompt,kw))
            return {"currencyThreshold":175,"requiredUpgrades":[
                {"slot":"HullSlot","minLevel":2},
                {"slot":"EngineSlot","minLevel":3},
            ]}
        return super().complete_json(prompt,**kw)


def plan_with_gate():
    p,builder,upgrade,upgrade_ui=plan_with_upgrade()
    desc=(
        "The server tracks the player's accumulated game currency and spaceship "
        "upgrade state. When the player reaches the required currency threshold "
        "and the spaceship has completed the required upgrades, the server marks "
        "the player as launch-eligible. When the player reaches the launch gate, "
        "the server validates the player's launch eligibility, grants the "
        "player the space mode state, and records the transition in the "
        "player's saved data."
    )
    server=RobloxModuleSpec(
        module_id="dyn_517b2bfc22da",name="SpaceLaunchGate9368211Server",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/SpaceLaunchGate9368211Server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,description=desc)
    client=RobloxModuleSpec(
        module_id="dyn_c3a04ac7a8a2",name="SpaceLaunchGate9368211Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/SpaceLaunchGate9368211Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Shows server-confirmed launch and required currency.")
    p.modules.extend([server,client])
    dynamic=p.game_design["dynamic_design"]
    remote="SpaceLaunchGate9368211Action"
    dynamic["host_actions"][remote]={"service":server.name,"kind":"RemoteFunction"}
    dynamic["remotes"][remote]="RemoteFunction"
    dynamic["module_remotes"][server.module_id]=[remote]
    dynamic["module_remotes"][client.module_id]=[remote]
    return p,builder,upgrade,server,client


def test_launch_gate_matches_authored_progression_and_verified_rocket_parts():
    p,builder,upgrade,server,client=plan_with_gate()
    assert eligible_ship_launch_gate(server,p)
    assert eligible_ship_launch_gate(client,p)
    scopes={m["name"]:m["strategy"] for m in generation_scope(p)["modules"]}
    assert scopes[server.name]=="host_declarative_ship_launch_gate"
    assert scopes[client.name]=="host_declarative_ship_launch_gate"
    router=ThreeDatasets()
    generator=LuauCodeGenerator(router)
    built=generator.generate_with_self_correction(builder,p)
    upgraded=generator.generate_with_self_correction(upgrade,p)
    launch=generator.generate_with_self_correction(server,p)
    ui=generator.generate_with_self_correction(client,p)
    assert len(router.calls)==3
    assert 'local CURRENCY_THRESHOLD=175' in launch
    assert 'local REQUIRED={{slot="HullSlot",level=2}, {slot="EngineSlot",level=3}}' in launch
    assert 'manager.GetState(player,"RMMShipSections")' in launch
    assert 'manager.GetState(player,"RMMShipSectionUpgradeLevels")' in launch
    assert 'manager.GetState(player,"RMMTravelProgress")' in launch
    assert 'coins.Value>=CURRENCY_THRESHOLD and upgradesReady' in launch
    assert 'owned.typeId~=installed.typeId' in launch
    assert 'if (gate.Position-root.Position).Magnitude>22' in launch
    assert 'travel.inSpace=true' in launch
    assert 'mode.activeMode="Space Mode"' in launch
    assert 'character:PivotTo(CFrame.new(orbit.Position+' in launch
    assert 'remote:InvokeServer("launch")' in ui
    assert 'remote:InvokeServer("status")' in ui
    for module,code in ((builder,built),(upgrade,upgraded),(server,launch),(client,ui)):
        errors=[d for d in LuauStaticAnalyzer().analyze_source(code,module.file_path)
                if d.severity=="ERROR"]
        assert not errors,[(module.name,d.rule,d.message) for d in errors]


def test_invalid_launch_level_and_threshold_cannot_bypass_plan():
    caps={"HullSlot":4,"EngineSlot":3}
    for invalid in (
        {"currencyThreshold":0,"requiredUpgrades":[{"slot":"HullSlot","minLevel":2}]},
        {"currencyThreshold":175,"requiredUpgrades":[{"slot":"HullSlot","minLevel":9}]},
        {"currencyThreshold":175,"requiredUpgrades":[{"slot":"Unverified","minLevel":1}]},
        {"currencyThreshold":175,"requiredUpgrades":[]},
        {"currencyThreshold":175,"requiredUpgrades":[
            {"slot":"HullSlot","minLevel":2},{"slot":"HullSlot","minLevel":3}]},
    ):
        with pytest.raises(ValueError):
            _validate(invalid,caps)


def test_launch_does_not_select_without_real_approved_upgrades():
    p,builder,upgrade,server,client=plan_with_gate()
    p.modules.remove(upgrade)
    assert eligible_ship_launch_gate(server,p) is None
    p,builder,upgrade,server,client=plan_with_gate()
    p.game_design["dynamic_design"]["remotes"]["SpaceLaunchGate9368211Action"]="RemoteEvent"
    assert eligible_ship_launch_gate(server,p) is None


def test_launch_resume_rule_cannot_use_unverified_level():
    p,builder,upgrade,server,client=plan_with_gate()
    router=ThreeDatasets()
    gen=LuauCodeGenerator(router)
    assert gen.generate_with_self_correction(builder,p)
    assert gen.generate_with_self_correction(upgrade,p)
    assert gen.generate_with_self_correction(server,p)
    assert try_ship_launch_gate(client,p,None)
    assert len(router.calls)==3
    p.game_design["_host_ship_launch_rules"][server.name]["requiredUpgrades"][0]["minLevel"]=100
    with pytest.raises(ValueError):
        try_ship_launch_gate(server,p,None)



def test_launch_refuses_upgrades_not_in_independent_real_ship_catalog():
    p,builder,upgrade,server,client=plan_with_gate()
    router=ThreeDatasets()
    gen=LuauCodeGenerator(router)
    assert gen.generate_with_self_correction(builder,p)
    assert gen.generate_with_self_correction(upgrade,p)
    p.game_design["_host_ship_level_upgrades"][upgrade.name][0]["slot"]="InventedLaunchPart"
    with pytest.raises(ValueError,match="SHIP_LEVEL_UPGRADE_INVALID"):
        try_ship_launch_gate(server,p,None)
