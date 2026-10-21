"""A real mode gate has to be reachable from a host-built ship, not a fake attr."""
from copy import deepcopy
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_performance_mode import render_host_performance_mode
from roblox_mod_ai.host_ship_reconfiguration import (
    eligible_ship_reconfiguration, try_ship_reconfiguration, _validate,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


class OnlyData:
    def __init__(self, payload=None):
        self.calls = []
        self.data = payload if payload is not None else {
            "maxParts": 3, "requiredSlots": ["Hull", "Engine"],
            "parts": [
                {"id": "HullA", "label": "Basic Hull", "slot": "Hull",
                 "resourceCost": 3, "performance": 50},
                {"id": "HullB", "label": "Shielded Hull", "slot": "Hull",
                 "resourceCost": 9, "performance": 70},
                {"id": "EngineA", "label": "Engine", "slot": "Engine",
                 "resourceCost": 6, "performance": 30},
                {"id": "CrewA", "label": "Crew Quarters", "slot": "Crew",
                 "resourceCost": 4, "performance": 35},
            ],
        }
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Tiny LLM cannot own durable ship state or mode gate Luau")

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return deepcopy(self.data)


def plan():
    def module(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_" + name, name=name, kind=kind,
            file_path=("src/server/" + name + ".luau"
                       if kind == ModuleKind.SERVER_MODULE else
                       "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE else
                            RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    builder = module("ArbitraryStructuralShipBuilderServer", ModuleKind.SERVER_MODULE,
        "The server owns the ship assembly state and validates every part addition, "
        "removal, and swap before applying it. A player request is accepted only "
        "when the requesting player is the ship's owner or has an active build "
        "permission, the target part exists in the server-side part catalog, "
        "the target part is not already installed on the ship, the resulting "
        "ship still satisfies the minimum structural requirements for its "
        "class, and the ship's total installed part count remains within "
        "the catalog's per-ship limit. On success the server adds or replaces "
        "the part in the ship's authoritative part list, persists the resulting "
        "build, and emits the observable result to the client. On failure "
        "the server rejects the request with a specific reason.")
    ui = module("ArbitraryStructuralShipBuilderClient", ModuleKind.CLIENT_SCRIPT,
        "The player selects a part, slot, and add, remove or swap action.")
    mode = module("AnotherCustomSpaceModeServer", ModuleKind.SERVER_MODULE,
        "The server owns the space-mode state machine and validates every "
        "mode transition. A player may only enter space mode when the ship's "
        "performance value is at least 100, and the server rejects the "
        "transition with a clear message otherwise. Entering space mode is "
        "a server-authoritative state change, never a client-reported value.")
    mode_ui = module("AnotherCustomSpaceModeClient", ModuleKind.CLIENT_SCRIPT,
        "The player sees the mode and confirms server-validated entry.")
    design = {
        "host_actions": {
            "BuildAction": {"service": builder.name, "kind": "RemoteFunction"},
            "ModeAction": {"service": mode.name, "kind": "RemoteFunction"},
        },
        "remotes": {"BuildAction": "RemoteFunction", "ModeAction": "RemoteFunction"},
        "module_remotes": {
            builder.module_id: ["BuildAction"], ui.module_id: ["BuildAction"],
            mode.module_id: ["ModeAction"], mode_ui.module_id: ["ModeAction"],
        },
    }
    p = RobloxProposal(requested_prompt="Assemble an arbitrary ship with mining",
                       game_title="General Vehicle", description="Configurable ship",
                       modules=[mode, mode_ui, builder, ui],
                       game_design={"dynamic_design": design})
    return p, mode, mode_ui, builder, ui


def test_real_assembly_contract_and_mode_threshold_work_as_same_host_state():
    p, mode, mode_ui, builder, ui = plan()
    assert eligible_ship_reconfiguration(builder, p)
    assert eligible_ship_reconfiguration(ui, p)
    scope = generation_scope(p)
    assert scope["counts"]["host_declarative_ship_reconfiguration"] == 2
    assert not scope["unverified_cross_module_dependencies"]
    coder = LuauCodeGenerator(OnlyData())
    mode_code = coder.generate_with_self_correction(mode, p)
    server_code = coder.generate_with_self_correction(builder, p)
    client_code = coder.generate_with_self_correction(ui, p)
    mode_ui_code = coder.generate_with_self_correction(mode_ui, p)
    assert len(coder.router.calls) == 1
    assert coder.router.calls[0][1]["max_tokens"] <= 1250
    assert "Highest possible performance at cap must be >= 100" in coder.router.calls[0][0]
    assert server_code == try_ship_reconfiguration(builder, p, None)
    assert mode_code == render_host_performance_mode(mode, p)
    assert "local MAX_PARTS = 3" in server_code
    assert '["HullB"] = {slot = "Hull", cost = 9, performance = 70' in server_code
    assert 'local REQUIRED = {["Hull"] = true, ["Engine"] = true}' in server_code
    assert 'manager.GetState(player, "RMMShipSections")' in mode_code
    assert 'manager.GetState(player, "RMMShipSections")' in server_code
    assert 'manager.GetState(player, "RMMInventory")' in server_code
    assert 'profile.sections = nextParts' in server_code
    assert 'inventory.resources = resources - cost' in server_code
    assert 'player:SetAttribute("RMMShipPerformance", current.performance)' in server_code
    assert 'player:SetAttribute("RMMShipReady", current.ready)' in server_code
    assert '"essential_structure"' in server_code
    assert '"part_cap"' in server_code
    assert '"already_installed"' in server_code
    assert 'existing.partId == partId' in server_code
    assert 'remote:InvokeServer(action, part.id, part.slot)' in client_code
    assert 'call("enter")' in mode_ui_code
    assert "Coins.Value" not in server_code
    assert 'GetState(player, "RMMShipSections")' in mode_code
    for m,code in ((mode,mode_code),(mode_ui,mode_ui_code),
                   (builder,server_code),(ui,client_code)):
        errors = [d for d in LuauStaticAnalyzer().analyze_source(code, m.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(m.name,d.rule,d.line_number,d.message) for d in errors]


@pytest.mark.parametrize("bad", [
    {"maxParts":3,"requiredSlots":["Hull","Engine"],
     "parts":[{"id":"Hull","slot":"Hull","label":"Hull","resourceCost":2,"performance":40}]},
    {"maxParts":1,"requiredSlots":["Hull","Engine"],
     "parts":[{"id":"Hull","slot":"Hull","label":"Hull","resourceCost":2,"performance":40},
              {"id":"Engine","slot":"Engine","label":"Engine","resourceCost":2,"performance":40}]},
    {"maxParts":1,"requiredSlots":["Hull"],
     "parts":[{"id":"Hull","slot":"Hull","label":"Hull","resourceCost":True,"performance":40},
              {"id":"Engine","slot":"Engine","label":"Engine","resourceCost":2,"performance":40}]},
    {"maxParts":1,"requiredSlots":["Hull"],
     "parts":[{"id":"Hull","slot":"Hull","label":"Hull","resourceCost":2,"performance":0},
              {"id":"Engine","slot":"Engine","label":"Engine","resourceCost":2,"performance":40}]},
])
def test_unreachable_or_malformed_catalog_fails_closed(bad):
    with pytest.raises(ValueError):
        _validate(bad, 100)


def test_does_not_replace_unrelated_shop_or_empty_game():
    p, mode, mode_ui, builder, ui = plan()
    p.game_design["dynamic_design"]["host_actions"]["BuildAction"]["kind"] = "RemoteEvent"
    assert eligible_ship_reconfiguration(builder, p) is None
    p, mode, mode_ui, builder, ui = plan()
    builder.description = "The server spawns a decorative ship statue."
    assert eligible_ship_reconfiguration(builder, p) is None
    p, mode, mode_ui, builder, ui = plan()
    p.game_design["dynamic_design"]["module_remotes"][ui.module_id] = ["Other"]
    assert eligible_ship_reconfiguration(ui, p) is None


def test_cache_resumes_with_same_validated_parts_and_rejects_tampering():
    p, mode, mode_ui, builder, ui = plan()
    router = OnlyData()
    assert try_ship_reconfiguration(builder, p, router)
    assert try_ship_reconfiguration(ui, p, None)
    assert len(router.calls) == 1
    p.game_design["_host_ship_reconfiguration"][builder.name]["parts"][0]["performance"] = 0
    with pytest.raises(ValueError):
        try_ship_reconfiguration(builder, p, None)



def test_optional_high_power_parts_cannot_fake_required_ship_layout():
    # A 2-part ship requiring Hull and Engine cannot use a third decoration's
    # high score to pass the authored launch/mode threshold.
    with pytest.raises(ValueError, match="Required structural parts cannot reach"):
        _validate({
            "maxParts": 2,
            "requiredSlots": ["Hull", "Engine"],
            "parts": [
                {"id":"Hull", "label":"Hull", "slot":"Hull",
                 "resourceCost":1, "performance":10},
                {"id":"Engine", "label":"Engine", "slot":"Engine",
                 "resourceCost":1, "performance":10},
                {"id":"Decoration", "label":"Decoration", "slot":"Decoration",
                 "resourceCost":1, "performance":200},
            ],
        }, 100)
