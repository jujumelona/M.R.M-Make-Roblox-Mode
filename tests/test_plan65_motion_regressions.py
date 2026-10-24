"""Exact regressions from user-provided proposal (65) / plan_failure_logs (23).

These assert planning semantics, not Roblox Studio execution.
"""
from roblox_mod_ai.world_motion_contract import (
    source_motion_contract, motion_contract_errors, has_vehicle_arrival_evidence,
)
from roblox_mod_ai.source_ownership_review import ground_source_ownership


def _required():
    return source_motion_contract(
        "그렇게해서 우주로 나갈수있고",
        ["무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"],
    )


def test_plan65_all_three_real_craft_launch_outputs_are_not_false_negatives():
    assert _required() is not None
    records = [
        (
            "Server validates the player's launch request against the craft's "
            "current state, then performs a server-owned relocation of the "
            "entire craft into the space region with all existing occupants "
            "aboard; invalid inputs such as a launch request from a "
            "non-space-ready craft or a request that would leave the crew "
            "list empty are rejected.",
            "The craft visibly travels and arrives in space with its "
            "occupants still on board; no passenger is ejected and the crew "
            "list remains unchanged.",
        ),
        (
            "On the player's confirmed launch input, the server performs a "
            "real world transition: it moves the owned spacecraft's "
            "VehicleSeat/vehicle to a playable space/orbit destination, "
            "keeps every player aboard the vehicle, and transitions the world "
            "to the space destination; the player's mode flag alone is never "
            "treated as travel.",
            "The owned spacecraft physically changes world location to "
            "playable space/orbit with all players still aboard, and the "
            "world visibly changes to the space destination.",
        ),
        (
            "On the player's confirmed launch input, the server transitions "
            "the owned spacecraft's state from 'surface' to 'in_space' and "
            "physically moves the vehicle and all aboard players to the "
            "destination world (orbit), then triggers the arrival event.",
            "The spacecraft and its passengers are visibly present in the "
            "destination world after launch, not merely flagged as launched.",
        ),
    ]
    for server, outcome in records:
        assert motion_contract_errors(
            _required(), [{"server_behavior": server, "observable_result": outcome}]
        ) == [], (server, outcome)


def test_negative_ejection_not_confused_with_actual_ejection():
    server = (
        "Server launches the craft itself into playable space with its "
        "occupants aboard."
    )
    arrived = "The craft visibly arrives in orbit with all players aboard."
    assert motion_contract_errors(
        _required(), [{"server_behavior": server,
                       "observable_result": arrived + " No passenger is ejected."}]
    ) == []
    assert any(
        "VEHICLE_OCCUPANCY_REVERSED" in issue
        for issue in motion_contract_errors(
            _required(), [{"server_behavior": server,
                            "observable_result": arrived + " The pilot exits the craft."}]
        )
    )


def test_disjoint_system_cannot_supply_other_system_missing_arrival():
    systems = [
        {"server_behavior": "The server relocates the craft to orbit.",
         "observable_result": "The ship display changes to launched."},
        {"server_behavior": "The server sets a status label only.",
         "observable_result": "The craft visibly arrives in space."},
    ]
    assert any(
        "VEHICLE_TRAVEL_RESULT_MISSING" in issue
        for issue in motion_contract_errors(_required(), systems)
    )


def test_destination_label_without_craft_motion_is_not_enough():
    assert not has_vehicle_arrival_evidence(
        "The spacecraft status label shows destination world."
    )
    assert not has_vehicle_arrival_evidence(
        "The spaceship remains docked, player appears in space."
    )
    assert any(
        "VEHICLE_TRANSITION_MISSING" in issue
        for issue in motion_contract_errors(
            _required(), [{
                "server_behavior": "Server sets the spaceship in_space flag.",
                "observable_result": (
                    "The spacecraft and players are visibly present "
                    "in destination world after launch."
                ),
            }]
        )
    )


def test_accepted_set_defined_after_review_of_four_candidates():
    systems = [
        {"name": f"System{i}",
         "server_behavior": "Server changes the authoritative resource state for this action."}
        for i in range(4)
    ]
    verdict = {"bindings": [
        {"index": i, "owned": i in (1, 2, 3),
         "source_quote": "자원" if i in (1, 2, 3) else "",
         "server_quote": "Server changes the authoritative resource state"
         if i in (1, 2, 3) else ""}
        for i in range(4)
    ]}
    scoped, rejected = ground_source_ownership(
        {"systems": systems}, verdict, source_clause="자원 수집과 거래"
    )
    assert len(scoped["systems"]) == 3
    assert rejected == ["System0"]
