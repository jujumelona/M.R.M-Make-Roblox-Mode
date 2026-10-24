"""Regression for the recurring architecture/codegen ABI mismatches in plan80.

This is deliberately game-agnostic: service registry membership comes from
actual built ModuleScripts and one-target action inputs from the semantic
action schema, not keywords in the original game prompt.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.server_interface_audit import dependency_api_errors
from roblox_mod_ai.typed_action_contract import (
    host_owned_action_contract, validate_contract, lua_server_guard,
)


def _module(name: str, source: str = ""):
    return NS(name=name, module_id="dyn_" + name,
              file_path="src/server/" + name + ".luau", code=source)


def test_nonexistent_injected_service_is_rejected_without_call():
    db = _module("PlayerDataManager",
                 "local Service = {}\nfunction Service.GetState(player, key)\n"
                 " return {}\nend\nreturn Service")
    user = _module("SourceGameplay")
    proposal = NS(modules=[db, user])
    code = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "  local bogus = services.WorldProp81\n"
        "  local owned = services.PlayerDataManager.GetState(player, 'Owned')\n"
        "  if bogus then return true end\n"
        "  return false\nend\nreturn Service\n"
    )
    issues = dependency_api_errors(user, proposal, code)
    assert any("DEPENDENCY_SERVICE_UNKNOWN" in e and "WorldProp81" in e
               for e in issues), issues
    assert not any("services.PlayerDataManager is not" in e for e in issues)


def test_valid_injected_real_service_and_runtime_world_are_not_rejected():
    db = _module("PlayerDataManager",
                 "local Service = {}\nfunction Service.GetState(player, key)\n"
                 " return {}\nend\nreturn Service")
    user = _module("SourceGameplay")
    p = NS(modules=[db, user])
    code = (
        "local Service = {}\n"
        "function Service.handleAction(player, services, ...)\n"
        "  local entity = workspace:FindFirstChild('WorldProp81')\n"
        "  local state = services.PlayerDataManager.GetState(player, 'Owned')\n"
        "  return entity and state ~= nil\nend\nreturn Service\n"
    )
    assert not any("DEPENDENCY_SERVICE_UNKNOWN" in e
                   for e in dependency_api_errors(user, p, code))


def test_source_grounded_single_entity_gets_button_not_two_dummy_inputs():
    c = host_owned_action_contract(world_entities=["single_authored_target"])
    assert c["inputs"] == []
    validate_contract(c, world_entities=["single_authored_target"],
                      transport_only=True)
    guard = lua_server_guard(c)
    assert "local actionArgs = ..." in guard
    assert '__rmmAllowedFields["selection"]' not in guard
    assert '__rmmAllowedFields["quantity"]' not in guard


def test_host_world_transition_is_zero_input_when_target_is_server_selected():
    c = host_owned_action_contract(
        world_entities=["actor", "destination", "arrival"],
        host_selects_target=True,
    )
    assert c["inputs"] == []


def test_multiple_unbound_targets_do_not_silently_claim_one():
    c = host_owned_action_contract(
        world_entities=["seller", "buyer"],
        host_selects_target=False,
    )
    assert [row["id"] for row in c["inputs"]] == ["selection", "quantity"]


def test_source_authorized_choice_remains_enforced_without_dropping_quantity():
    c = host_owned_action_contract([
        {"id": "basic", "label": "Basic"},
        {"id": "premium", "label": "Premium"},
    ])
    assert [row["id"] for row in c["inputs"]] == ["selection", "quantity"]
    assert c["inputs"][0]["type"] == "choice"



def test_unrelated_world_targets_are_not_exposed_to_a_coder():
    from roblox_mod_ai.world_object_abi import (
        world_lookup_guidance, world_lookup_errors,
    )
    mod = NS(name="IndependentAction", module_id="dyn_self")
    p = NS(modules=[mod], game_design={"dynamic_design": {
        "world_objects": [
            {"name": "AuthorizedMachine", "class": "Part"},
            {"name": "OtherPlayersInventory", "class": "Part"},
        ],
        "module_world_objects": {mod.module_id: ["AuthorizedMachine"]},
    }})
    instructions = world_lookup_guidance(p, mod)
    assert '"AuthorizedMachine"' in instructions
    assert "OtherPlayersInventory" not in instructions
    assert world_lookup_errors(
        'local a = workspace:FindFirstChild("AuthorizedMachine")',
        p, mod,
    ) == []
    assert any("WORLD_OBJECT_NAME_UNDECLARED" in e for e in
               world_lookup_errors(
                   'local a = workspace:FindFirstChild("OtherPlayersInventory")',
                   p, mod,
               ))


def test_unrelated_world_target_still_exists_but_is_forbidden_for_this_action():
    from roblox_mod_ai.world_object_abi import world_names
    first = NS(name="A", module_id="dyn_a")
    second = NS(name="B", module_id="dyn_b")
    p = NS(game_design={"dynamic_design": {
        "world_objects": [{"name": "TargetA"}, {"name": "TargetB"}],
        "module_world_objects": {"dyn_a": ["TargetA"], "dyn_b": ["TargetB"]},
    }})
    assert world_names(p, first)[1] == ["TargetA"]
    assert world_names(p, second)[1] == ["TargetB"]
