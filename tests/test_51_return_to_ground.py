"""51: RMM orbit visit must be reversible on the same player-owned ship.

This covers server contracts and generated Luau text, not Roblox Studio physics.
"""
from tests.test_plan83_ordered_assembly_launch import sample
from roblox_mod_ai.host_vehicle_departure import render_departure


def test_can_return_to_previously_recorded_launch_dock():
    proposal, _builder, _client, server, client = sample()
    lua = render_departure(server,proposal)
    ui = render_departure(client,proposal)
    assert lua and ui
    for token in (
        'local homeDock={}',
        'homeDock[player]=start',
        'target=homeDock[player]',
        'if action=="return" then',
        'reason="return_destination_missing"',
        'reason="not_in_orbit"',
        'if inFlight[player] then',
        'seat.Occupant~=humanoid',
        'vehicle:GetAttribute("OwnerUserId")~=player.UserId',
        'start:Lerp(target,alpha)',
        'if completed and action=="return" then homeDock[player]=nil end',
        'action=="return" and "landed" or "arrived"',
    ):
        assert token in lua, token
    assert lua.index('if action=="return" then') < lua.index('recent[player]=now')
    assert 'homeDock[player]=nil' in lua
    assert "Return to ground" in ui
    assert 'remote:InvokeServer(action)' in ui
    assert 'state=="arrived" and "return" or "launch"' in ui
    assert 'Instance.new("TextButton")' in ui
    assert ui.count('Instance.new("TextButton")')==1 # RMMHUDLayout docks exactly one.


def test_return_remains_same_verified_actor_and_no_untrusted_target():
    proposal, _builder, _client, server, _client = sample()
    lua=render_departure(server, proposal)
    assert 'services.ConstructionServer.GetOwnedActor(player)' in lua
    assert 'local destinationName="VehicleArrivalZone"' in lua
    assert 'select("#",...)~=1' in lua
    assert '((...)~="launch" and (...)~="return")' in lua
    assert 'typeof(target)~="CFrame"' in lua
    assert 'return {success=true,status=action=="return"' in lua
