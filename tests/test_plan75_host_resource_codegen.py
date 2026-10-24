"""General resource-only world-action compilation, no hand-coded game prompt.

A host transport-only selection/quantity form is not a valid permission to
pick a client-controlled mining yield. For a genuinely source-requested,
single-action resource harvester, replace only that generic transport with
server-chosen nearby node input and deterministic first-party gameplay.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.host_mining_contract import (
    ensure_mining_world_contract,
    _is_named_mining_service,
)
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.generation_scope import generation_scope


def proposal(*, description="Server validates collection of resource deposits.",
             profile="transport_only"):
    server = NS(
        name="ResourceGather4533281Server", module_id="dyn_general_gather",
        description=description, kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ResourceGather4533281Server.luau",
    )
    client = NS(
        name="ResourceGather4533281Client", module_id="dyn_general_gather_ui",
        description="Host receives user input for resource gathering",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/ResourceGather4533281Client.client.luau",
    )
    remote = "ResourceGather4533281Action"
    typed = {
        "contract": {
            "inputs": [
                {"id": "selection", "label": "Item ID", "type": "text"},
                {"id": "quantity", "label": "Requested quantity",
                 "type": "integer", "min": 1, "max": 10000},
            ],
            "target": {"kind": "none"}, "state_changes": [],
        },
        "server": server.name, "client": client.name,
        "transport_only": profile == "transport_only",
        "world_entities": ["ResourceBalance45332811"],
        "world_name": None,
    }
    design = {
        "world_objects": [{
            "name": "ResourceBalance45332811", "class": "Part",
            "position": [24.0, 2.0, 24.0], "size": [4.0, 4.0, 4.0],
        }],
        "module_world_objects": {
            server.module_id: ["ResourceBalance45332811"],
            client.module_id: ["ResourceBalance45332811"],
        },
        "host_actions": {
            remote: {"service": server.name, "kind": "RemoteFunction",
                     "max_args": 1},
        },
        "host_typed_actions": {remote: typed},
        "host_world_actions": {}, "module_remotes": {
            server.module_id: [remote], client.module_id: [remote],
        },
        "host_client_actions": {},
        "host_action_choices": {},
        "host_world_motion": {},
        "module_behaviors": {}, "module_facets": {},
    }
    p = NS(
        requested_prompt="Players harvest materials from a resource site",
        game_design={"dynamic_design": design},
        modules=[server, client],
    )
    return p, server, client, remote


def test_numeric_host_generated_suffix_not_part_of_mechanic_name():
    assert _is_named_mining_service(
        "ResourceGather4533281Server",
        "Server validates collection of resource deposits.",
        "Mine resources in a resource site",
    )
    assert not _is_named_mining_service(
        "ResourceShop4533281Server",
        "Server sells resource bundles",
        "Mine resources in a resource site",
    )


def test_host_owns_resource_world_and_rebases_only_transport():
    p, server, client, route = proposal()
    changes = ensure_mining_world_contract(p)
    assert len(changes) == 1
    assert changes[0]["transport_rebased"] is True
    node = changes[0]["resource_node"]
    assert node.startswith("ResourceNode")
    design = p.game_design["dynamic_design"]
    assert design["host_actions"][route]["max_args"] == 0
    assert route not in design["host_typed_actions"]
    assert node in design["module_world_objects"][server.module_id]
    assert node in design["module_world_objects"][client.module_id]
    server_code = render_host_mining(server, p)
    client_code = render_host_mining(client, p)
    assert server_code is not None
    assert "GetState(player" in server_code
    assert "SetState(" not in server_code
    assert "handleAction(player, services" in server_code
    assert "actionArgs.fieldId" not in server_code
    assert "InvokeServer()" in client_code
    assert "InvokeServer(target)" not in client_code
    assert "RMMInventory" in server_code


def test_input_contract_with_genuine_effects_is_not_rebased():
    p, server, client, route = proposal(profile="effectful")
    ensure_mining_world_contract(p)
    design = p.game_design["dynamic_design"]
    assert design["host_actions"][route]["max_args"] == 1
    assert route in design["host_typed_actions"]


def test_unrelated_generated_module_remains_unmodified():
    p, server, client, route = proposal(
        description="Server creates an interactive decorative museum plaque",
    )
    p.requested_prompt = "Design an interactive museum"
    assert ensure_mining_world_contract(p) == []
    assert route in p.game_design["dynamic_design"]["host_typed_actions"]
    assert p.game_design["dynamic_design"]["host_actions"][route]["max_args"] == 1


def test_second_preflight_is_idempotent():
    p, server, client, route = proposal()
    first = ensure_mining_world_contract(p)
    second = ensure_mining_world_contract(p)
    assert len(first) == 1
    assert second == []
    assert len(p.game_design["dynamic_design"]["world_objects"]) == 2
