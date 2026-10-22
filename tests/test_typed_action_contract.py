"""Cross-domain typed action contract: model data -> deterministic UI/Remote/server."""
from __future__ import annotations

import copy
import pytest

from roblox_mod_ai.typed_action_contract import (
    SCHEMA, TypedActionContractError, validate_contract,
    lua_server_guard, render_typed_client,
)
from roblox_mod_ai.host_architecture import (
    expand_semantic_facet, HostArchitectureError,
)
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.spec import RobloxProposal
from roblox_mod_ai.server_modules import normalize_dynamic_server_modules


def _contract():
    return {
        "inputs": [
            {"id": "resource", "label": "Resource", "type": "choice",
             "options": [{"id": "ore", "label": "Ore"}, {"id": "wood", "label": "Wood"}]},
            {"id": "quantity", "label": "Quantity", "type": "integer", "min": 1, "max": 25},
            {"id": "note", "label": "Note", "type": "text"},
        ],
        "target": {"kind": "none"},
        "state_changes": [
            {"scope": "player", "key": "inventory.resources", "operation": "decrement"},
            {"scope": "player", "key": "wallet.credits", "operation": "increment"},
        ],
    }


def _system():
    return {
        "name": "TradeResources",
        "server_behavior": (
            "The server checks the user's owned inventory and validates "
            "the item, requested quantity and exchange rate before "
            "removing resources and incrementing earned credit balance."
        ),
        "client_behavior": "The player submits a validated trade request using the item selection interface.",
        "observable_result": (
            "The user's resource inventory decreases and earned credit "
            "balance increases after a confirmed trade."
        ),
        "interaction": "request_response", "input_mode": "custom",
        "world_entities": [],
    }


