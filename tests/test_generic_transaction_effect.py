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
