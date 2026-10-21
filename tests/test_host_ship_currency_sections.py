"""Regression for the actual currency-paid section assembly failure in ZIP 16.

The previous host router required a fourth 'upgrade' verb even though this
design authorizes only create/replace/remove, and it incorrectly charged ore.
The host now owns the entire money transaction and model writes only JSON.
"""
from copy import deepcopy

import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_ship_sections import eligible_ship_sections, try_ship_sections
from roblox_mod_ai.host_ship_currency_sections import (
    _validate_currency_slots, eligible_currency_ship_sections,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class OptionsOnly:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or {"slots": [
            {"id": "Hull", "label": "Hull", "options": [
                {"id": "BasicHull", "label": "Basic", "cost": 30, "performance": 20},
                {"id": "ArmorHull", "label": "Armored", "cost": 50, "performance": 45},
            ]},
            {"id": "Engine", "label": "Engine", "options": [
                {"id": "BasicEngine", "label": "Basic", "cost": 40, "performance": 30},
            ]},
        ]}

    def complete(self, *args, **kwargs):
        raise AssertionError("A small model must never implement ship money transactions")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return deepcopy(self.rows)


def _plan(name="SectionBySectionSpaceshipB327A61Server"):
    client_name = name.removesuffix("Server") + "Client"
    description = (
        "The server maintains a per-player ship assembly as a collection of "
        "independent section slots (e.g. hull, cockpit, engine, weapon, crew, "
        "shield, cargo). Each section is a discrete, independently creatable "
        "slot; a player may create, replace, or remove any one section without "
        "affecting the others. Creating a section validates the player's earned "
        "game currency against the section's cost, then deducts the currency "
        "and records the section in the player's ship assembly. Replacing a "
        "section validates the new section's cost and applies the delta to "
        "the player's currency. Removing a section returns its value to the "
        "player's currency. The server computes the ship's performance from "
        "the assembled sections and persists the assembly and currency."
    )
    server = RobloxModuleSpec(
        module_id="dyn_24ee3ea10bef", name=name,
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/" + name + ".luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=description,
    )
    client = RobloxModuleSpec(
        module_id="dyn_c495c88dc957", name=client_name,
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/" + client_name + ".client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Show owned sections, currency balance, create/replace/remove controls.",
    )
    remote = name.removesuffix("Server") + "Action"
    design = {"dynamic_design": {
        "host_actions": {remote: {"service": server.name, "kind": "RemoteFunction"}},
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {
            server.module_id: [remote], client.module_id: [remote],
        },
        "module_world_objects": {server.module_id: [], client.module_id: []},
        "world_objects": [],
    }}
    return RobloxProposal(
        requested_prompt="Build a modular vehicle with earned currency",
        game_title="Modular builder", description="Currency-driven ship sections",
        game_design=design, modules=[server, client],
    ), server, client, remote


def test_failed_actual_scoped_module_now_uses_short_json_and_host_code():
    plan, server, client, remote = _plan()
    assert eligible_ship_sections(server, plan) == (server.name, remote)
    assert eligible_ship_sections(client, plan) == (server.name, remote)
    assert eligible_currency_ship_sections(server, plan)
    scope = generation_scope(plan)
    roles = {row["name"]: row["strategy"] for row in scope["modules"]}
    assert roles[server.name] == "host_declarative_ship_sections"
    assert roles[client.name] == "host_declarative_ship_sections"
    router = OptionsOnly()
    generator = LuauCodeGenerator(router)
    code = generator.generate_with_self_correction(server, plan)
    ui = generator.generate_with_self_correction(client, plan)
    assert len(router.calls) == 1
    assert router.calls[0][1]["max_tokens"] <= 1100
    assert "NO Luau" in router.calls[0][0]
    assert code == try_ship_sections(server, plan, None)
    assert ui == try_ship_sections(client, plan, None)
    assert '["Hull"] = {order = 1' in code
    assert '["ArmorHull"] = {cost = 50, performance = 45}' in code
    assert 'GetState(player, "RMMShipSections")' in code
    assert 'player:SetAttribute("RMMShipPerformance", result.performance)' in code
    assert 'player:SetAttribute("RMMShipAssemblyPerformance", result.performance)' in code
    assert 'local netCharge = targetPaid - oldPaid' in code
    assert 'coins.Value -= netCharge' in code
    assert 'return reject("stale_variant")' in code
    assert 'return reject("currency_overflow")' in code
    assert 'if netCharge > coins.Value then return reject("insufficient_currency") end' in code
    assert 'sections[slotId] = nil' in code
    assert 'paidPrice = targetPaid' in code
    assert 'part:SetAttribute("ShipSectionVariant", installed.variantId)' in code
    assert 'remote:InvokeServer(action, slotId, optionId)' in ui
    assert 'for _, action in {"create", "replace", "remove"} do' in ui
    assert "PlayerDataManager:GetState" not in code
    assert 'sectionCost = ...' not in code
    assert "costNumberRaw = tonumber" not in code
    assert "newCost" not in code
    for module, source in ((server, code), (client, ui)):
        errors = [diag for diag in LuauStaticAnalyzer().analyze_source(
            source, module.file_path) if diag.severity == "ERROR"]
        assert not errors, [(diag.rule, diag.line_number, diag.message) for diag in errors]


def test_names_and_game_prompt_do_not_select_host_route():
    plan, server, client, remote = _plan("GeneralIndependentPartsServer")
    plan.requested_prompt = "Make an independent modular vehicle design studio"
    assert eligible_ship_sections(server, plan)
    assert eligible_ship_sections(client, plan)
    assert try_ship_sections(server, plan, OptionsOnly()) is not None
    server.description = "Server draws decorative model Parts, no currency transactions"
    assert eligible_ship_sections(server, plan) is None


def test_refuse_unsupported_route_or_missing_ownership():
    plan, server, client, remote = _plan()
    plan.game_design["dynamic_design"]["host_actions"][remote]["kind"] = "RemoteEvent"
    assert eligible_ship_sections(server, plan) is None
    plan, server, client, remote = _plan()
    plan.game_design["dynamic_design"]["host_actions"][remote]["max_args"] = 2
    assert eligible_ship_sections(server, plan) is None
    plan, server, client, remote = _plan()
    plan.game_design["dynamic_design"]["module_remotes"][client.module_id] = ["Other"]
    assert eligible_ship_sections(client, plan) is None
    plan, server, client, remote = _plan()
    plan.modules.remove(server)
    assert eligible_ship_sections(client, plan) is None


@pytest.mark.parametrize("bad", [
    {"slots": []},
    {"slots": [{"id": "Hull", "label": "Hull", "options": []}]},
    {"slots": [{"id": "Hull", "label": "Hull", "options": [
        {"id": "Basic", "label": "Basic", "cost": 0, "performance": 40},
    ]}]},
    {"slots": [{"id": "Hull", "label": "Hull", "options": [
        {"id": "Basic", "label": "Basic", "cost": 40, "performance": True},
    ]}]},
    {"slots": [{"id": "Hull", "label": "Hull", "options": [
        {"id": "Basic", "label": "Basic", "cost": 40, "performance": 20},
        {"id": "basic", "label": "Dup", "cost": 40, "performance": 20},
    ]}]},
    {"slots": [{"id": "end();", "label": "Injection", "options": [
        {"id": "Basic", "label": "Basic", "cost": 40, "performance": 20},
    ]}]},
])
def test_invalid_currency_section_catalog_fail_closed(bad):
    with pytest.raises(ValueError):
        _validate_currency_slots(bad)


def test_cached_currency_catalog_is_revalidated_no_second_model_call():
    plan, server, client, remote = _plan()
    coder = OptionsOnly()
    assert try_ship_sections(server, plan, coder)
    assert try_ship_sections(client, plan, None)
    assert len(coder.calls) == 1
    plan.game_design["_host_currency_ship_sections"][server.name][0]["options"][0]["cost"] = -1
    with pytest.raises(ValueError):
        try_ship_sections(server, plan, None)
