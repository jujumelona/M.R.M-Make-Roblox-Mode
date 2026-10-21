"""ZIP17 regression: server-owned no-price ship slot creation/configuration/removal."""
from copy import deepcopy
import pytest
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_slot_configuration import (
    eligible_ship_slot_configuration, try_ship_slot_configuration, _validate,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, RobloxService, ModuleKind


class DataOnly:
    def __init__(self):
        self.calls = []
        self.data = {"slots": [
            {"id": "HullSlot", "label": "Hull", "types": [
                {"id": "BasicHull", "label": "Hull type", "configurations": [
                    {"id": "Light", "performance": 10},
                    {"id": "Armor", "performance": 20},
                ]}]},
            {"id": "EngineSlot", "label": "Engine", "types": [
                {"id": "Engine", "label": "Engine type", "configurations": [
                    {"id": "Standard", "performance": 30},
                ]}]},
        ]}
    def complete(self, *args, **kwargs):
        raise AssertionError("The small model must not author Luau code")
    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return deepcopy(self.data)


def plan(server_name="ModularShipSectionBuilderB327A61Server"):
    desc = (
        "The server owns the ship assembly and validates every section creation, "
        "configuration, and removal. A player may add a ship section only when "
        "the player owns the ship, the ship has an available section slot, "
        "and the requested section type is a valid ship section. The server "
        "creates the section as a server-owned part, assigns it a stable "
        "section slot, applies the requested configuration, and persists the "
        "ship's section list. The server rejects duplicate section types in "
        "the same slot, invalid section types, and any section configuration "
        "outside the allowed set. The server removes a section only when the "
        "player owns the ship and the section is present in the ship's section "
        "list. The server never allows a client to create, configure, or "
        "remove a section directly."
    )
    client_name = server_name.removesuffix("Server") + "Client"
    server = RobloxModuleSpec(
        module_id="dyn_4e07ec75bdb3", name=server_name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/" + server_name + ".luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=desc,
    )
    client = RobloxModuleSpec(
        module_id="dyn_c90bce0c4cd8", name=client_name,
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/" + client_name + ".client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description=("Client shows ship's current section layout, lets player "
                     "select a section type and configuration; never edits ship."),
    )
    route = server_name.removesuffix("Server") + "Action"
    p = RobloxProposal(
        requested_prompt="Build a vehicle whose slots can have configurable parts",
        game_title="Ship Slot Builder",
        description="Modular ship",
        modules=[server, client],
        game_design={"dynamic_design": {
            "host_actions": {route: {"service": server_name, "kind": "RemoteFunction"}},
            "remotes": {route: "RemoteFunction"},
            "module_remotes": {server.module_id: [route], client.module_id: [route]},
            "module_world_objects": {server.module_id: [], client.module_id: []},
            "world_objects": [],
        }},
    )
    return p, server, client


def test_real_failed_scoped_luau_now_host_owned_and_complete():
    p, server, client = plan()
    assert eligible_ship_slot_configuration(server,p) is not None
    assert eligible_ship_slot_configuration(client,p) is not None
    scope = {x["name"]: x["strategy"] for x in generation_scope(p)["modules"]}
    assert scope[server.name] == "host_declarative_ship_slot_configuration"
    assert scope[client.name] == "host_declarative_ship_slot_configuration"
    router = DataOnly()
    generator = LuauCodeGenerator(router)
    server_code = generator.generate_with_self_correction(server,p)
    client_code = generator.generate_with_self_correction(client,p)
    assert len(router.calls) == 1
    assert router.calls[0][1]["max_tokens"] <= 1350
    assert server_code == try_ship_slot_configuration(server,p)
    assert client_code == try_ship_slot_configuration(client,p)
    for snippet in (
        '["HullSlot"]={order=1,types={',
        '["BasicHull"]={configs={["Light"]=10,["Armor"]=20}}',
        'manager.GetState(player,"RMMShipSections")',
        'sections[slotId]=nextSections[slotId]',
        'part:SetAttribute("ShipSectionType",saved.typeId)',
        'part:SetAttribute("ShipSectionConfiguration",saved.configuration)',
        'return reject("slot_occupied")',
        'return reject("invalid_selection")',
        'return reject("wrong_section")',
        'if action=="remove" then',
        'local after=inspect(nextSections)',
        'player:SetAttribute("RMMShipPerformance",summary.performance)',
    ):
        assert snippet in server_code, snippet
    assert 'remote:InvokeServer(action,slotId,typeId,configId)' in client_code
    assert 'for _,action in {"create","configure","remove"} do' in client_code
    assert "PlayerDataManager:GetState" not in server_code
    assert 'services:GetService("ShipSectionSlots")' not in server_code
    assert "coins.Value" not in server_code
    assert "inventory.resources" not in server_code
    for module,code in ((server,server_code),(client,client_code)):
        failures=[d for d in LuauStaticAnalyzer().analyze_source(code,module.file_path)
                  if d.severity=="ERROR"]
        assert not failures, [(d.rule,d.line_number,d.message) for d in failures]


def test_generic_names_and_independent_prompt_match_contract():
    p,server,client=plan("IndependentCraftingSectionsServer")
    assert eligible_ship_slot_configuration(server,p)
    assert eligible_ship_slot_configuration(client,p)
    assert try_ship_slot_configuration(server,p,DataOnly())
    server.description="Server shows decorative ship cosmetics and UI"
    assert eligible_ship_slot_configuration(server,p) is None


def test_costed_graph_and_unowned_transport_not_hijacked():
    p,server,client=plan()
    server.description += " Player must pay 50 coins to create every section."
    assert eligible_ship_slot_configuration(server,p) is None
    p,server,client=plan()
    server.description += " Each section needs a parent section."
    assert eligible_ship_slot_configuration(server,p) is None
    p,server,client=plan()
    route=next(iter(p.game_design["dynamic_design"]["host_actions"]))
    p.game_design["dynamic_design"]["host_actions"][route]["kind"]="RemoteEvent"
    assert eligible_ship_slot_configuration(server,p) is None
    p,server,client=plan()
    p.game_design["dynamic_design"]["module_remotes"][client.module_id]=["Other"]
    assert eligible_ship_slot_configuration(client,p) is None
    p,server,client=plan()
    p.modules.remove(server)
    assert eligible_ship_slot_configuration(client,p) is None


@pytest.mark.parametrize("bad",[
    {"slots":[]},
    {"slots":[{"id":"Hull","label":"Hull","types":[]}]},
    {"slots":[{"id":"Hull","label":"Hull","types":[{"id":"Part","label":"P",
               "configurations":[{"id":"Strong","performance":True}]}]}]},
    {"slots":[{"id":"Hull","label":"Hull","types":[{"id":"Part","label":"P",
               "configurations":[{"id":"Strong","performance":-1}]}]}]},
    {"slots":[{"id":"Hull","label":"Hull","types":[{"id":"Part","label":"P",
               "configurations":[{"id":"Strong","performance":1},
                                 {"id":"strong","performance":2}]}]}]},
    {"slots":[{"id":"Hull","label":"Hull","types":[{"id":"Part","label":"P",
               "configurations":[{"id":"Strong","performance":1}]}]},
              {"id":"hull","label":"Duplicate","types":[{"id":"Other","label":"O",
               "configurations":[{"id":"Strong","performance":1}]}]}]},
])
def test_reject_invalid_or_injectable_slot_catalog(bad):
    with pytest.raises(ValueError):
        _validate(bad)


def test_validated_catalog_resume_without_new_model_call():
    p,server,client=plan()
    router=DataOnly()
    assert try_ship_slot_configuration(server,p,router)
    assert try_ship_slot_configuration(client,p,None)
    assert len(router.calls)==1
    p.game_design["_host_ship_slot_config"][server.name][0]["types"][0]["configurations"][0]["id"]="x; end"
    with pytest.raises(ValueError):
        try_ship_slot_configuration(server,p,None)