def _convert(system):
    return expand_semantic_facet(
        {"systems": [system]}, facet_id="f-trade",
        requirement_ids=["r-trade"],
        source_requirements=[{"id": "r-trade",
                              "statement": "Trade resources for earned credits"}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
    )


def test_typed_schema_rejects_unvalidated_params_and_unowned_target():
    good = validate_contract(_contract(), world_entities=[])
    assert good["inputs"][1]["min"] == 1
    for mutation in (
        lambda x: x["inputs"][1].update(min=-100, max=10**9),
        lambda x: x["inputs"][0]["options"].append({"id": "ore", "label": "Duplicated"}),
        lambda x: x["inputs"][2].update(debug={"hack": True}),
        lambda x: x["target"].update(kind="world_entity", name="OtherPlayerInventory"),
        lambda x: x["state_changes"].clear(),
        lambda x: x["state_changes"][0].update(operation="free-money"),
    ):
        invalid = copy.deepcopy(_contract())
        mutation(invalid)
        with pytest.raises(TypedActionContractError):
            validate_contract(invalid, world_entities=[])


def test_host_assigns_typed_contract_to_one_remote_and_keeps_state_effects():
    system = dict(_system(), action_contract=_contract())
    raw = _convert(system)
    assert len(raw["_host_typed_actions"]) == 1
    assert len(raw["modules"]) == 2
    remote = next(iter(raw["_host_typed_actions"]))
    spec = raw["_host_typed_actions"][remote]
    assert spec["contract"]["state_changes"] == _contract()["state_changes"]
    assert spec["server"].endswith("Server")
    assert spec["client"].endswith("Client")
    assert raw["remotes"] == [{"name": remote, "type": "RemoteFunction"}]


@pytest.mark.parametrize("interaction,mode", [
    ("none", "custom"), ("request_response", "host_button"),
    ("event", "world_prompt"),
])
def test_typed_contract_cannot_attach_to_unsupported_or_shadow_transport(interaction, mode):
    system = dict(_system(), action_contract=_contract(),
                  interaction=interaction, input_mode=mode)
    with pytest.raises(HostArchitectureError, match="Typed action contract"):
        _convert(system)


def test_server_guard_validates_every_input_and_rejects_unknown_extra_args():
    guard = lua_server_guard(validate_contract(_contract(), world_entities=[]))
    assert 'select("#", ...) ~= 1' in guard
    assert 'typeof(actionArgs) ~= "table"' in guard
    assert '__rmmAllowedFields["resource"]' in guard
    assert '__rmmAllowedFields["quantity"]' in guard
    assert 'type(actionArgs["quantity"]) ~= "number"' in guard
    assert 'actionArgs["quantity"] % 1 ~= 0' in guard
    assert 'actionArgs["quantity"] < 1' in guard
    assert 'actionArgs["quantity"] > 25' in guard
    assert 'type(actionArgs["note"]) ~= "string"' in guard
    assert 'actionArgs["resource"]' in guard
    assert '["ore"] = true' in guard
    assert '["wood"] = true' in guard
    assert "for key, _ in pairs(actionArgs)" in guard


def test_world_target_has_host_owned_name_and_server_distance_check():
    contract = {"inputs": [{"id": "amount", "label": "Amount",
                            "type": "integer", "min": 1, "max": 10}],
                "target": {"kind": "world_entity", "name": "HarvestNode"},
                "state_changes": [{"scope": "player", "key": "resources",
                                   "operation": "increment"}]}
    system = dict(_system(), action_contract=contract,
                  world_entities=["HarvestNode"])
    # This test is about a generic world target, not genre-specific source
    # validity; use the true source semantics when expanding.
    system.update(name="GatherResource", server_behavior=(
        "The server validates the targeted node and records the gathered "
        "resource in the player-owned inventory after reducing node health."
    ), observable_result=(
        "The node depletes and the player inventory increases visibly."
    ))
    result = expand_semantic_facet(
        {"systems": [system]}, facet_id="f-node",
        requirement_ids=["r-node"],
        source_requirements=[{"id": "r-node",
                              "statement": "Gather resources from node"}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
    )
    remote = next(iter(result["_host_typed_actions"]))
    binding = result["_host_typed_actions"][remote]
    world = binding["world_name"]
    assert world == result["world_objects"][0]["name"]
    guard = lua_server_guard(binding["contract"], world_name=world)
    assert 'workspace:FindFirstChild(' in guard
    assert world in guard
    assert 'HumanoidRootPart' in guard
    assert '.Magnitude > 24' in guard


def test_end_to_end_real_architect_typed_ui_requires_no_second_client_model(
        monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Trade resources for earned credits"
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "r-trade", "statement": source}],
        "facets": [{
            "id": "f-trade", "source_span": source,
            "requirements": ["r-trade"],
            "search_query": "Roblox Trade resources for earned credits",
        }],
    }, "evidence": []}
    class SmallModel:
        supports_typed_action_contract = True
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return {"systems": [_system()]}
            assert len(self.calls) == 2
            assert kwargs["json_schema"] == SCHEMA
            assert kwargs["max_tokens"] <= 500
            assert "server_behavior" in prompt
            return copy.deepcopy(_contract())
    model = SmallModel()
    result = RobloxDynamicArchitect(model).design(source, research, [])
    assert len(model.calls) == 2
    assert len(result["host_typed_actions"]) == 1
    remote, route = next(iter(result["host_typed_actions"].items()))
    assert result["host_actions"][remote]["max_args"] == 1
    proposal = RobloxProposal(
        requested_prompt=source, game_title="TypedTrade", description="",
        modules=list(result["modules"]),
        game_design={"dynamic_design": {
            key: value for key, value in result.items() if key != "modules"
        }, "pre_design_research": {"ledger": research["ledger"]}},
    )
    normalize_dynamic_server_modules(proposal)
    client = next(m for m in proposal.modules
                  if m.file_path.endswith(".client.luau"))
    class NeverCodeClient:
        def complete(self, *args, **kwargs):
            raise AssertionError("Typed input UI must not call the language model")
    ui = LuauCodeGenerator(NeverCodeClient()).generate_module_code(client, proposal)
    assert "ScreenGui" in ui
    assert "TextBox" in ui
    assert "TextButton" in ui
    assert "InvokeServer(payload)" in ui
    assert 'controls["resource"]' in ui
    assert 'controls["quantity"]' in ui
    assert remote in ui
    assert route["server"].endswith("Server")


