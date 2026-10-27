"""Genre-independent multi-effect compilation regression.

The small planner supplies only a validated, data-only transaction contract.
The host compiles the atomic server handler, not custom Luau from a prompt.
"""
from copy import deepcopy

import pytest

from roblox_mod_ai.host_atomic_effect import render_atomic_server
from roblox_mod_ai.generation_scope import generation_scope, assert_prompt_invariant_routing
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


def _candidate():
    remote = "ExchangeResourcesAction"
    server = RobloxModuleSpec(
        module_id="dyn_exchange_server",
        name="ExchangeResourcesServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ExchangeResourcesServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Transfer resources and credits in a single state transaction.",
    )
    client = RobloxModuleSpec(
        module_id="dyn_exchange_client",
        name="ExchangeResourcesClient",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ExchangeResourcesClient.client.luau",
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        description="Send a typed quantity request to the server.",
    )
    persistence = RobloxModuleSpec(
        module_id="mod_player_data",
        name="PlayerDataManager",
        kind=ModuleKind.DATA_STORE,
        file_path="src/server/PlayerDataManager.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Host-managed persistent state",
    )
    contract = {
        "inputs": [{"id": "quantity", "label": "Quantity",
                    "type": "integer", "min": 1, "max": 12}],
        "target": {"kind": "none"},
        "state_changes": [
            {"scope": "player", "key": "Progress.ore", "operation": "decrement"},
            {"scope": "player", "key": "Progress.credits", "operation": "increment"},
        ],
    }
    program = {
        "schema": "rmm/transaction-effect-v1", "namespace": "Progress",
        "changes": [
            {"field": "ore", "operation": "decrement",
             "amount": {"input": "quantity"}, "limit": 1000},
            {"field": "credits", "operation": "increment",
             "amount": {"constant": 5}, "limit": 10000},
        ],
    }
    design = {
        "host_actions": {remote: {"service": server.name, "kind": "RemoteFunction",
                                  "max_args": 1}},
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {server.module_id: [remote], client.module_id: [remote]},
        "host_typed_actions": {remote: {
            "server": server.name, "client": client.name,
            "contract": contract, "world_entities": [],
            "transport_only": False,
        }},
        "host_executable_actions": {remote: program},
        "world_objects": [], "module_world_objects": {},
    }
    proposal = RobloxProposal(
        game_title="ContractCompiled", description="",
        requested_prompt="Any arbitrary resource transaction game",
        game_design={"dynamic_design": design},
        modules=[persistence, server, client],
    )
    return proposal, server, remote


def test_host_compiles_all_preconditions_before_mutating_any_fields():
    p, server, _ = _candidate()
    code = render_atomic_server(server, p)
    assert code is not None
    assert "local old1=state.ore" in code
    assert "local old2=state.credits" in code
    assert "local next1=old1-amount1" in code
    assert "local next2=old2+amount2" in code
    assert code.index("local next2=") < code.index("state.ore=next1")
    assert code.index("state.ore=next1") < code.index("state.credits=next2")
    assert 'GetState(player,"Progress")' in code
    assert "\\n" not in code
    diagnostics = LuauStaticAnalyzer().analyze_source(code, server.file_path)
    assert not [d for d in diagnostics if d.severity == "ERROR"]


def test_contract_compilation_ignores_raw_prompt():
    p, server, _ = _candidate()
    code = render_atomic_server(server, p)
    p.requested_prompt = "뉴욕을 관광하는 퀘스트 게임"
    assert render_atomic_server(server, p) == code
    report = generation_scope(p)
    assert next(row["strategy"] for row in report["modules"]
                if row["module_id"] == server.module_id) == "host_atomic_effect"
    assert_prompt_invariant_routing(p, original_scope=report)


