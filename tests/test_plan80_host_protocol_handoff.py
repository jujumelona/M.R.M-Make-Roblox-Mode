"""Restore first-party host implementation priority for complete protocol pairs.

The source-owned design may have a generic transport_only stub, but that does
not authorize skipping a more strictly matched and fully host-authored client
and server. Handoff is atomic, preserves Remote ownership, and never erases
a typed action contract with genuine declared state changes.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols


def sample(*, transport_only=True, effects=None,
           server_strategy="host_declarative_general_upgrades",
           client_strategy="host_declarative_general_upgrades"):
    server = NS(name="AnyActionServer", module_id="dyn_srv",
                file_path="src/server/AnyActionServer.luau")
    client = NS(name="AnyActionClient", module_id="dyn_cli",
                file_path="src/client/AnyActionClient.client.luau")
    remote = "AnyActionRoute"
    typed_spec = {
        "server": server.name, "client": client.name,
        "transport_only": transport_only,
        "contract": {
            "inputs": [{"id": "selection", "label": "Selection", "type": "text"}],
            "target": {"kind": "none"},
            "state_changes": [] if effects is None else effects,
        },
    }
    design = {
        "host_typed_actions": {remote: typed_spec},
        "host_actions": {
            remote: {"service": server.name, "kind": "RemoteFunction",
                     "max_args": 1}
        },
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {
            server.module_id: [remote], client.module_id: [remote],
        },
    }
    p = NS(modules=[server, client],
           game_design={"dynamic_design": design})
    scope = {"modules": [
        {"name": server.name, "strategy": server_strategy},
        {"name": client.name, "strategy": client_strategy},
    ]}
    return p, scope, remote


def test_matching_authoritative_pair_replaces_generic_transport():
    p, scope, remote = sample()
    changes = rebase_complete_host_protocols(p, scope)
    assert len(changes) == 1
    assert changes[0]["protocol"] == "host_declarative_general_upgrades"
    design = p.game_design["dynamic_design"]
    assert remote not in design["host_typed_actions"]
    assert design["host_actions"][remote]["service"] == "AnyActionServer"
    assert design["host_actions"][remote]["kind"] == "RemoteFunction"
    assert design["module_remotes"]["dyn_srv"] == [remote]
    assert design["module_remotes"]["dyn_cli"] == [remote]
    assert rebase_complete_host_protocols(p, scope) == []


def test_no_handoff_without_both_client_and_server_host_implementations():
    for other_strategy in ("bounded_client_ui", "host_declarative_catalog"):
        p, scope, remote = sample(client_strategy=other_strategy)
        assert rebase_complete_host_protocols(p, scope) == []
        assert remote in p.game_design["dynamic_design"]["host_typed_actions"]


def test_unrecognized_or_model_owned_server_never_takes_over():
    for kind in ("bounded_server_action", "whole_file_model_legacy"):
        p, scope, remote = sample(server_strategy=kind, client_strategy=kind)
        assert rebase_complete_host_protocols(p, scope) == []
        assert remote in p.game_design["dynamic_design"]["host_typed_actions"]


def test_real_effect_schema_must_never_be_erased():
    p, scope, remote = sample(effects=[
        {"scope": "player", "key": "ownedEffect", "operation": "increment"}
    ])
    assert rebase_complete_host_protocols(p, scope) == []
    assert p.game_design["dynamic_design"]["host_typed_actions"][remote][
        "contract"]["state_changes"]


def test_non_transport_owned_schema_must_never_be_erased():
    p, scope, remote = sample(transport_only=False)
    assert rebase_complete_host_protocols(p, scope) == []
    assert remote in p.game_design["dynamic_design"]["host_typed_actions"]


def test_miswired_remote_is_not_mutated():
    p, scope, remote = sample()
    p.game_design["dynamic_design"]["module_remotes"]["dyn_cli"] = ["Wrong"]
    assert rebase_complete_host_protocols(p, scope) == []
    assert remote in p.game_design["dynamic_design"]["host_typed_actions"]
