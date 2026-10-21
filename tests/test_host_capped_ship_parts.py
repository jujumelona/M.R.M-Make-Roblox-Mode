"""A capped modular spaceship purchase must never need a long Luau model body."""
from copy import deepcopy
import pytest
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_capped_ship_parts import (
    eligible_capped_ship_parts, _validate, try_capped_ship_parts,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, RobloxService, ModuleKind


class PartJSONOnly:
    def __init__(self, payload=None):
        self.calls=[]
        self.data=payload if payload is not None else {
            "maxParts": 2,
            "parts": [
                {"id":"Engine", "label":"Engine", "cost":15},
                {"id":"Hull", "label":"Hull", "cost":7},
                {"id":"CrewDeck", "label":"Crew deck", "cost":10},
            ],
        }
    def complete(self,*a,**kw):
        raise AssertionError("Model cannot write purchase and world assembly code")
    def complete_json(self,prompt,**kw):
        self.calls.append((prompt,kw))
        return deepcopy(self.data)


def make_plan():
    server=RobloxModuleSpec(
        module_id="dyn_ship",name="AnyModularSpaceshipServer",kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/AnyModularSpaceshipServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server owns the construction state and validates every part "
            "addition: the player selects a modular part type, the server checks "
            "the player has enough earned game currency and enough available "
            "modular parts, then adds the part to the player's spaceship assembly, "
            "updates the assembly's part count and total cost, and deducts the "
            "currency only after the part is committed. The server also validates "
            "that the current assembly is not already at its part cap and that "
            "the selected part is a valid modular part type."),
    )
    client=RobloxModuleSpec(
        module_id="dyn_ship_client",name="AnyModularSpaceshipClient",kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/AnyModularSpaceshipClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Client shows modular ship parts for purchase, count, cost and money.",
    )
    remote="AnyShipPartsAction"
    p=RobloxProposal(
        game_title="Any buildable game",description="Game with modular vehicles",
        requested_prompt="Buy and construct a spaceship with earned currency",
        modules=[server,client],
        game_design={"dynamic_design":{
            "host_actions":{remote:{"service":server.name,"kind":"RemoteFunction"}},
            "remotes":{remote:"RemoteFunction"},
            "module_remotes":{server.module_id:[remote],client.module_id:[remote]},
        }},
    )
    return p,server,client


def test_real_next_plan_contract_uses_fixed_cap_and_server_owned_ledger():
    p,server,client=make_plan()
    assert eligible_capped_ship_parts(server,p)
    assert eligible_capped_ship_parts(client,p)
    scope=generation_scope(p)
    assert scope["counts"]["host_declarative_capped_ship_parts"] == 2
    router=PartJSONOnly()
    gen=LuauCodeGenerator(router)
    source=gen.generate_with_self_correction(server,p)
    ui=gen.generate_with_self_correction(client,p)
    assert len(router.calls)==1
    assert router.calls[0][1]["max_tokens"]<=800
    assert router.calls[0][1]["json_schema"]["required"]==["maxParts","parts"]
    assert "local MAX_PARTS = 2" in source
    assert '["Engine"] = {cost = 15' in source
    assert 'GetState(player, "RMMShipSections")' in source
    assert 'coins.Value -= price' in source
    assert 'if count >= MAX_PARTS' in source
    assert 'state.sections[id] ~= nil' in source
    assert 'state.sections[id] = {owned = true, level = 1, cost = price}' in source
    assert 'player:SetAttribute("RMMShipPartCount", count)' in source
    assert 'local part = Instance.new("Part")' in source
    assert 'remote:InvokeServer(item.id)' in ui
    assert 'WaitForChild("AnyShipPartsAction", 20)' in ui
    assert 'status.Text = "Validating ship part..."' in ui
    assert "PlayerDataManager:SetState" not in source
    for m,code in ((server,source),(client,ui)):
        errors=[d for d in LuauStaticAnalyzer().analyze_source(code,m.file_path)
                if d.severity=="ERROR"]
        assert not errors,[(m.name,d.rule,d.line_number,d.message) for d in errors]


@pytest.mark.parametrize("payload",[
    {"maxParts":0,"parts":[{"id":"Hull","label":"Hull","cost":1}]},
    {"maxParts":2,"parts":[{"id":"Hull","label":"Hull","cost":1}]},
    {"maxParts":1,"parts":[{"id":"Hull","label":"Hull","cost":True}]},
    {"maxParts":1,"parts":[{"id":"Hull","label":"Hull","cost":0}]},
    {"maxParts":1,"parts":[{"id":"Hull) end","label":"Hull","cost":1}]},
    {"maxParts":1,"parts":[{"id":"Hull","label":" ","cost":1}]},
    {"maxParts":1,"parts":[{"id":"Hull","label":"A","cost":1},
                            {"id":"hull","label":"B","cost":1}]},
])
def test_invalid_unsafe_or_impossible_part_data_fails_closed(payload):
    with pytest.raises(ValueError):
        _validate(payload)


def test_not_a_zero_arg_or_resource_craft_adapter():
    p,server,client=make_plan()
    p.game_design["dynamic_design"]["host_actions"]["AnyShipPartsAction"]["max_args"]=0
    assert eligible_capped_ship_parts(server,p) is None
    p,server,client=make_plan()
    server.description="Build decorative craft sections with earned resources."
    assert eligible_capped_ship_parts(server,p) is None
    p,server,client=make_plan()
    server.description="Equip ship parts via an upgrade catalog in fixed slots."
    assert eligible_capped_ship_parts(server,p) is None


def test_cache_survives_resume_and_rejects_tampering():
    p,server,client=make_plan()
    model=PartJSONOnly()
    s=try_capped_ship_parts(server,p,model)
    assert s
    assert try_capped_ship_parts(client,p,None)
    assert len(model.calls)==1
    p.game_design["_host_capped_ship_parts"][server.name]["parts"][0]["cost"]=0
    with pytest.raises(ValueError):
        try_capped_ship_parts(server,p,None)


def test_actual_failed_workflow_module_names_not_a_special_case():
    p,server,client=make_plan()
    server.name="ModularSpaceshipPartConst2A35951Server"
    server.file_path="src/server/ModularSpaceshipPartConst2A35951Server.luau"
    client.name="ModularSpaceshipPartConst2A35951Client"
    client.file_path="src/client/ModularSpaceshipPartConst2A35951Client.client.luau"
    for route in p.game_design["dynamic_design"]["host_actions"].values():
        route["service"]=server.name
    assert eligible_capped_ship_parts(server,p)
    assert eligible_capped_ship_parts(client,p)