@pytest.mark.parametrize("corruption", ["wrong_namespace", "wrong_effect", "duplicate", "bad_amount", "bad_remote"])
def test_incompatible_transaction_fails_closed(corruption):
    p, server, remote = _candidate()
    design = p.game_design["dynamic_design"]
    program = design["host_executable_actions"][remote]
    if corruption == "wrong_namespace":
        program["namespace"] = "Unrelated"
    elif corruption == "wrong_effect":
        program["changes"][1]["operation"] = "decrement"
    elif corruption == "duplicate":
        program["changes"][1]["field"] = "ore"
    elif corruption == "bad_amount":
        program["changes"][0]["amount"] = {"input": "never_declared"}
    else:
        design["host_actions"][remote]["kind"] = "RemoteEvent"
    with pytest.raises(ValueError, match="TRANSACTION_"):
        render_atomic_server(server, p)


def test_transaction_does_not_fabricate_program():
    p, server, remote = _candidate()
    p.game_design["dynamic_design"]["host_executable_actions"].pop(remote)
    assert render_atomic_server(server, p) is None


def test_compact_numeric_planner_builds_same_contract_without_genre_names():
    from roblox_mod_ai.host_effect_ir_planner import try_plan_effect_data
    class Router:
        supports_declarative_effect_program = True
        def complete_json(self, prompt, **kwargs):
            assert "source" in prompt and "behavior" in prompt
            assert kwargs["json_schema"]["required"]
            return {
                "supported": True,
                "uses_quantity": True,
                "quantity_max": 10,
                "changes": [
                    {"field": "ore", "operation": "decrement",
                     "source": "quantity", "constant": 0, "multiplier": 1,
                     "limit": 1000},
                    {"field": "credits", "operation": "increment",
                     "source": "quantity", "constant": 0, "multiplier": 2,
                     "limit": 10000},
                ],
            }
    system = {"input_mode": "custom", "interaction": "request_response",
              "server_behavior": "A validated player action transfers owned counts.",
              "observable_result": "Two owned counts update together.",
              "world_entities": []}
    result = try_plan_effect_data(
        Router(), system, [{"statement": "Change two numeric resources"}],
    )
    assert result is not None
    contract, program = result
    assert len(contract["state_changes"]) == 2
    assert program["changes"][1]["amount"] == {
        "input": "quantity", "multiplier": 2,
    }


def test_ir_planner_rejects_quantity_overflow_and_does_not_guess():
    from roblox_mod_ai.host_effect_ir_planner import compile_effect_data, try_plan_effect_data
    bad = {
        "supported": True,
        "uses_quantity": True, "quantity_max": 1000,
        "changes": [{"field": "count", "operation": "increment",
                     "source": "quantity", "constant": 0,
                     "multiplier": 100, "limit": 100}],
    }
    with pytest.raises(ValueError, match="DECLARATIVE_EFFECT_UNBOUNDED_QUANTITY"):
        compile_effect_data(bad)
    class Unsupported:
        supports_declarative_effect_program = True
        def complete_json(self, *_args, **_kwargs):
            return dict(bad, supported=False)
    assert try_plan_effect_data(Unsupported(), {
        "input_mode": "custom", "interaction": "request_response",
        "world_entities": [],
        "server_behavior": "Complex game action", "observable_result": "Outcome",
    }, [{"statement": "Complex requested game action"}]) is None


def test_generic_generator_uses_transaction_not_model_written_module():
    from roblox_mod_ai.code_generator import LuauCodeGenerator
    class ForbiddenModel:
        def complete(self, *_args, **_kwargs):
            raise AssertionError("Typed executable transaction must not use coder")
        def complete_json(self, *_args, **_kwargs):
            raise AssertionError("Typed executable transaction must not use coder")
    p, server, _ = _candidate()
    output = LuauCodeGenerator(ForbiddenModel()).generate_module_code(server, p)
    assert output == render_atomic_server(server, p)
    assert "state.ore=next1" in output


