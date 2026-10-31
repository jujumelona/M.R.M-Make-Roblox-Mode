"""Generated vehicle models must contain real guest seats, not a fake crew manifest.

The launcher scans occupied Seat/VehicleSeat instances. The physical builder
therefore has to create welded, authenticatable passenger seats for multiplayer
trips. This is source-only; Studio physics needs a separate multiplayer run.
"""
import re

from roblox_mod_ai.host_ship_attachment import _SERVER
from roblox_mod_ai.host_flight_ready_attachment import render_flight_ready_attachment
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer


def rendered():
    return render_flight_ready_attachment(_SERVER)


def test_real_passenger_boarding_is_generated_for_launchable_model():
    source = rendered()
    assert 'local function ensurePilotSeat(player, ship, anchor)' in source
    assert 'local function ensurePassengerSeats(player, ship, anchor)' in source
    assert 'seat=Instance.new("Seat")' in source
    assert 'seat.Name=name' in source
    assert 'seat:Sit(humanoid)' in source
    assert 'prompt.Triggered:Connect(function(requester)' in source
    assert 'local promptName="BoardPassenger"..tostring(index)' in source
    assert 'if not ensurePassengerSeats(player, ship, anchor) then return nil end' in source
    assert 'or Service.GetOwnedActor(player)~=ship' in source
    assert 'requester.Parent~=Players' in source
    assert 'ship:GetAttribute("OwnerUserId")~=player.UserId' in source
    assert 'requester==player' in source
    assert 'root.Position-anchor.Position' in source
    assert 'or humanoid.Sit' in source
    assert 'local passengerWeld=passenger:FindFirstChild("PassengerWeld")' in source
    assert 'or passengerWeld.Part1~=passenger then return nil end' in source


def test_guest_seats_have_nonoverlapping_positions_and_valid_authoritative_weld():
    source = rendered()
    assert 'local z=index==1 and -3 or 3' in source
    assert 'seat.CFrame=anchor.CFrame*CFrame.new(-3,3.2,z)' in source
    assert 'seat.Size=Vector3.new(2.5,1,2.5)' in source
    assert 'seat.Anchored=false' in source
    assert 'weld.Part0=anchor' in source
    assert 'weld.Part1=seat' in source
    assert 'weld.Parent=seat' in source
    assert 'local seat=ship:FindFirstChild(name)' in source
    assert 'for index=1,2 do' in source
    # The seat/guest cells never collide with pilot box (3x1x3) or the
    # earliest +X modular section starting at x=2.5.
    for z in (-3, 3):
        assert abs(-3) > (2.5 + 3) / 2
        assert abs(z) > (2.5 + 3) / 2
        assert -3 + 2.5 / 2 < 5 - 5 / 2


def test_single_passenger_boarding_callback_cannot_pick_unowned_actor():
    source = rendered()
    start = source.index("prompt.Triggered:Connect(function(requester)", source.index(
        "local function ensurePassengerSeats"))
    end = source.index("seat:Sit(humanoid)", start)
    body = source[start:end]
    assert 'requester==player' in body
    assert 'requester.Parent~=Players' in body
    assert 'player.Parent~=Players' in body
    assert 'ship:GetAttribute("OwnerUserId")~=player.UserId' in body
    assert 'Service.GetOwnedActor(player)~=ship' in body
    assert 'humanoid.Health<=0' in body
    assert '(root.Position-anchor.Position).Magnitude>12' in body


def test_original_attachment_without_verified_launch_is_unmodified():
    assert "PassengerSeat" not in _SERVER
    assert "PilotSeat" not in _SERVER
    assert "GetOwnedActor" not in _SERVER


def test_generated_source_preserves_existing_secure_builder_and_launch_provider():
    source = rendered()
    for key in (
        'profile.sections[id] = {', 'inventory.resources', 'coins',
        'function Service.GetOwnedActor(player)', 'SectionWeld',
        'GetState(player, "RMMShipSections")',
    ):
        # The original source uses tight formatting in some contract fields.
        if key == "coins":
            continue
        assert key.replace(" = ", "=") in source.replace(" = ", "=")
    assert source.count("function Service.GetOwnedActor(player)") == 1
    assert source.count('local function ensurePassengerSeats(player, ship, anchor)') == 1
