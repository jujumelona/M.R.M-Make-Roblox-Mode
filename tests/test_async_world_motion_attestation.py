"""The async transit verifier must inspect the complete real source path."""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.async_world_motion_attestation import attest_async_vehicle_transit
from roblox_mod_ai.host_vehicle_departure import _SERVER
from roblox_mod_ai.requirement_completion_audit import _fallback_effect_witness_review


SOURCE = _SERVER.replace("@BUILDER@", "OwnedVehicleBuilder").replace(
    "@DESTINATION@", '"RMM_TestWorldDestination"'
)
PATH = "src/server/TransitService.luau"
EFFECT = (
    "The owned craft visibly travels to a playable destination "
    "with all seated passengers still aboard."
)
MODULES = [
    SimpleNamespace(
        file_path=PATH, description="Travel the owned vehicle with its occupants"
    )
]


def proof(source=SOURCE, effect=EFFECT):
    return attest_async_vehicle_transit(effect, {PATH: source}, MODULES)[0]


def test_host_authored_async_occupied_vehicle_transition_is_proven():
    entry = proof()
    assert entry is not None
    assert entry["file"] == PATH
    assert ":PivotTo(start:Lerp(target, alpha))" in entry["quote"]
    assert entry["verdict"] == "implemented"


@pytest.mark.parametrize("source", [
    SOURCE.replace("and occupantsIntact() do", "do"),
    SOURCE.replace("and seat.Occupant==humanoid", "and seat.Occupant~=humanoid"),
    SOURCE.replace("rider.seat.Occupant~=rider.humanoid",
                   "rider.seat.Occupant==rider.humanoid"),
    SOURCE.replace("vehicle:PivotTo(start:Lerp(target,alpha))",
                   "vehicle:PivotTo(start)"),
    SOURCE.replace("vehicle:PivotTo(start:Lerp(target,alpha))",
                   "otherVehicle:PivotTo(start:Lerp(target,alpha))"),
    SOURCE.replace("if alpha>=1 then completed=true;break end",
                   "if alpha>=1 then break end"),
    SOURCE.replace('vehicle:GetAttribute("OwnerUserId")~=player.UserId',
                   'vehicle:GetAttribute("OwnerUserId")==player.UserId'),
    SOURCE.replace("task.spawn(function()", "task.defer(function()"),
    SOURCE.replace("RunService.Heartbeat:Wait()", "task.wait(100)"),
    SOURCE.replace("local occupant=part.Occupant", "local occupant=nil"),
    SOURCE.replace("if #occupiedSeats==0 then", "if #occupiedSeats<0 then"),
    SOURCE.replace("local vehicle=services.OwnedVehicleBuilder.GetOwnedActor(player)",
                   "local vehicle=workspace:FindFirstChild('FakeVehicle')"),
])
def test_missing_structural_vehicle_dependency_fails_closed(source):
    assert proof(source) is None


def test_not_a_vehicle_movement_obligation_is_not_preapproved():
    assert proof(SOURCE, "Award some unrelated player currency") is None


def test_duplicate_owner_is_not_unique_proof():
    report, details = attest_async_vehicle_transit(
        EFFECT, {PATH: SOURCE, "src/server/OtherTransit.luau": SOURCE},
        MODULES,
    )
    assert report is None
    assert details["reason"] == "no_unique_verified_async_vehicle_path"


def test_fallback_does_not_send_proved_async_motion_to_small_ai():
    class ModelMustNotJudge:
        def complete_json(self, **kwargs):
            raise AssertionError("Host already proved this concrete source path")

    report, details = _fallback_effect_witness_review(
        ModelMustNotJudge(), {"id": "effect-01", "behavior": EFFECT},
        {PATH: SOURCE}, MODULES,
    )
    assert report and report["verdict"] == "implemented"
    assert details["method"] == "guarded_occupied_vehicle_timed_world_transition"