def test_semantic_architecture_preserves_executable_effect_ir():
    from roblox_mod_ai.host_architecture import expand_semantic_facet
    program = {
        "schema": "rmm/transaction-effect-v1",
        "namespace": "RMMGameplayState",
        "changes": [
            {"field": "points", "operation": "increment",
             "amount": {"constant": 3}, "limit": 9999},
        ],
    }
    raw = {"systems": [{
        "name": "GainPoints",
        "server_behavior": (
            "The server validates the authenticated player action, then "
            "increases the player's persistent points by three within a "
            "strict checked limit."
        ),
        "client_behavior": (
            "A player clicks the button to request the points increase "
            "and sees the confirmed updated points count."
        ),
        "observable_result": (
            "The player sees their saved points increase by three."
        ),
        "interaction": "request_response", "input_mode": "custom",
        "world_entities": [],
        "action_contract": {
            "inputs": [], "target": {"kind": "none"},
            "state_changes": [{
                "scope": "player", "key": "RMMGameplayState.points",
                "operation": "increment",
            }],
        },
        "effect_program": program,
    }]}
    converted = expand_semantic_facet(
        raw, facet_id="intent-points", requirement_ids=["req-001"],
        source_requirements=[{"id": "req-001", "statement": "Gain points"}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
    )
    remote, saved = next(iter(converted["_host_executable_actions"].items()))
    assert saved == program
    assert converted["_host_typed_actions"][remote]["transport_only"] is False


def test_noop_increment_cannot_be_declared_as_finished_gameplay():
    from roblox_mod_ai.host_effect_ir_planner import compile_effect_data
    p, server, remote = _candidate()
    program = p.game_design["dynamic_design"]["host_executable_actions"][remote]
    program["changes"][1]["amount"] = {"constant": 0}
    with pytest.raises(ValueError, match="TRANSACTION_INVALID_CONSTANT"):
        render_atomic_server(server, p)
    with pytest.raises(ValueError, match="DECLARATIVE_EFFECT_ZERO_MUTATION"):
        compile_effect_data({
            "supported": True,
            "uses_quantity": False,
            "quantity_max": 1,
            "changes": [{
                "field": "score", "operation": "increment",
                "source": "constant", "constant": 0,
                "multiplier": 1, "limit": 100,
            }],
        })


def test_atomic_effect_rejects_zero_increment_as_fake_gameplay():
    p, server, remote = _candidate()
    design = p.game_design["dynamic_design"]
    design["host_typed_actions"][remote]["contract"]["state_changes"] = [
        {"scope": "player", "key": "Progress.credits",
         "operation": "increment"},
    ]
    design["host_executable_actions"][remote] = {
        "schema": "rmm/atomic-effect-v1",
        "namespace": "Progress", "field": "credits",
        "operation": "increment", "amount": {"constant": 0},
        "limit": 1000,
    }
    with pytest.raises(ValueError, match="EXECUTABLE_ACTION_INVALID_CONSTANT"):
        render_atomic_server(server, p)


def test_numeric_compiler_requires_positive_quantities_for_arithmetic():
    import copy
    p, server, remote = _candidate()
    design = p.game_design["dynamic_design"]
    # Zero is a valid wire integer, but not a meaningful increment/decrement.
    design["host_typed_actions"][remote]["contract"]["inputs"][0]["min"] = 0
    with pytest.raises(ValueError, match="TRANSACTION_UNVALIDATED_AMOUNT"):
        render_atomic_server(server, p)

    row = design["host_typed_actions"][remote]["contract"]["state_changes"][0]
    design["host_typed_actions"][remote]["contract"]["state_changes"] = [row]
    design["host_executable_actions"][remote] = {
        "schema": "rmm/atomic-effect-v1",
        "namespace": "Progress", "field": "ore", "operation": "decrement",
        "amount": {"input": "quantity"}, "limit": 1000,
    }
    with pytest.raises(ValueError, match="EXECUTABLE_ACTION_INPUT_NOT_VALIDATED"):
        render_atomic_server(server, p)
