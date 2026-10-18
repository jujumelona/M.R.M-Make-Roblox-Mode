"""Host-built Roblox network gateway; 9B does not author transport boilerplate."""
from __future__ import annotations

import pytest

from roblox_mod_ai.dynamic_architect import _clean_model_json
from roblox_mod_ai.host_architecture import expand_semantic_facet
from roblox_mod_ai.spec import RobloxProposal
from roblox_mod_ai.server_modules import (
    normalize_dynamic_server_modules, render_dynamic_server_bootstrap,
    module_bootstrap_contract,
)
from roblox_mod_ai.dynamic_wiring import inspect_dynamic_remote_wiring
from roblox_mod_ai.server_interface_audit import inspect_dynamic_server_interfaces


def _plan(interaction="event"):
    response = expand_semantic_facet({
        "systems": [{
            "name": "MineOre",
            "server_behavior": "Server checks valid player proximity and grants only verified ore to inventory.",
            "client_behavior": "Show the mining button and update ore counter using server results.",
            "interaction": interaction,
            "observable_result": "Mining nearby ore grants validated inventory resources to a player.",
            "world_entities": ["OreNode"],
        }]},
        facet_id="intent-mining", requirement_ids=["req-001"],
        source_requirements=[{"id": "req-001", "statement": "Mine ore"}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set())
    ledger = {
        "requirements": [{"id": "req-001", "statement": "Mine ore"}],
        "facets": [{"id": "intent-mining", "requirements": ["req-001"],
                    "source_span": "Mine ore"}], "original_prompt": "Mine ore",
    }
    design = _clean_model_json(response, ledger, set())
    target = next(m for m in design["modules"] if m.file_path.startswith("src/server/"))
    remote_name = next(iter(design["remotes"]))
    design["host_actions"] = {
        remote_name: {"service": target.name, "kind": design["remotes"][remote_name]}}
    runtime_design = {k: v for k, v in design.items() if k != "modules"}
    proposal = RobloxProposal(
        requested_prompt="Mine ore", game_title="Mining", description="",
        game_design={"dynamic_design": runtime_design},
        modules=list(design["modules"]),
    )
    normalize_dynamic_server_modules(proposal)
    server = next(m for m in proposal.modules if m.name == target.name)
    client = next(m for m in proposal.modules if m.file_path.endswith(".client.luau"))
    bootstrap = next(m for m in proposal.modules
                     if m.name == "RMMServerBootstrap")
    server.code = (
        "--!strict\nlocal Mining = {}\n"
        "function Mining.start(services)\n"
        "    assert(services ~= nil)\n"
        "end\n"
        "function Mining.handleAction(player, services, ...)\n"
        "    if player.Parent ~= game:GetService('Players') then return false end\n"
        "    return true\n"
        "end\nreturn Mining\n"
    )
    verb = "FireServer()" if interaction == "event" else "InvokeServer()"
    client.code = (
        "--!strict\n"
        f"local r = game:GetService('ReplicatedStorage'):WaitForChild('Remotes'):WaitForChild('{remote_name}')\n"
        f"r:{verb}\n"
    )
    bootstrap.code = render_dynamic_server_bootstrap(proposal)
    return proposal, server, client, bootstrap, remote_name


@pytest.mark.parametrize("interaction,method", [
    ("event", "OnServerEvent:Connect"),
    ("request_response", "OnServerInvoke ="),
])
def test_host_server_gateway_owns_roblox_remote_and_per_player_rate_limit(interaction, method):
    plan, server, client, bootstrap, remote_name = _plan(interaction)
    assert method in bootstrap.code
    assert "typeof(player)" in bootstrap.code
    assert "player.Parent ~= Players" in bootstrap.code
    assert "os.clock()" in bootstrap.code
    assert "now - previous < 0.08" in bootstrap.code
    assert "service.handleAction(player, services, ...)" in bootstrap.code
    assert remote_name in bootstrap.code
    assert "OnServerEvent" not in server.code
    assert "OnServerInvoke" not in server.code
    assert "HOST-OWNED NETWORK" in module_bootstrap_contract(server, plan)
    wiring = inspect_dynamic_remote_wiring(plan)
    assert wiring["passed"], wiring
    exports = inspect_dynamic_server_interfaces(plan)
    assert exports["passed"], exports
    assert any(c["id"] == "wiring.hostGateway." + remote_name
               and c["passed"] for c in wiring["checks"])


def test_malformed_domain_module_cannot_be_masked_by_host_gateway():
    plan, server, client, bootstrap, remote = _plan()
    server.code = server.code.replace("handleAction", "inventedHandler")
    assert not inspect_dynamic_remote_wiring(plan)["passed"]
    contract = inspect_dynamic_server_interfaces(plan)
    assert any(c["id"] == "service.handleAction." + server.name
               and not c["passed"] for c in contract["checks"])


def test_model_cannot_duplicate_host_remote_listener():
    plan, server, client, bootstrap, remote = _plan()
    server.code += "local remote = game.ReplicatedStorage.Remotes.RequestMine\n" + (
        "remote.OnServerEvent:Connect(function(player) end)\n"
    )
    issues = inspect_dynamic_server_interfaces(plan)
    assert any(c["id"] == "service.hostGatewayNoManualBinding." + server.name
               and not c["passed"] for c in issues["checks"])


def test_tampered_host_route_rejected_before_build():
    plan, server, client, bootstrap, remote = _plan()
    plan.game_design["dynamic_design"]["host_actions"][remote]["kind"] = "RemoteFunction"
    with pytest.raises(ValueError, match="invalid service/Remote class"):
        render_dynamic_server_bootstrap(plan)
