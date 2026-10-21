"""General host ship assembly uses real resources and shared ownership profile."""
from copy import deepcopy
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_sections import _slots, eligible_ship_sections
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class SlotsOnly:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"slots": [
            {"id": "hull", "label": "Hull", "cost": 3},
            {"id": "weapon", "label": "Weapon", "cost": 5},
        ]}

    def complete(self, *_a, **_kw):
        raise AssertionError("Full Luau should never be generated for ship assembly")

    def complete_json(self, prompt, **kw):
        self.calls.append((prompt, kw))
        return deepcopy(self.result)


def _plan():
    server_name = "PlayerOwnedShipAssemblyServer"
    remote = "ShipSectionAction"
    server = RobloxModuleSpec(
        module_id="dyn_ship", name=server_name, kind=ModuleKind.SERVER_MODULE,
        file_path=f"src/server/{server_name}.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server maintains a per-player ship assembly as independent "
                     "section slots. Player can create, replace, remove and upgrade "
                     "ship sections. Ownership and resources must be validated "
                     "before recording a section in persistent inventory."),
    )
    client = RobloxModuleSpec(
        module_id="dyn_ship_client", name="PlayerOwnedShipAssemblyClient",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/PlayerOwnedShipAssemblyClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Client selects ship sections to create or upgrade.",
        depends_on=["mod_network_bridge"],
    )
    return RobloxProposal(
        game_title="Ship factory", description="Construct modular spacecraft",
        requested_prompt="Build and upgrade ship sections from mined resources",
        game_design={"dynamic_design": {
            "host_actions": {remote: {"service": server_name, "kind": "RemoteFunction"}},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {server.module_id: [remote], client.module_id: [remote]},
        }},
        modules=[server, client],
    )


def test_ship_sections_never_ask_model_for_full_luau_and_share_profile_contract():
    p = _plan()
    model = SlotsOnly()
    scope = generation_scope(p)
    assert scope["counts"]["host_declarative_ship_sections"] == 2
    gen = LuauCodeGenerator(model)
    s = gen.generate_module_code(p.modules[0], p)
    c = gen.generate_module_code(p.modules[1], p)
    assert len(model.calls) == 1
    assert model.calls[0][1]["json_schema"]["required"] == ["slots"]
    assert 'GetState(player, "RMMShipSections")' in s
    assert 'GetState(player, "RMMInventory")' in s
    assert 'profile.sections[slot] = {owned = newLevel > 0, level = newLevel}' in s
    assert 'inventory.resources -= cost' in s
    assert 'if command ~= "create" and not owned then return false end' in s
    assert 'root.Position).Magnitude > SHIP_DISTANCE' in s
    assert 'return remote:InvokeServer(command, slot.id)' in c
    assert 'WaitForChild("ShipSectionAction", 20)' in c
    assert 'local SLOTS = {' in s
    analyzer = LuauStaticAnalyzer()
    for module, code in zip(p.modules, (s, c)):
        errors = [x for x in analyzer.analyze_source(code, module.file_path)
                  if x.severity == "ERROR"]
        assert not errors, [(e.rule, e.message) for e in errors]


@pytest.mark.parametrize("slot", [
    {"id": "weapon", "label": "Weapon", "cost": 0},
    {"id": "weapon", "label": "Weapon", "cost": 4.5},
    {"id": "weapon", "label": "Weapon", "cost": True},
    {"id": "end(); print(1)", "label": "Weapon", "cost": 5},
    {"id": "weapon", "label": " ", "cost": 5},
])
def test_ship_data_rejects_unsafe_or_free_catalog_slots(slot):
    with pytest.raises(ValueError):
        _slots({"slots": [slot]})


def test_host_ship_sections_rejects_unsupported_and_wrong_transport():
    p = _plan()
    p.modules[0].description = "Set up a passive decorative ship model."
    assert eligible_ship_sections(p.modules[0], p) is None
    p = _plan()
    p.game_design["dynamic_design"]["host_actions"]["ShipSectionAction"]["kind"] = "RemoteEvent"
    assert eligible_ship_sections(p.modules[0], p) is None
    p = _plan()
    p.modules.pop(0)
    assert eligible_ship_sections(p.modules[0], p) is None
