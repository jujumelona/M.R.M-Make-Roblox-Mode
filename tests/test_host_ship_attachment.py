"""Reproduce attach-once space construction without asking a 9B model for Luau."""
from copy import deepcopy
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_ship_attachment import (
    _validated_sections, eligible_ship_attachment, try_ship_attachment,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


class SectionDataOnly:
    def __init__(self, data=None):
        self.calls = []
        self.data = data if data is not None else {"sections": [
            {"id": "Engine", "label": "Engine compartment", "cost": 5, "performance": 8},
            {"id": "Hull", "label": "Hull section", "cost": 3, "performance": 3},
        ]}

    def complete(self, *_a, **_kw):
        raise AssertionError("Do not delegate Roblox profile and assembly Luau to tiny model")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return deepcopy(self.data)


def plan(*, server_name="CustomVesselSectionBuilderServer"):
    mining = RobloxModuleSpec(
        module_id="dyn_mine", name="OreMiningServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/OreMiningServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="The server validates resource mining node distance, depletion and awards earned coins and resources.",
    )
    owner = RobloxModuleSpec(
        module_id="dyn_builder", name=server_name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/" + server_name + ".luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server owns the spaceship assembly state and validates every "
            "build action. A player may add a modular section only when the "
            "player is in a valid build context and the target section is not "
            "already present. The server records the section as attached to "
            "the spaceship, applies the section's performance contribution, "
            "and persists the assembly state. The server rejects invalid "
            "section types, duplicate sections, and actions taken outside "
            "the build context."
        ),
    )
    client = RobloxModuleSpec(
        module_id="dyn_builder_ui", name=server_name.removesuffix("Server") + "Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/" + server_name.removesuffix("Server") + "Client.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="The client selects modular ship sections and shows confirmed performance.",
    )
    remote = "BuildShipSectionAction"
    design = {
        "host_actions": {
            remote: {"service": server_name, "kind": "RemoteFunction"},
            "MineOreAction": {"service": mining.name, "kind": "RemoteFunction"},
        },
        "remotes": {remote: "RemoteFunction", "MineOreAction": "RemoteFunction"},
        "world_objects": [{"name": "OreNodeA23810", "class": "Part"}],
        "module_world_objects": {mining.module_id: ["OreNodeA23810"]},
        "module_remotes": {owner.module_id: [remote], client.module_id: [remote]},
    }
    p = RobloxProposal(
        game_title="General spacecraft construction", description="Assemble a vessel",
        requested_prompt="Build a modular ship with resources from mining",
        game_design={"dynamic_design": design}, modules=[mining, owner, client],
    )
    return p, owner, client


