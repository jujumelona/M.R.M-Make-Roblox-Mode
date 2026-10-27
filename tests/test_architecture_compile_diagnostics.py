"""Failure ZIP must retain original model-architecture observations and reason."""
import json
import zipfile
from types import SimpleNamespace

from roblox_mod_ai.agent_trajectory import AgentTrajectory
from roblox_mod_ai.architecture_failure_receipt import (
    export_architecture_compilation_report,
)
from roblox_mod_ai.semantic_world_entities import (
    normalize_logical_state_references,
    assert_physical_world_entities,
)


def test_model_architecture_failure_keeps_real_cause_in_failed_zip(tmp_path):
    p = SimpleNamespace(game_design={
        "planning_phase": "implementation_contract",
        "dynamic_design": None,
        "pre_design_research": {
            "provider_failures": [{
                "provider": "local_small_model", "facet": "dynamic_game_design",
                "reason": "Feature facet-two could not be validated: invalid world actor",
            }],
            "architecture_attempts": [{
                "facet_id": "facet-two", "attempt": 1, "passed": False,
                "validator_error": "WORLD_ENTITY_LOGICAL_STATE_NOT_PHYSICAL",
                "model_response": {"systems": [{"world_entities": ["PlayerCurrency"]}]},
            }],
            "ledger": {
                "unimplemented_facets": ["dynamic_architecture_failed"],
                "classification_unverified": ["chunk-002"],
                "requirements": [{"id": "req-001"}, {"id": "req-002"}],
            },
        },
    })
    root = tmp_path / "build"
    root.mkdir()
    details = export_architecture_compilation_report(p, root)
    assert details["status"] == "uncompiled"
    assert details["attempts_recorded"] == 1
    trace = AgentTrajectory(root)
    bundle = trace.failure_bundle(
        "resolve_dependencies: INCOMPLETE_GAMEPLAY_ARCHITECTURE",
        tool_results={"architecture_compilation": details},
    )
    with zipfile.ZipFile(bundle) as reader:
        assert "architecture_compilation_report.json" in reader.namelist()
        report = json.loads(reader.read("architecture_compilation_report.json"))
        assert "facet-two" in report["root_error"]
        assert report["architecture_attempts"][0]["model_response"] == {
            "systems": [{"world_entities": ["PlayerCurrency"]}],
        }
        assert report["classification_unverified"] == ["chunk-002"]


def test_logical_world_fields_are_data_for_custom_input_only():
    raw = {"systems": [{
        "name": "Exchange",
        "server_behavior": "Validate and store owned item counts.",
        "client_behavior": "Player enters a quantity in a typed form.",
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [
            "PlayerCurrency", "CounterpartyInventory", "ResourceNode", "InventoryChest"
        ],
    }]}
    updated, notes = normalize_logical_state_references(raw)
    assert updated["systems"][0]["world_entities"] == [
        "ResourceNode", "InventoryChest",
    ]
    assert {n["name"] for n in notes} == {
        "PlayerCurrency", "CounterpartyInventory",
    }
    assert len(raw["systems"][0]["world_entities"]) == 4
    assert_physical_world_entities(updated["systems"][0]["world_entities"])


def test_world_prompt_and_typed_physical_target_are_not_silently_removed():
    for spec in (
        {"interaction": "event", "input_mode": "world_prompt"},
        {"interaction": "request_response", "input_mode": "custom",
         "action_contract": {"target": {"kind": "world_object"}}},
    ):
        raw = {"systems": [dict(
            spec, name="Physical", world_entities=["Inventory"],
            client_behavior="Interact with a real selected object",
        )]}
        fixed, notes = normalize_logical_state_references(raw)
        assert fixed == raw
        assert notes == []


def test_ui_explicitly_clicking_object_does_not_disappear():
    raw = {"systems": [{
        "name": "Click", "interaction": "event", "input_mode": "custom",
        "client_behavior": "Player clicks the Trade Request when nearby.",
        "world_entities": ["TradeRequest"],
    }]}
    fixed, notes = normalize_logical_state_references(raw)
    assert not notes
    assert fixed == raw


def test_server_physical_access_keeps_real_target():
    source = {"systems": [{
        "name": "UseMachine", "interaction": "request_response",
        "input_mode": "custom",
        "server_behavior": (
            "Validate the player's distance to the TradeRequest position "
            "in workspace and execute the action only while nearby."
        ),
        "client_behavior": "A player presses a button to request this action.",
        "world_entities": ["TradeRequest"],
    }]}
    corrected, repairs = normalize_logical_state_references(source)
    assert corrected == source
    assert repairs == []
