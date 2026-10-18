"""CI negative suite for failure classes missed by basic endpoint-presence tests.

A passing unrelated Remote handler must not hide a missing declared owner.
Even when both valid endpoints exist, an invalid Roblox transport method must
fail the same production static quality gate.
"""
from __future__ import annotations

import pytest

from roblox_mod_ai.dynamic_wiring import inspect_dynamic_remote_wiring
from roblox_mod_ai.quality_gates import acceptance_obligations
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def _plan(kind="RemoteEvent"):
    server = RobloxModuleSpec(
        module_id="dyn_server", name="MiningServer",
        kind="server_module", roblox_service="ServerScriptService",
        file_path="src/server/MiningServer.luau",
        code=(
            "--!strict\nlocal Mine = {}\n"
            'local remote = game.ReplicatedStorage.Remotes:WaitForChild("RequestMine")\n'
            "function Mine.start(services)\n"
            + ("    remote.OnServerEvent:Connect(function(player) end)\n"
               if kind == "RemoteEvent" else
               "    remote.OnServerInvoke = function(player) return true end\n")
            + "end\nreturn Mine\n"
        ),
    )
    client = RobloxModuleSpec(
        module_id="dyn_client", name="MiningClient",
        kind="client_script", roblox_service="StarterPlayer.StarterPlayerScripts",
        file_path="src/client/MiningClient.client.luau",
        code=(
            "--!strict\n"
            'local remote = game.ReplicatedStorage.Remotes:WaitForChild("RequestMine")\n'
            + ("remote:FireServer()\n" if kind == "RemoteEvent" else
               "local result = remote:InvokeServer()\nprint(result)\n")
        ),
    )
    return RobloxProposal(
        requested_prompt="mine ore", game_title="MiningGame", description="",
        modules=[server, client],
        game_design={"dynamic_design": {
            "remotes": {"RequestMine": kind},
            "module_remotes": {
                "dyn_server": ["RequestMine"], "dyn_client": ["RequestMine"],
            },
            "source_reuse": "none_unless_validated",
            "module_requirements": {},
            "acceptance": {},
        }},
    )


@pytest.mark.parametrize("kind", ["RemoteEvent", "RemoteFunction"])
def test_normal_transport_and_exact_owners_are_accepted(kind):
    plan = _plan(kind)
    report = inspect_dynamic_remote_wiring(plan)
    assert report["passed"], report
    assert len([c for c in report["checks"] if c["id"].startswith("wiring.owner.")]) == 2


def test_unrelated_valid_server_handler_cannot_mask_claimed_owner_without_handler():
    plan = _plan()
    plan.modules[0].code = plan.modules[0].code.replace(
        "remote.OnServerEvent:Connect(function(player) end)",
        "print(remote.Name)"
    )
    other = RobloxModuleSpec(
        module_id="dyn_other", name="UnrelatedServer",
        kind="server_module", roblox_service="ServerScriptService",
        file_path="src/server/UnrelatedServer.luau",
        code='local r = game.ReplicatedStorage.Remotes:WaitForChild("RequestMine")\n'
             'r.OnServerEvent:Connect(function(player) end)\n',
    )
    plan.modules.append(other)
    report = inspect_dynamic_remote_wiring(plan)
    overall = next(c for c in report["checks"] if c["id"] == "wiring.RequestMine")
    assert overall["passed"], report
    owner = next(c for c in report["checks"]
                 if c["id"] == "wiring.owner.MiningServer.RequestMine")
    assert not owner["passed"]
    assert not report["passed"]


@pytest.mark.parametrize("kind,side,wrong_method", [
    ("RemoteEvent", "client", "InvokeServer"),
    ("RemoteEvent", "server", "OnServerInvoke"),
    ("RemoteEvent", "server", "FireServer"),
    ("RemoteEvent", "client", "OnServerEvent"),
    ("RemoteFunction", "client", "FireServer"),
    ("RemoteFunction", "server", "OnServerEvent"),
    ("RemoteFunction", "server", "FireAllClients"),
    ("RemoteFunction", "client", "OnClientEvent"),
])
def test_transport_fault_is_rejected_even_if_good_endpoints_also_exist(
        kind, side, wrong_method, tmp_path):
    plan = _plan(kind)
    module = plan.modules[0 if side == "server" else 1]
    suffix = " = function() end" if wrong_method.endswith("Invoke") else (
        ":Connect(function() end)" if wrong_method.startswith("On") else "()"
    )
    if wrong_method.startswith("On"):
        invalid = "remote." + wrong_method + suffix
    else:
        invalid = "remote:" + wrong_method + suffix
    module.code += invalid + "\n"
    report = inspect_dynamic_remote_wiring(plan)
    assert not report["passed"], report
    assert any(c["id"] == "wiring.method." + module.name + ".RequestMine"
               and not c["passed"] for c in report["checks"])
    gate = acceptance_obligations(plan, tmp_path)
    assert any(c["id"] == "wiring.method." + module.name + ".RequestMine"
               and not c["passed"] for c in gate["checks"])


def test_quoted_and_commented_invalid_transport_methods_are_not_real_calls():
    plan = _plan()
    plan.modules[1].code += (
        '-- remote:InvokeServer()\n'
        'print("remote:InvokeServer()")\n'
    )
    assert inspect_dynamic_remote_wiring(plan)["passed"]
