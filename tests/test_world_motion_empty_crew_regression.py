"""World-motion guard must not reject server-side denied empty-crew launches."""
from roblox_mod_ai.world_motion_contract import (
    has_actual_occupant_ejection, motion_contract_errors, source_motion_contract,
)

CONTRACT = source_motion_contract(
    "그렇게해서 우주로 나갈수있고",
    ["우주선 부품을 만들어서 우주로 나갈수있다"],
)


def test_rejecting_a_crewless_launch_does_not_eject_anyone():
    server = (
        "Server relocates the entire craft into playable space with "
        "everyone aboard; requests that would leave the crew list empty "
        "are rejected."
    )
    result = (
        "The craft visibly arrives in orbit with all occupants aboard; "
        "no passenger is ejected."
    )
    assert CONTRACT is not None
    assert not has_actual_occupant_ejection(server)
    assert not has_actual_occupant_ejection(result)
    assert not any("VEHICLE_OCCUPANCY_REVERSED" in err for err in
                   motion_contract_errors(CONTRACT, [{
                       "server_behavior": server, "observable_result": result,
                   }]))


def test_real_crew_ejection_or_empty_craft_remains_blocked():
    for actual in (
        "Server ejects the pilot from the spacecraft in orbit.",
        "The spacecraft becomes empty after launch.",
        "The ship is no longer carrying the player in space.",
        "The pilot exits the craft.",
    ):
        assert has_actual_occupant_ejection(actual), actual
