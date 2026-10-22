"""End-to-end regressions: production pipeline does not ask a 9B LLM to invent
a second typed/state-transition plan before writing real Luau gameplay.
Applies to arbitrary source semantics, not a space/trade keyword shortcut.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.typed_action_contract import (
    host_owned_action_contract, validate_contract, TypedActionContractError,
    render_typed_client, lua_server_guard,
)
from roblox_mod_ai.spec import RobloxProposal, ModuleKind
from roblox_mod_ai.server_modules import normalize_dynamic_server_modules
from roblox_mod_ai.code_generator import LuauCodeGenerator


@pytest.mark.parametrize("source,name,behavior,result", [
    (
        "Trade earned game resources",
        "Trade",
        "The server checks owned inventory and trade requests, removes "
        "the approved resource and adds the earned currency to the "
        "player's authoritative balance.",
        "The inventory decreases and the currency balance increases.",
    ), (
        "Water a growing fruit tree",
        "WaterTree",
        "The server checks the owned water quantity, subtracts water from "
        "the player's storage and increases the tree's saved growth state.",
        "The tree's next growth stage becomes visible.",
    ), (
        "Upgrade a vehicle engine",
        "UpgradeEngine",
        "The server validates the player's vehicle ownership and parts "
        "inventory, consumes materials and increases the persisted engine level.",
        "The vehicle's engine level increases and used items disappear.",
    ),
])
def test_production_host_standard_transport_eliminates_extra_model_metadata(
        monkeypatch, source, name, behavior, result):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-1", "statement": source}],
        "facets": [{"id": "intent-a", "source_span": source,
                    "requirements": ["req-1"],
                    "search_query": "Roblox " + source}],
    }, "evidence": []}

    class SmallModel:
        # ModelRouter uses this production capability; a 9B cannot provide
        # the triple schema (inputs+target+state_changes) consistently.
        supports_host_standard_transport = True
        supports_typed_action_contract = False

        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            assert len(self.calls) == 1, (
                "NO second inferred typed state contract and NO repeated "
                "whole-game plan generation")
            return {"systems": [{
                "name": name,
                "server_behavior": behavior,
                "client_behavior": "",
                "observable_result": result,
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": [],
            }]}

    model = SmallModel()
    generated = RobloxDynamicArchitect(model).design(source, research, [])
    assert len(model.calls) == 1
    assert generated["host_typed_actions"]
    spec = next(iter(generated["host_typed_actions"].values()))
    assert spec["transport_only"] is True
    assert spec["contract"]["state_changes"] == []
    assert [x["id"] for x in spec["contract"]["inputs"]] == [
        "selection", "quantity"]
    assert generated["host_actions"]


def test_host_standard_input_has_real_bounds_but_does_not_forge_state_effects():
    c = host_owned_action_contract()
    assert c["state_changes"] == []
    with pytest.raises(TypedActionContractError, match="state change"):
        validate_contract(c, world_entities=[])
    normalized = validate_contract(c, world_entities=[], transport_only=True)
    guard = lua_server_guard(normalized)
    assert "quantity" in guard and "> 10000" in guard
    assert 'typeof(actionArgs) ~= "table"' in guard
    assert "selection" in guard
    assert "wallet" not in guard and "inventory" not in guard


def test_host_standard_preserves_original_choices_as_remote_allowlist():
    choices = [
        {"id": "Gather", "label": "Gather resources"},
        {"id": "Craft", "label": "Craft item"},
    ]
    spec = host_owned_action_contract(choices)
    normalized = validate_contract(spec, world_entities=[],
                                   transport_only=True)
    assert normalized["inputs"][0]["type"] == "choice"
    guard = lua_server_guard(normalized)
    assert '["Gather"] = true' in guard
    assert '["Craft"] = true' in guard
    assert "Robux" not in guard


def test_host_input_service_codegen_renders_real_guard_and_gameplay_body():
    from roblox_mod_ai.host_service_codegen import _shell
    from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
    contract = validate_contract(
        host_owned_action_contract(), world_entities=[],
        transport_only=True,
    )
    body = (
        'local selection = actionArgs.selection\n'
        'local quantity = actionArgs.quantity\n'
        'if selection == "" then return false end\n'
        'local data = services.PlayerDataManager.GetState(player, "RMMInventory")\n'
        'if not data or type(data.resources) ~= "number" then return false end\n'
        'if data.resources < quantity then return false end\n'
        'data.resources -= quantity\n'
        'return true'
    )
    luau = _shell(body, typed_contract=contract)
    assert luau.index('typeof(actionArgs) ~= "table"') < luau.index(
        'data.resources -=')
    issues = [issue for issue in LuauStaticAnalyzer().analyze_source(
        luau, "src/server/HostStandardGame.luau")
        if issue.severity == "ERROR"]
    assert not issues, issues


def test_host_standard_does_not_call_second_json_or_fake_success(
        monkeypatch):
    """Bug 58 source: valid trade server plan used to produce three *wrong*
    schema outputs and blocked the entire project. Exactly one call now.
    """
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Trade game items with a merchant"
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "r-trade", "statement": source}],
        "facets": [{"id": "f-trade", "source_span": source,
                    "requirements": ["r-trade"],
                    "search_query": "Roblox trade items with merchant"}],
    }, "evidence": []}
    class Model:
        supports_host_standard_transport = True
        supports_typed_action_contract = True  # host must take precedence
        def __init__(self): self.calls = 0
        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("Forbidden: schema re-generation from 9B")
            return {"systems": [{
                "name": "MerchantTrade",
                "server_behavior": (
                    "The server validates ownership, in-game item quantity "
                    "and the merchant's exchange prices, deducts owned "
                    "resources and updates authoritative player currency."
                ),
                "client_behavior": "",
                "observable_result": (
                    "The player's inventory and game currency balance update."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": [],
                "action_choices": [
                    {"id": "Sell", "label": "Sell"},
                    {"id": "Buy", "label": "Buy"},
                ],
            }]}
    m = Model()
    got = RobloxDynamicArchitect(m).design(source, research, [])
    assert m.calls == 1
    assert len(got["host_typed_actions"]) == 1
    binding = next(iter(got["host_typed_actions"].values()))
    assert binding["transport_only"] is True
    assert binding["contract"]["inputs"][0]["type"] == "choice"
    assert [x["id"] for x in binding["contract"]["inputs"][0]["options"]] == [
        "Sell", "Buy"]
    assert not got["host_action_choices"]
