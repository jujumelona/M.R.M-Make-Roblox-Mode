"""Connectivity must be real source code, not comments, strings or unused remote names."""
from roblox_mod_ai.dynamic_wiring import inspect_dynamic_remote_wiring
from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec

def _check(server: str, client: str, kind: str = "RemoteEvent"):
    modules=[
        RobloxModuleSpec(module_id="dyn_server",name="ActionServer",kind="server_script",
                         roblox_service="ServerScriptService",
                         file_path="src/server/ActionServer.server.luau",code=server),
        RobloxModuleSpec(module_id="dyn_client",name="ActionClient",kind="client_script",
                         roblox_service="StarterPlayer.StarterPlayerScripts",
                         file_path="src/client/ActionClient.client.luau",code=client),
    ]
    proposal=RobloxProposal(requested_prompt="test",game_title="Game",description="",
        game_design={"dynamic_design":{"remotes":{"ActionSignal":kind}}},modules=modules)
    result=inspect_dynamic_remote_wiring(proposal)
    assert len(result["checks"])==1
    return result["passed"]

def test_remote_client_request_and_server_receiver():
    assert _check(
        'local remote=game.ReplicatedStorage.Remotes:WaitForChild("ActionSignal")\nremote.OnServerEvent:Connect(function(player) end)',
        'local remote=game.ReplicatedStorage.Remotes:WaitForChild("ActionSignal")\nremote:FireServer()'
    )

def test_remote_broadcast_server_to_client_is_valid():
    assert _check(
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote:FireAllClients()',
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote.OnClientEvent:Connect(function() end)'
    )

def test_remote_function_request_response():
    assert _check(
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote.OnServerInvoke=function(player) return true end',
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nprint(remote:InvokeServer())',
        kind="RemoteFunction"
    )

def test_wrong_direction_does_not_pass():
    assert not _check(
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote:FireClient(player)',
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote:FireServer()'
    )

def test_commented_sender_does_not_pass():
    assert not _check(
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote.OnServerEvent:Connect(function() end)',
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\n-- remote:FireServer()'
    )

def test_string_containing_sender_does_not_pass():
    assert not _check(
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote.OnServerEvent:Connect(function() end)',
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nprint("remote:FireServer()")'
    )

def test_unbound_other_remote_does_not_pass():
    assert not _check(
        'local remote=game.ReplicatedStorage.Remotes.OtherRemote\nremote.OnServerEvent:Connect(function() end)',
        'local remote=game.ReplicatedStorage.Remotes.ActionSignal\nremote:FireServer()'
    )