def test_typed_server_shell_is_parsed_and_guards_contract_before_state_writes():
    from roblox_mod_ai.host_service_codegen import _shell
    from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
    contract = validate_contract(_contract(), world_entities=[])
    body = (
        'local resource = actionArgs["resource"]\n'
        'local quantity = actionArgs["quantity"]\n'
        'local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")\n'
        'if not inventory or type(inventory.resources) ~= "number" then return false end\n'
        'if inventory.resources < quantity then return false end\n'
        'inventory.resources -= quantity\n'
        'local wallet = services.PlayerDataManager.GetState(player, "RMMWallet")\n'
        'if not wallet then return false end\n'
        'wallet.credits = (wallet.credits or 0) + quantity\n'
        'return true'
    )
    source = _shell(body, typed_contract=contract)
    assert source.index('typeof(actionArgs)') < source.index('inventory.resources -=')
    assert source.index('for key, _ in pairs(actionArgs)') < source.index('wallet.credits =')
    assert '["ore"] = true' in source and '["wood"] = true' in source
    errors = [d.message for d in LuauStaticAnalyzer().analyze_source(
        source, "src/server/TypedTrade.luau") if d.severity == "ERROR"]
    assert errors == [], errors


def test_typed_server_generator_rejects_body_unrelated_to_declared_state_keys():
    from roblox_mod_ai.dynamic_architect import _clean_model_json
    from roblox_mod_ai.host_service_codegen import try_scaffolded_server
    from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
    from roblox_mod_ai.spec import ModuleKind

    raw = _convert(dict(_system(), action_contract=_contract()))
    ledger = {
        "original_prompt": "Trade resources for earned credits",
        "requirements": [{"id": "r-trade",
                          "statement": "Trade resources for earned credits"}],
        "facets": [{"id": "f-trade", "requirements": ["r-trade"],
                    "source_span": "Trade resources for earned credits"}],
    }
    expanded = _clean_model_json(raw, ledger, set())
    remote, typed = next(iter(raw["_host_typed_actions"].items()))
    design = {
        "host_actions": {
            remote: {"kind": "RemoteFunction", "service": typed["server"],
                     "max_args": 1}
        },
        "host_typed_actions": {remote: typed},
        "host_action_choices": {},
        "host_world_actions": {},
        "module_remotes": expanded["module_remotes"],
        "remotes": expanded["remotes"],
    }
    proposal = RobloxProposal(
        requested_prompt=ledger["original_prompt"],
        game_title="TypedTrade", description="",
        modules=expanded["modules"],
        game_design={"dynamic_design": design},
    )
    normalize_dynamic_server_modules(proposal)
    server = next(m for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE)

    class WrongCoder:
        def complete(self, prompt, **kwargs):
            # This still mutates a real server state; it is simply NOT the
            # state transition the declared game contract requires.
            return (
                'local args = actionArgs\n'
                'local state = services.PlayerDataManager.GetState(player, "Wrong")\n'
                'if not state then return false end\n'
                'state.unrelated = (state.unrelated or 0) + 1\n'
                'return true'
            )
        def complete_json(self, prompt, **kwargs):
            return {"body": self.complete(prompt)}
    wrong = WrongCoder()
    assert try_scaffolded_server(
        server, proposal, wrong, LuauStaticAnalyzer()) is None
    assert len(wrong.last_scaffold_attempts) == 3
    assert any(
        "does not reference declared state keys" in diagnostic
        for attempt in wrong.last_scaffold_attempts
        for diagnostic in attempt["diagnostics"]
    )
