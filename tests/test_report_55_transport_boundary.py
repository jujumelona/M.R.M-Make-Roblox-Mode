"""Regress real plan_failure_logs (14) as generic host transport contracts.

This is not a scenario-specific planner prompt: the same enum/ingress rules
apply to harvesting, crafting, gardening and any model-authored gameplay.
"""
from __future__ import annotations

from copy import deepcopy
import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.host_architecture import expand_semantic_facet, HostArchitectureError
from roblox_mod_ai.semantic_input_contract import (
    apply_interaction_patch, interaction_issues,
)


def _source():
    return {
        "name": "Construct Modular Vehicle",
        "server_behavior": (
            "Validate the selected part type and required materials "
            "against the player's owned inventory; deduct required items, "
            "install the part in the assembly, and persist the saved build state."
        ),
        "client_behavior": "",
        "observable_result": (
            "The selected part appears in the player's assembled vehicle "
            "and the resource inventory decreases."
        ),
        "interaction": "custom",  # from real 14th failure: wrong enum domain
        "input_mode": "custom",
        "world_entities": ["Vehicle Assembly"],
    }


def _convert(system, source="Build a vehicle from individual parts"):
    return expand_semantic_facet(
        {"systems": [system]}, facet_id="intent-123",
        requirement_ids=["req-123"],
        source_requirements=[{"id": "req-123", "statement": source}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
    )


def test_host_wired_world_prompt_does_not_require_duplicated_client_script():
    system = {
        "name": "Harvest Nearby Resource",
        "server_behavior": (
            "Validate the chosen resource node and mining reach, change "
            "the node to depleted, and increment the player's owned resources."
        ),
        "client_behavior": "",
        "observable_result": (
            "The depleted node is visible and the player resource count increases."
        ),
        "interaction": "event",
        "input_mode": "world_prompt",
        "world_entities": ["Resource Node"],
    }
    assert interaction_issues({"systems": [system]}) == {}
    built = _convert(system, "Harvest nearby resources")
    assert len(built["modules"]) == 1
    assert built["modules"][0]["role"] == "server"
    assert built["remotes"] == []
    assert len(built["_host_world_actions"]) == 1


def test_host_wired_zero_argument_button_has_real_generated_client_contract():
    system = {
        "name": "Request Daily Award",
        "server_behavior": (
            "The server checks the cooldown and awards one earned daily "
            "credit to the requesting player's authoritative balance."
        ),
        "client_behavior": "",
        "observable_result": (
            "The player's credits increase and their daily award is confirmed."
        ),
        "interaction": "request_response",
        "input_mode": "host_button",
        "world_entities": [],
    }
    assert interaction_issues({"systems": [system]}) == {}
    built = _convert(system, "Claim an earned daily award")
    clients = [m for m in built["modules"] if m["role"] == "client"]
    assert len(clients) == 1
    assert "Host-generated button" in clients[0]["behavior"]
    assert len(clients[0]["behavior"]) >= 24
    assert built["_host_client_actions"]


def test_custom_user_selection_must_still_have_real_client_input():
    system = dict(_source(), interaction="request_response")
    assert 0 in interaction_issues({"systems": [system]})
    with pytest.raises(HostArchitectureError, match="Client interaction"):
        _convert(system)


def test_constrained_model_can_echo_unchanged_gameplay_without_violating_patch():
    raw = {"systems": [_source()]}
    patch = dict(_source(), interaction="request_response",
                 input_mode="custom",
                 client_behavior=(
                     "Player selects a vehicle part and target slot, "
                     "confirms material cost, and sends a build request."
                 ))
    # Real-world constrained backends often echo a complete system and omit
    # an index when exactly one system has an invalid protocol.
    fixed = apply_interaction_patch(raw, {"systems": [patch]})
    assert fixed["systems"][0]["server_behavior"] == raw["systems"][0]["server_behavior"]
    assert fixed["systems"][0]["observable_result"] == raw["systems"][0]["observable_result"]
    assert fixed["systems"][0]["world_entities"] == ["Vehicle Assembly"]
    assert interaction_issues(fixed) == {}
    built = _convert(fixed["systems"][0])
    assert len(built["modules"]) == 2


def test_single_unambiguous_metadata_only_patch_without_envelope_is_accepted():
    raw = {"systems": [_source()]}
    fixed = apply_interaction_patch(raw, {
        "interaction": "request_response",
        "client_behavior": (
            "Player chooses a vehicle component then confirms a valid "
            "build request using the client selection interface."
        ),
    })
    assert fixed["systems"][0]["input_mode"] == "custom"
    assert fixed["systems"][0]["interaction"] == "request_response"
    assert interaction_issues(fixed) == {}


@pytest.mark.parametrize("tamper", [
    {"server_behavior": "Give the player unlimited money."},
    {"observable_result": "The world ends."},
    {"world_entities": []},
    {"name": "Different Unrequested Mechanic"},
    {"action_choices": [{"id": "free", "label": "Free Cash"}]},
])
def test_metadata_patch_cannot_smuggle_gameplay_changes(tamper):
    raw = {"systems": [_source()]}
    patch = {
        "interaction": "request_response",
        "input_mode": "custom",
        "client_behavior": (
            "Player selects a vehicle part and confirms the materials "
            "for server-authoritative vehicle assembly."
        ),
        **tamper,
    }
    with pytest.raises(ValueError, match="only protocol"):
        apply_interaction_patch(raw, {"systems": [patch]})


def test_real_architect_repairs_report_55_without_regenerating_server_gameplay(
        monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Build a vehicle from individual parts"
    evidence = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-123", "statement": source}],
        "facets": [{
            "id": "intent-123", "requirements": ["req-123"],
            "source_span": source, "search_query": "Build vehicle parts",
        }],
    }, "evidence": []}
    original = _source()
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return {"systems": [deepcopy(original)]}
            assert len(self.calls) == 2
            assert "interaction protocol" in prompt
            assert kwargs["max_tokens"] <= 600
            # The LLM unnecessarily echoes the original system; the host
            # verifies equality rather than falsely rejecting a safe patch.
            return {"systems": [dict(
                original,
                interaction="request_response", input_mode="custom",
                client_behavior=(
                    "Player selects a component and a target slot, "
                    "then submits a materials-backed build request."
                ),
            )]}
    m = Model()
    result = RobloxDynamicArchitect(m).design(source, evidence, [])
    assert len(m.calls) == 2
    assert any(original["server_behavior"] == module.description
               for module in result["modules"])
    assert evidence["architecture_attempts"][0]["validator_error"].startswith(
        "DynamicDesignError: SEMANTIC_INPUT_CONTRACT")
    assert evidence["architecture_attempts"][-1]["passed"]


