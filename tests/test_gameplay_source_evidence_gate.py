"""Routed gameplay cannot pass on host boilerplate or a textual effect claim."""
from types import SimpleNamespace

from roblox_mod_ai.gameplay_source_evidence import (
    authored_action_body, has_gameplay_mutation, state_key_used_by_executable_code,
)
from roblox_mod_ai.module_generation_gate import generated_module_errors
from roblox_mod_ai.spec import ModuleKind


SOURCE = """--!strict
local Service = {}
function Service.start(services)
    Service._services = services
end
function Service.handleAction(player, services, ...)
    -- RMM_GAMEPLAY_BODY_BEGIN
    print("player:SetAttribute('Colonized', true)")
    -- workspace:SetAttribute("Colonized", true)
    return true
    -- RMM_GAMEPLAY_BODY_END
end
return Service
"""


def test_routed_source_cannot_use_host_registry_or_printed_mutation():
    assert authored_action_body(SOURCE).strip().startswith("-- RMM_GAMEPLAY_BODY_BEGIN") is False
    assert not has_gameplay_mutation(SOURCE, routed_action=True)
    assert not has_gameplay_mutation(
        '--!strict\nlocal Service = {}\nfunction Service.start(s)\n'
        'Service._services = services\nend\nreturn Service\n'
    )


def test_mutation_must_be_inside_action_not_an_unrelated_startup():
    code = SOURCE.replace(
        '    print("player:SetAttribute(\'Colonized\', true)")',
        '    print("nothing happens")',
    ).replace("    Service._services = services",
              '    workspace:SetAttribute("NotRequested", true)\n    Service._services = services')
    assert not has_gameplay_mutation(code, routed_action=True)
    assert has_gameplay_mutation(code)


def test_real_routed_action_candidate_is_detectable():
    code = SOURCE.replace(
        '    print("player:SetAttribute(\'Colonized\', true)")',
        '    player:SetAttribute("Colonized", true)',
    )
    assert has_gameplay_mutation(code, routed_action=True)


def test_generation_checkpoint_rejects_fake_routed_effect():
    module = SimpleNamespace(
        name="WorldInteractionServer", module_id="dyn_world",
        file_path="src/server/WorldInteractionServer.luau",
        kind=ModuleKind.SERVER_MODULE,
    )
    proposal = SimpleNamespace(
        modules=[module],
        game_design={"dynamic_design": {
            "host_actions": {"Act": {"service": module.name}},
            "host_world_actions": {},
        }},
    )

    class Analyzer:
        def analyze_source(self, *_args, **_kwargs):
            return []

    errors = generated_module_errors(module, proposal, SOURCE, Analyzer())
    assert any(error.startswith("ACTION_EFFECT_UNIMPLEMENTED:") for error in errors)
    implementation = SOURCE.replace(
        '    print("player:SetAttribute(\'Colonized\', true)")',
        '    player:SetAttribute("Colonized", true)',
    )
    corrected = generated_module_errors(module, proposal, implementation, Analyzer())
    assert not any(error.startswith("ACTION_EFFECT_UNIMPLEMENTED:") for error in corrected)


def test_typed_effect_key_must_appear_on_real_mutation_target():
    assert not state_key_used_by_executable_code(
        '-- player:SetAttribute("ColonyOwned", true)\n'
        'print("ColonyOwned")\n'
        'workspace:SetAttribute("UnrelatedWorldFlag", true)\n',
        "ColonyOwned",
    )
    assert not state_key_used_by_executable_code(
        'local ColonyOwned = true\n'
        'workspace:SetAttribute("WrongFlag", ColonyOwned)\n',
        "ColonyOwned",
    )
    assert not state_key_used_by_executable_code(
        'services.PlayerDataManager.GetState(player, "ColonyOwned")\n'
        'workspace:SetAttribute("WrongFlag", true)\n',
        "ColonyOwned",
    )
    assert state_key_used_by_executable_code(
        'player:SetAttribute("ColonyOwned", true)\n',
        "ColonyOwned",
    )
    assert state_key_used_by_executable_code(
        "inventory.resources += 1\n", "RMMInventory.resources",
    )
    assert state_key_used_by_executable_code(
        "coins.Value += 1\n", "Coins",
    )


def test_saved_typed_action_cannot_swap_requested_state_effect_for_unrelated_flag():
    """After recovery the server must still change the exact planned state."""
    module = SimpleNamespace(
        name="ColonyServer", module_id="dyn_colony",
        file_path="src/server/ColonyServer.luau", kind=ModuleKind.SERVER_MODULE,
    )
    proposal = SimpleNamespace(
        modules=[module],
        game_design={"dynamic_design": {
            "host_actions": {"FoundColony": {"service": module.name}},
            "host_world_actions": {},
            "host_typed_actions": {
                "FoundColony": {
                    "server": module.name,
                    "contract": {"state_changes": [
                        {"scope": "player", "key": "ColonyOwned", "operation": "set"}
                    ]},
                },
            },
        }},
    )

    class Analyzer:
        def analyze_source(self, *_args, **_kwargs):
            return []

    bad = SOURCE.replace(
        '    print("player:SetAttribute(\'Colonized\', true)")',
        '    workspace:SetAttribute("UnrelatedWorldFlag", true)',
    )
    rejected = generated_module_errors(module, proposal, bad, Analyzer())
    assert any("TYPED_STATE_EFFECT_MISSING" in error for error in rejected), rejected
    good = bad.replace(
        '    workspace:SetAttribute("UnrelatedWorldFlag", true)',
        '    player:SetAttribute("ColonyOwned", true)',
    )
    validated = generated_module_errors(module, proposal, good, Analyzer())
    assert not any("TYPED_STATE_EFFECT_MISSING" in error
                   for error in validated), validated
