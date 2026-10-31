"""The async transit verifier must inspect the complete real source path."""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.async_world_motion_attestation import attest_async_vehicle_transit
from roblox_mod_ai.host_vehicle_departure import _SERVER
from roblox_mod_ai.requirement_completion_audit import (
    _fallback_effect_witness_review, _is_effectful_source_line,
    audit_whole_requirement_completion,
)


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
        file_path=PATH, name="TransitService", description="Travel the owned vehicle with its occupants"
    )
]


def proof(source=SOURCE, effect=EFFECT):
    return attest_async_vehicle_transit(effect, {PATH: source}, MODULES)[0]


def test_host_authored_async_occupied_vehicle_transition_is_proven():
    entry = proof()
    assert entry is not None
    assert entry["file"] == PATH
    assert ":PivotTo(start:Lerp(target,alpha))" in entry["quote"]
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



def test_composite_proof_matches_whole_requirement_contract_and_real_lines():
    entry, metadata = attest_async_vehicle_transit(
        EFFECT, {PATH: SOURCE}, MODULES,
    )
    assert entry is not None, metadata
    parts = entry["proof_lines"]
    assert 2 <= len(parts) <= 6
    assert metadata["proof_lines"] == len(parts)
    assert entry["line"] in {row["line"] for row in parts}
    assert len({row["line"] for row in parts}) == len(parts)
    for part in parts:
        assert SOURCE.splitlines()[part["line"] - 1].strip() == part["quote"]
        assert _is_effectful_source_line(SOURCE, part["line"])
    assert parts[0]["line"] < entry["line"] < parts[-1]["line"]


def test_formatted_async_source_keeps_correct_physical_citations():
    formatted = (SOURCE.replace(
        'player:SetAttribute("RMMFlightState",action==',
        'player:SetAttribute("RMMFlightState", action == ',
    ).replace(
        "vehicle:PivotTo(start:Lerp(target,alpha))",
        "vehicle:PivotTo(start:Lerp(target, alpha))",
    ).replace(
        'player:SetAttribute("RMMFlightState",finalState)',
        'player:SetAttribute("RMMFlightState", finalState)',
    ))
    entry, metadata = attest_async_vehicle_transit(
        EFFECT, {PATH: formatted}, MODULES,
    )
    assert entry is not None, metadata
    assert 2 <= len(entry["proof_lines"]) <= 6
    for part in entry["proof_lines"]:
        assert formatted.splitlines()[part["line"] - 1].strip() == part["quote"]


def test_async_motion_contract_survives_full_requirement_audit(tmp_path):
    file = tmp_path / PATH
    file.parent.mkdir(parents=True)
    file.write_text(SOURCE, encoding="utf-8")
    proposal = SimpleNamespace(
        modules=MODULES,
        game_design={"detailed_implementation_plan": {
            "required_functions": [{
                "id": "req-transit",
                "original_request": "Players use the owned spacecraft to travel",
                "expected_outcome": EFFECT,
                "server_state_changes": [EFFECT],
                "owner_files": [PATH],
            }],
        }},
    )

    class ScopeOnly:
        def complete_json(self, **kwargs):
            prompt = kwargs["prompt"]
            if prompt.startswith("Find user-requested"):
                return {"missing_actions": []}
            raise AssertionError("No model vote should override deterministic transit")

    report = audit_whole_requirement_completion(
        proposal, tmp_path, ScopeOnly(), host_witness_only=True,
    )
    assert report["status"] == "reviewed_no_blockers", report
    assert report["fully_covered"], report
    assert len(report["checks"]) == 1
    assert len(report["checks"][0]["proof_lines"]) >= 2


@pytest.mark.parametrize("source", [
    SOURCE.replace(
        'player:SetAttribute("RMMFlightState",action=="return"',
        'player:SetAttribute("RMMFlightState","arrived"'
    ),
    SOURCE.replace('player:SetAttribute("RMMFlightState",finalState)',
                   'player:SetAttribute("RMMFlightState","arrived")'),
])
def test_missing_start_or_finish_does_not_manufacture_composite_proof(source):
    assert proof(source) is None



TRANSIT_EFFECTS = [
    "The owned craft visibly travels into a playable destination",
    "arrives with its occupants still aboard",
    "no passenger is ejected and the crew list remains populated",
]


def test_one_authoritative_transit_trace_proves_distinct_temporal_facets():
    anchors = []
    for expected, facet in zip(
        TRANSIT_EFFECTS,
        ["transit", "arrive_with_occupants",
         "preserve_occupants_on_success"],
    ):
        result, details = attest_async_vehicle_transit(
            expected, {PATH: SOURCE}, MODULES,
        )
        assert result is not None, (expected, details)
        assert details["facet"] == facet
        assert 2 <= len(result["proof_lines"]) <= 6
        assert result["line"] in {p["line"] for p in result["proof_lines"]}
        for part in result["proof_lines"]:
            assert SOURCE.splitlines()[part["line"] - 1].strip() == part["quote"]
            assert _is_effectful_source_line(SOURCE, part["line"])
        anchors.append(result["line"])
    assert len(set(anchors)) == 3


def test_three_temporal_facets_pass_real_whole_requirement_audit(tmp_path):
    target = tmp_path / PATH
    target.parent.mkdir(parents=True)
    target.write_text(SOURCE, encoding="utf-8")
    proposal = SimpleNamespace(
        modules=MODULES,
        game_design={"detailed_implementation_plan": {
            "required_functions": [{
                "id": "req-travel",
                "original_request": "Use a real owned vehicle for transport",
                "expected_outcome": ". ".join(TRANSIT_EFFECTS),
                "server_state_changes": TRANSIT_EFFECTS,
                "owner_files": [PATH],
            }],
        }},
    )

    class NoModelInterpretationOfKnownStateMachine:
        def complete_json(self, **kwargs):
            if kwargs["prompt"].startswith("Find user-requested"):
                return {"missing_actions": []}
            raise AssertionError("No repeated tiny-model interpretation of known transit")

    report = audit_whole_requirement_completion(
        proposal, tmp_path, NoModelInterpretationOfKnownStateMachine(),
        host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert len(report["checks"]) == 3, report
    assert not report.get("unverified_effects"), report
    assert len({r["line"] for r in report["checks"]}) == 3, report


@pytest.mark.parametrize("broken", [
    SOURCE.replace("and occupantsIntact() do", "do"),
    SOURCE.replace("table.insert(occupiedSeats, { seat=part, humanoid=occupant })",
                   "local decor = { seat=part, humanoid=occupant }"),
    SOURCE.replace('player:SetAttribute("RMMFlightState",finalState)',
                   'player:SetAttribute("RMMFlightState","arrived")'),
])
def test_temporal_facet_audit_fails_closed_on_broken_continuity(broken):
    for claim in TRANSIT_EFFECTS[1:]:
        cert, _ = attest_async_vehicle_transit(claim, {PATH: broken}, MODULES)
        assert cert is None
