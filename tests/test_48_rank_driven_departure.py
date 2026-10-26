"""48: ship upgrade must affect ascent; flight is not instant teleport."""
from tests.test_plan83_ordered_assembly_launch import sample
from roblox_mod_ai.host_vehicle_departure import render_departure


def test_departure_consumes_authoritative_spaceship_rank():
    proposal, _builder, _client, server, client = sample()
    luau = render_departure(server, proposal)
    ui = render_departure(client, proposal)
    assert luau and ui
    assert 'GetState(player,"RMMRankProgress")' in luau
    assert 'local rank=progress.Spaceship or 0' in luau
    assert 'if not validTier(rank)' in luau
    assert 'local duration=math.max(3,7-0.4*rank)' in luau
    # Sections now have an actual server-side effect on the voyage duration,
    # not merely an unused assembly score attribute.
    assert 'GetState(player,"RMMShipSections")' in luau
    assert 'part.owned==true' in luau
    assert 'contribution%1~=0' in luau
    assert 'duration=math.max(2,duration-math.min(1.5,assemblyScore/200))' in luau
    assert 'assemblyPerformance=assemblyScore' in luau
    assert 'player:GetAttribute("RMMShipAssemblyPerformance")' not in luau
    assert "start:Lerp(target,alpha)" in luau
    assert "RunService.Heartbeat:Wait()" in luau
    assert "already_launching" in luau
    assert "already_in_orbit" in luau
    assert 'player:SetAttribute("RMMFlightState",action=="return" and "returning" or "launching")' in luau
    assert 'player:SetAttribute("RMMFlightState",finalState)' in luau
    assert 'homeDock[player]=start' in luau
    assert "vehicle:PivotTo(destination.CFrame * CFrame.new(0,16,0))" not in luau
    assert "GetAttributeChangedSignal" in ui
    assert 'info.Text="Vehicle arrived"' not in ui


def test_departure_is_still_tied_to_verified_actor_service():
    proposal, _builder, _client, server, _ui = sample()
    luau = render_departure(server, proposal)
    assert "services.ConstructionServer.GetOwnedActor(player)" in luau
    assert 'OwnerUserId' in luau
    assert 'seat.Occupant~=humanoid' in luau
    assert 'destinationName="VehicleArrivalZone"' in luau
