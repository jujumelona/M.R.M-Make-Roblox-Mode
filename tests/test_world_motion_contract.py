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


def test_plan_failure_8_all_real_model_outputs_satisfy_vehicle_contract():
    """Regression data from plan_failure_logs (8)(1): all three were false rejects.

    Accepting authored *semantics* never asserts that Luau/Studio was tested.
    """
    from roblox_mod_ai.world_motion_contract import has_vehicle_motion_effect

    required = source_motion_contract(
        "그렇게해서 우주로 나갈수있고",
        [
            "우주선을 부위마다 만들어서 만들수있고",
            "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고",
        ],
    )
    assert required is not None
    recorded_outputs = [
        (
            "The server requires the player's craft to be in a valid launch-ready "
            "state before accepting the launch action; it then performs a real "
            "server-owned relocation of the craft itself into the space region, "
            "keeping the craft's existing occupants aboard. Invalid inputs "
            "are rejected: a launch request from a craft that is not in a valid "
            "launch-ready state, or a request that would leave the craft without "
            "its occupants, is refused and the craft remains in its current location.",
            "The player's craft visibly moves from its launch position into space "
            "and arrives there with its occupants still aboard.",
        ),
        (
            "On the player's confirmed launch input, the server performs a real "
            "vehicle world transition: it sets the owned spacecraft's Position "
            "and CFrame to a server-authoritative orbit destination, keeps every "
            "passenger aboard the vehicle, and persists the transition in a "
            "server-owned state field so the arrival is not a client-side mode flag.",
            "The owned spacecraft physically appears in the playable space/orbit "
            "destination with all players still aboard, and the destination "
            "world is rendered there.",
        ),
        (
            "Server-authoritative state machine transitions the owned spacecraft "
            "from the planet surface to orbit; the server computes the vehicle's "
            "new world position, applies it to the vehicle and every passenger "
            "aboard, and persists the transition state so the vehicle remains "
            "in space until a server-issued return action.",
            "The owned spacecraft and all players aboard are physically relocated "
            "to a playable space/orbit region with the space environment active; "
            "a player who was aboard the vehicle remains aboard it.",
        ),
    ]
    from roblox_mod_ai.semantic_preservation import (
        source_intent_conflicts, source_outcome_conflicts,
    )
    for server, outcome in recorded_outputs:
        assert has_vehicle_motion_effect(server), server
        assert motion_contract_errors(required, _system(server, outcome)) == []
        assert source_intent_conflicts("그렇게해서 우주로 나갈수있고", server) == []
        assert source_outcome_conflicts("그렇게해서 우주로 나갈수있고", outcome) == []


def test_vehicle_actor_is_required_beyond_nearby_ship_mentions():
    from roblox_mod_ai.world_motion_contract import has_vehicle_motion_effect

    invalid = [
        "Server checks spacecraft ownership, then launches the player "
        "into orbit without relocating the spacecraft.",
        "Server verifies ship construction and sets player.in_space to true.",
        "Server launches the player to space while the ship remains docked.",
        "Server stores an empty crew list and marks the ship as in space.",
    ]
    for server in invalid:
        assert not has_vehicle_motion_effect(server), server


def test_surface_relocation_does_not_count_as_departing_into_space():
    from roblox_mod_ai.world_motion_contract import (
        has_vehicle_motion_effect, has_vehicle_arrival_evidence,
    )
    assert not has_vehicle_motion_effect(
        "The server moves the player's spacecraft along the planet surface."
    )
    assert not has_vehicle_arrival_evidence(
        "The spacecraft physically moves to another planet surface position."
    )
    assert not has_vehicle_arrival_evidence(
        "The spaceship is docked, the player appears in space."
    )


def test_generation_checkpoint_rejects_attribute_only_spaceflight():
    """A saved module may bypass the original scaffold, never the motion gate."""
    from types import SimpleNamespace
    from roblox_mod_ai.module_generation_gate import generated_module_errors
    from roblox_mod_ai.spec import ModuleKind

    class Analyzer:
        def analyze_source(self, *_args, **_kwargs):
            return []

    module = SimpleNamespace(
        name="SpaceLaunchService", module_id="dyn_space_launch",
        file_path="src/server/SpaceLaunchService.luau",
        kind=ModuleKind.SERVER_MODULE,
    )
    proposal = SimpleNamespace(
        modules=[module],
        game_design={"dynamic_design": {
            "host_world_motion": {
                "SpaceLaunchService": {
                    "kind": "vehicle_world_transition",
                    "actor": "owned spacecraft / vehicle",
                },
            },
            "host_actions": {},
            "host_world_actions": {},
            "module_remotes": {},
        }},
    )
    fake = (
        '--!strict\nlocal Service = {}\n'
        'function Service.start(services)\n'
        '    Service._services = services\nend\n'
        'function Service.handleAction(player, services, ...)\n'
        '    player:SetAttribute("in_space", true)\n'
        '    workspace:SetAttribute("SpaceLaunch", true)\n'
        '    return true\nend\nreturn Service\n'
    )
    errors = generated_module_errors(module, proposal, fake, Analyzer())
    assert any("VEHICLE_WORLD_MOVEMENT_CODE_MISSING" in e for e in errors), errors
    actual = fake.replace(
        '    workspace:SetAttribute("SpaceLaunch", true)',
        '    local ship = workspace:FindFirstChild("OwnedSpacecraft")\n'
        '    if not ship or not ship:IsA("Model") then return false end\n'
        '    ship:PivotTo(CFrame.new(0, 1250, 0))'
    )
    fixed_errors = generated_module_errors(module, proposal, actual, Analyzer())
    assert not any("VEHICLE_WORLD_MOVEMENT_CODE_MISSING" in e
                   for e in fixed_errors), fixed_errors