def test_new_single_section_contract_dispatches_to_host_and_one_json_call():
    proposal, owner, client = plan()
    assert eligible_ship_attachment(owner, proposal) is not None
    assert eligible_ship_attachment(client, proposal) is not None
    assert render_host_gameplay(owner, proposal) is None
    scope = generation_scope(proposal)
    assert scope["counts"]["host_declarative_ship_attachment"] == 2
    router = SectionDataOnly()
    coder = LuauCodeGenerator(router)
    server = coder.generate_with_self_correction(owner, proposal)
    ui = coder.generate_with_self_correction(client, proposal)
    assert len(router.calls) == 1
    assert router.calls[0][1]["json_schema"]["required"] == ["sections"]
    assert router.calls[0][1]["max_tokens"] <= 950
    assert '["Engine"] = {cost = 5, performance = 8' in server
    assert 'GetState(player, "RMMShipSections")' in server
    assert 'GetState(player, "RMMInventory")' in server
    assert 'inventory.resources = resources - definition.cost' in server
    assert 'profile.sections[id] = {owned = true, level = 1,' in server
    assert 'profile.sections[id] ~= nil' in server
    assert '(root.Position - anchor.Position).Magnitude > RANGE' in server
    assert 'player:SetAttribute("RMMShipAssemblyPerformance", score)' in server
    assert 'occupied[index] = true' in server
    assert 'remote:InvokeServer(section.id)' in ui
    assert 'WaitForChild("BuildShipSectionAction", 20)' in ui
    assert 'status.Text = "Server validating build..."' in ui
    assert 'lastActionTime' not in server and 'SetState(' not in server
    for m, code in [(owner, server), (client, ui)]:
        errors = [d for d in LuauStaticAnalyzer().analyze_source(code, m.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(e.rule, e.line_number, e.message) for e in errors]


@pytest.mark.parametrize("field,value", [
    ("id", "[[bad]]"), ("id", "1Nope"), ("cost", 0), ("cost", True),
    ("cost", -5), ("performance", 1001), ("performance", False),
    ("label", ""), ("label", " " * 60),
])
def test_bad_model_data_fails_closed(field, value):
    section = {"id": "Engine", "label": "Engine", "cost": 5, "performance": 2}
    section[field] = value
    with pytest.raises(ValueError):
        _validated_sections({"sections": [section]})


def test_missing_mining_world_or_transport_never_claims_unrelated_service():
    proposal, owner, client = plan()
    proposal.game_design["dynamic_design"]["module_world_objects"]["dyn_mine"] = []
    assert eligible_ship_attachment(owner, proposal) is None
    assert eligible_ship_attachment(client, proposal) is None
    proposal, owner, client = plan()
    proposal.game_design["dynamic_design"]["host_actions"]["BuildShipSectionAction"]["kind"] = "RemoteEvent"
    assert eligible_ship_attachment(owner, proposal) is None
    proposal, owner, _ = plan()
    owner.description = "The server shows decorative spaceship parts in a display case."
    assert eligible_ship_attachment(owner, proposal) is None


def test_fails_closed_when_catalog_data_cannot_be_created():
    p, server, _ = plan()
    model = SectionDataOnly({"sections": [{"id": "Engine", "cost": -1}]})
    with pytest.raises(ValueError, match="HOST_SHIP_ATTACHMENT_CATALOG_EXHAUSTED"):
        try_ship_attachment(server, p, model)
    assert len(model.calls) == 2


def test_cached_catalog_generates_same_ui_after_resume_without_new_inference():
    p, server, client = plan()
    model = SectionDataOnly()
    first = try_ship_attachment(server, p, model)
    assert first
    assert try_ship_attachment(client, p, None)
    assert len(model.calls) == 1
    p.game_design["_host_ship_attachment_catalogs"][server.name][0]["cost"] = -1
    with pytest.raises(ValueError, match="Invalid section"):
        try_ship_attachment(server, p, None)


def test_module_names_not_bound_to_specific_past_prompt():
    p, server, client = plan(server_name="UndergroundVesselConstructionServer")
    assert eligible_ship_attachment(server, p)
    assert eligible_ship_attachment(client, p)



def test_followup_server_contract_uses_existing_ship_profile_not_fake_sibling_api():
    from roblox_mod_ai.server_modules import module_bootstrap_contract
    from roblox_mod_ai.host_service_codegen import try_scaffolded_server
    p, _owner, _client = plan()
    next_module = RobloxModuleSpec(
        module_id="dyn_launch", name="OpenWorldLaunchControllerServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/OpenWorldLaunchControllerServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="The server verifies built ship sections and player eligibility before launch.",
    )
    p.modules.append(next_module)
    p.game_design["dynamic_design"]["host_actions"]["LaunchVesselAction"] = {
        "service": next_module.name, "kind": "RemoteFunction",
    }
    p.game_design["dynamic_design"]["remotes"]["LaunchVesselAction"] = "RemoteFunction"
    exported = module_bootstrap_contract(next_module, p)
    assert '"RMMShipSections").sections' in exported
    assert "RMMShipAssemblyPerformance" in exported
    assert "GetSection" in exported and "Do not call invented" in exported

    class Capture:
        def __init__(self):
            self.prompts = []
            self.last_generation_report = {}

        def complete(self, prompt, **_kwargs):
            self.prompts.append(prompt)
            return (
                'local saved = services.PlayerDataManager.GetState(player, "RMMShipSections")\n'
                'if not saved or type(saved.sections) ~= "table" then return false end\n'
                'local installed = 0\n'
                'for _, part in pairs(saved.sections) do\n'
                '    if type(part) == "table" and part.owned == true then installed += 1 end\n'
                'end\n'
                'if installed < 2 then return false end\n'
                'player:SetAttribute("RMMVesselLaunchEligible", true)\n'
                'return true'
            )

    model = Capture()
    assert try_scaffolded_server(next_module, p, model, LuauStaticAnalyzer())
    assert len(model.prompts) == 1
    assert '"RMMShipSections").sections' in model.prompts[0]
    assert "getAssembly" in model.prompts[0]
