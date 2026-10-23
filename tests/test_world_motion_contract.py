"""Regression: the old 9B planner ejected a passenger during ship launch."""
from roblox_mod_ai.world_motion_contract import (
    source_motion_contract, motion_contract_errors, vehicle_motion_code_errors,
)


def _system(server, outcome):
    return [{"server_behavior": server, "observable_result": outcome}]


def test_dependent_launch_resolves_existing_vehicle_not_passenger_exit():
    contract = source_motion_contract(
        "그렇게해서 우주로 나갈수있고",
        ["무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"],
    )
    assert contract is not None
    assert contract["kind"] == "vehicle_world_transition"
    assert "remain aboard" in contract["occupant_rule"]
    assert source_motion_contract(
        "우주로 나가면 다른행성의 특수 광물",
        ["우주선 성능 업그레이드"],
    ) is None
    assert source_motion_contract(
        "그렇게해서 우주로 나갈수있고", []
    ) is None


def test_real_plan_failure_replays_all_three_attempts_without_fake_success():
    required = source_motion_contract(
        "그렇게해서 우주로 나갈수있고", ["우주선을 부위마다 만든다"]
    )
    attempts = [
        _system(
            "Server verifies the player aboard spaceship and sets in_space.",
            "The player is launched out of the spaceship into space.",
        ),
        _system(
            "Server checks the spaceship and writes the same in_space status.",
            "The player leaves the spaceship and is outside in space.",
        ),
        _system(
            "Server sets in_space, clears crew manifest and transitions "
            "the ship to empty_hull without relocating the ship.",
            "The ship is visibly empty with no longer carrying the player.",
        ),
    ]
    for systems in attempts:
        assert motion_contract_errors(required, systems)
    near_but_wrong_actor = _system(
        "Server verifies ship ownership, then launches the player into space "
        "while the spaceship remains docked and unmoved.",
        "The spaceship remains docked, player appears in space.",
    )
    assert any(
        "VEHICLE_TRANSITION_MISSING" in issue
        for issue in motion_contract_errors(required, near_but_wrong_actor)
    )
    correct = _system(
        "Server checks the assembled spaceship and fuel, launches the "
        "spacecraft carrying players into space and teleports the ship "
        "and passengers into the orbital zone.",
        "The spaceship launches into space and the player remains aboard.",
    )
    assert motion_contract_errors(required, correct) == []


def test_server_codegen_requires_craft_displacement_not_status_only():
    assert vehicle_motion_code_errors(
        'player:SetAttribute("in_space", true)\n'
        'player.Character:PivotTo(CFrame.new(12, 0, 12))\n'
        'local ship = workspace:FindFirstChild("Ship")'
    )
    assert vehicle_motion_code_errors(
        'local ship = workspace:FindFirstChild("Ship")\n'
        'ship:SetAttribute("in_space", true)'
    )
    assert vehicle_motion_code_errors(
        'local ship = workspace:FindFirstChild("Ship")\n'
        'ship:PivotTo(CFrame.new(0, 120, 0))'
    ) == []
