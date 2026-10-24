"""Report 43: host-generated Luau was rejected by the static audit.

Ensure source wiring recognizes timed WaitForChild calls; movement contracts
can be safely extended by host identity metadata; UI PlaceholderText is not a
stub. All negative examples must still fail.
"""
from types import SimpleNamespace as Obj

from roblox_mod_ai.dynamic_wiring import _variables, inspect_dynamic_remote_wiring
from roblox_mod_ai.implementation_blueprint import _matches_source_motion
from roblox_mod_ai.quality_gates import _contains_source_placeholder


def test_timed_remote_name_with_nested_wait_and_timeout():
    src = (
        'local remote = game:GetService("ReplicatedStorage")'
        ':WaitForChild("Remotes", 20):WaitForChild("BuildShipAction", 20)\n'
        'remote:InvokeServer("build")\n'
    )
    assert _variables(src, "BuildShipAction") == ["remote"]
    assert _variables(src, "Remotes") == []
    assert _variables(src, "OtherAction") == []


def test_local_remote_timeout_and_exact_name():
    src = (
        'local folder = Storage:WaitForChild("Remotes", 20)\n'
        'local remote = folder:WaitForChild("LaunchAction", 20)\n'
        'remote:InvokeServer("launch")\n'
    )
    assert _variables(src, "LaunchAction") == ["remote"]
    assert _variables(src, "LaunchAct") == []


def _minimal_remote_plan(client_code):
    client = Obj(module_id="dyn_client", name="ShipClient",
                 file_path="src/client/ShipClient.client.luau",
                 code=client_code)
    server = Obj(module_id="dyn_server", name="ShipServer",
                 file_path="src/server/ShipServer.luau",
                 code="local Service={}\nfunction Service.handleAction(player,services,...) "
                      "return {success=true} end\nreturn Service")
    gateway = Obj(module_id="mod_dynamic_server_bootstrap",
                  name="RMMServerBootstrap",
                  file_path="src/server/RMMServerBootstrap.server.luau",
                  code='local remote = remotes:WaitForChild("ShipAction", 20)\n'
                       'remote.OnServerInvoke = function(...)\n'
                       'return service.handleAction(player, services, ...)\nend')
    design = {"remotes": {"ShipAction": "RemoteFunction"},
              "host_actions": {"ShipAction": {"service": "ShipServer",
                                              "kind": "RemoteFunction"}},
              "module_remotes": {
                  "dyn_client": ["ShipAction"],
                  "dyn_server": ["ShipAction"]}}
    return Obj(modules=[client, server, gateway],
               game_design={"dynamic_design": design})


def test_real_timed_client_invocation_and_host_gateway_are_connected():
    proposal = _minimal_remote_plan(
        'local folder=Storage:WaitForChild("Remotes",20)\n'
        'local remote=folder:WaitForChild("ShipAction",20)\n'
        'return remote:InvokeServer("launch")\n'
    )
    result = inspect_dynamic_remote_wiring(proposal)
    assert result["passed"], [x for x in result["checks"] if not x["passed"]]


def test_declared_owner_without_real_remote_invocation_still_rejected():
    proposal = _minimal_remote_plan(
        'local remote=Storage:WaitForChild("Remotes",20)'
        ':WaitForChild("ShipAction",20)\n'
        'local text="remote:InvokeServer()"\n'
    )
    result = inspect_dynamic_remote_wiring(proposal)
    assert not result["passed"]
    assert any(x["id"] == "wiring.owner.ShipClient.ShipAction"
               and not x["passed"] for x in result["checks"])


def test_host_motion_identity_enrichment_does_not_erase_source_obligation():
    required = {
        "kind": "vehicle_world_transition",
        "actor": "owned spacecraft / vehicle",
        "destination": "playable space / orbit",
        "occupant_rule": "players remain aboard the vehicle",
        "effect": "server moves the vehicle and its occupants to the destination",
    }
    enriched = dict(required, builder_module_id="dyn_builder",
                    arrival_world_name="OrbitArrival_1",
                    actor_identity_source="unique_host_materialized_builder_root")
    assert _matches_source_motion(enriched, required)
    assert not _matches_source_motion(
        dict(enriched, effect="server marks launched flag only"), required)
    assert not _matches_source_motion(
        {k:v for k,v in enriched.items() if k != "occupant_rule"}, required)
    assert not _matches_source_motion(None, required)


def test_actual_placeholder_tokens_rejected_but_roblox_ui_property_allowed():
    actual_ui = (
        '-- The editor has a placeholder hint\n'
        'local box=Instance.new("TextBox")\n'
        'box.PlaceholderText="Enter player name"\n'
        'local remote=Storage:WaitForChild("Remotes",20)'
        ':WaitForChild("TradeAction",20)\n'
        'remote:InvokeServer("offer")\n'
    )
    assert not _contains_source_placeholder(actual_ui)
    assert _contains_source_placeholder('local TODO = true\n')
    assert _contains_source_placeholder('placeholder()\n')
    assert _contains_source_placeholder('loadstring("bad")\n')
    assert not _contains_source_placeholder('print("TODO")\n')
