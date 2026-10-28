"""Remote input targets are not executable authority producers."""
from roblox_mod_ai.model_action_authority import (
    _provenance_for_action, partition_codegen_authority,
)


def _contract():
    return {
        "transport_only": False,
        "contract": {
            "inputs": [{"id": "target", "type": "instance"}],
            "target": {"kind": "world_entity", "name": "ClaimedPlanet"},
            "state_changes": [{
                "scope": "player", "key": "ColonyOwner",
                "operation": "set",
            }],
        },
    }


def test_world_target_and_claimed_write_are_not_producer_evidence():
    assert not _provenance_for_action(_contract(), {}, "ColonizeAction")
    assert not _provenance_for_action(
        _contract(),
        {"world_objects": [{"name": "ClaimedPlanet", "class": "Part"}]},
        "ColonizeAction",
    )


def test_concrete_remote_bound_effect_program_is_producer_candidate():
    route = "ColonizeAction"
    assert _provenance_for_action(
        _contract(), {"host_effect_programs": {
            route: {"schema": "rmm/verified-effect-data-v1",
                    "changes": [{"field": "ColonyOwner", "operation": "set"}]},
        }}, route,
    )
    assert not _provenance_for_action(
        _contract(), {"host_effect_programs": {
            "UnrelatedAction": {"changes": []},
        }}, route,
    )


def test_transport_only_never_becomes_proven_with_host_claim():
    spec = _contract()
    spec["transport_only"] = True
    assert not _provenance_for_action(
        spec, {"host_executable_actions": {
            "ColonizeAction": {"effect": "update"},
        }}, "ColonizeAction",
    )
