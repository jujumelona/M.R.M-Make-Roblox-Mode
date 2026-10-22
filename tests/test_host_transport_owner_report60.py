"""Report-60/plan_failure_logs (19): remove transport retry, not a genre patch.

The small model owns gameplay state transitions only. Host compiles its
transport/UI deterministically. A model interaction string is never trusted
as an enum or resent to the small model for correction in production.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from roblox_mod_ai.semantic_input_contract import (
    bind_host_standard_transport, canonicalize_interaction_fields,
    interaction_issues,
)
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect


def _raw_system():
    # Exact system returned by 19th failure bundle (short gameplay draft).
    return {
        "name": "Upgrade Ship Part",
        "server_behavior": (
            "Validate the player's selected ship part and requested upgrade "
            "level against the ship's current state and available resources; "
            "on success, transition the ship part from its current upgrade "
            "level to the requested level, consume the required resources, "
            "and persist the new state."
        ),
        "client_behavior": "",
        "observable_result": (
            "The selected ship part shows its upgraded state and the "
            "ship's resource balance changes."
        ),
        "interaction": "custom", "input_mode": "custom",
        "world_entities": [],
    }


def test_report60_wrong_enum_host_compiles_without_changing_gameplay():
    raw = {"systems": [_raw_system()]}
    original = deepcopy(raw)
    assert interaction_issues(raw) == {
        0: ["interaction must be none, event or request_response"]
    }
    converted, changed = bind_host_standard_transport(raw)
    assert changed == [0]
    assert converted["systems"][0]["interaction"] == "request_response"
    assert converted["systems"][0]["input_mode"] == "custom"
    assert "typed action form" in converted["systems"][0]["client_behavior"]
    for key in ("name", "server_behavior", "observable_result", "world_entities"):
        assert converted["systems"][0][key] == original["systems"][0][key]
    assert interaction_issues(converted) == {}
    assert raw == original  # no silent mutation of original draft


@pytest.mark.parametrize("name,server,outcome", [
    ("Water Orchard", "Deduct owned water and increase growth of the tree.",
     "The tree's growth level increases."),
    ("Claim Territory", "Check the world claim and save new territory ownership.",
     "The settlement's world ownership changes."),
    ("Compose Melody", "Store chosen MIDI note pattern in user's saved composition.",
     "The saved musical sequence appears in the editor."),
])
def test_host_protocol_is_genre_independent(name, server, outcome):
    raw = {"systems": [dict(_raw_system(), name=name,
                             server_behavior=server,
                             observable_result=outcome)]}
    fixed, indexes = bind_host_standard_transport(raw)
    assert indexes == [0]
    assert fixed["systems"][0]["server_behavior"] == server
    assert fixed["systems"][0]["observable_result"] == outcome
    assert interaction_issues(fixed) == {}


def test_ingress_world_prompt_and_autonomous_are_not_reinterpreted():
    systems = [
        dict(_raw_system(), name="Gather", interaction="custom",
             input_mode="world_prompt", world_entities=["Ore Node"]),
        dict(_raw_system(), name="Craft", interaction="event",
             input_mode="host_button"),
        dict(_raw_system(), name="Server Clock", interaction="none",
             input_mode="custom"),
        dict(_raw_system(), name="World Target Choice",
             interaction="custom", input_mode="world_prompt",
             world_entities=[]),
    ]
    result, indexes = bind_host_standard_transport({"systems": systems})
    assert set(indexes) == {0, 1, 2, 3}
    outputs = result["systems"]
    assert [(s["interaction"], s["input_mode"]) for s in outputs] == [
        ("event", "world_prompt"), ("request_response", "host_button"),
        ("none", "custom"), ("request_response", "custom"),
    ]
    assert interaction_issues(result) == {}


def test_whitelisted_choice_forces_request_response_without_asking_model():
    raw = {"systems": [{
        **_raw_system(),
        "action_choices": [
            {"id": "Install", "label": "Install"},
            {"id": "Remove", "label": "Remove"},
        ],
        "interaction": "event"
    }]}
    output, _ = bind_host_standard_transport(raw)
    assert output["systems"][0]["interaction"] == "request_response"
    assert interaction_issues(output) == {}


def test_invalid_model_transport_is_repaired_at_host_not_by_schema_reprompt(
        monkeypatch):
    """An exact copy of the report-60 first model output must need one
    planner call, not the prior 'custom' then two failed repair attempts.
    """
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "업그레이드 확장 할 수 있고"
    research = {
        "ledger": {
            "original_prompt": source,
            "requirements": [{"id": "req-006", "statement": source}],
            "facets": [{
                "id": "intent-7735e08094", "source_span": source,
                "requirements": ["req-006"],
                "search_query": "Roblox Upgrade and expand the ship",
            }],
        },
        "evidence": [],
    }

    class RealReportModel:
        supports_host_standard_transport = True
        supports_typed_action_contract = False
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) > 1:
                raise AssertionError("Production must never request a transport repair")
            return {"systems": [_raw_system()]}

    model = RealReportModel()
    result = RobloxDynamicArchitect(model).design(source, research, [])
    assert len(model.calls) == 1
    assert result["host_typed_actions"]
    assert research["architecture_attempts"][0]["passed"] is True
    assert research["architecture_attempts"][0]["typed_contract_attempts"] == []
    assert research["architecture_attempts"][0]["host_bound_transport_indexes"] == [0]
    assert not any("SEMANTIC_INPUT_CONTRACT" in str(e)
                   for e in research["architecture_attempts"])


def test_legacy_nonproduction_path_is_not_silently_rewritten():
    raw = {"systems": [_raw_system()]}
    converted, changed = canonicalize_interaction_fields(raw)
    assert converted == raw
    assert changed == []
    assert interaction_issues(converted)