@pytest.mark.parametrize("broken", [
    [], {"unexpected": "object"}, 123, None,
])
def test_malformed_transport_enum_never_crashes_before_bounded_repair(broken):
    raw = {"systems": [dict(_source(), interaction=broken, input_mode="custom")]}
    assert 0 in interaction_issues(raw)
    with pytest.raises(ValueError, match="only protocol"):
        apply_interaction_patch(raw, {
            "systems": [{"interaction": broken, "input_mode": "custom",
                         "client_behavior": "Player uses a vehicle build menu."}]
        })
    raw_mode = {"systems": [dict(_source(), interaction="request_response",
                                 input_mode=broken)]}
    assert 0 in interaction_issues(raw_mode)


def test_transport_repairs_two_invalid_systems_by_explicit_index_only():
    source = dict(_source())
    raw = {"systems": [source, dict(source, name="Second Task")]}
    with pytest.raises(ValueError, match="every invalid"):
        apply_interaction_patch(raw, {"systems": [{
            "index": 0, "interaction": "request_response",
            "client_behavior": "Player selects the first part and builds it.",
        }]})
    result = apply_interaction_patch(raw, {"systems": [
        {"index": 0, "interaction": "request_response",
         "client_behavior": "Player selects the first valid component and builds it."},
        {"index": 1, "interaction": "event",
         "client_behavior": "Player selects the second valid component and builds it."},
    ]})
    assert interaction_issues(result) == {}
    assert result["systems"][0]["server_behavior"] == source["server_behavior"]
