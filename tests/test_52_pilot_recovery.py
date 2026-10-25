"""52: a pilot death or seat ejection cannot strand the assembled spacecraft.

Static emitted-source assertions only; real physics requires Studio playtests.
"""
from tests.test_plan83_ordered_assembly_launch import sample
from roblox_mod_ai.host_vehicle_departure import render_departure


def _render():
    proposal, _builder, _client, server, _ui = sample()
    return render_departure(server, proposal)


def test_death_and_respawn_recover_owner_ship_at_authoritative_dock():
    src=_render()
    assert src is not None
    for item in (
        'local function recoverFlight(player,services)',
        'local dock=homeDock[player]',
        'local ship=services.ConstructionServer.GetOwnedActor(player)',
        'ship:GetAttribute("OwnerUserId")==player.UserId',
        'ship:PivotTo(dock)',
        'player:SetAttribute("RMMFlightState","landed")',
        'player:SetAttribute("RMMShipFlightSeconds",nil)',
        'player.CharacterAdded:Connect(watchCharacter)',
        'humanoid.Died:Connect(function()',
        'if homeDock[player] then recoverFlight(player,services) end',
        'Players.PlayerAdded:Connect(watchPlayer)',
        'for _,player in Players:GetPlayers() do watchPlayer(player) end',
    ):
        assert item in src, item


def test_pilot_remains_alive_in_own_seat_throughout_flight():
    src=_render()
    for item in (
        'local flightToken={}',
        'inFlight[player]=flightToken',
        'while inFlight[player]==flightToken',
        'and humanoid.Health>0 and humanoid.Parent~=nil',
        'and seat.Parent==vehicle and seat.Occupant==humanoid',
        'if inFlight[player]~=flightToken then return end',
        'local dock=homeDock[player]',
        'vehicle:PivotTo(dock)',
        'homeDock[player]=nil',
    ):
        assert item in src, item
    assert src.index('if inFlight[player]~=flightToken then return end') < src.index('inFlight[player]=nil\n        if not completed then')
    assert 'while inFlight[player] and player.Parent' not in src
