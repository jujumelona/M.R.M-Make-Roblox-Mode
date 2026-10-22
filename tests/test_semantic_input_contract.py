"""Generic regression tests for the typed interaction/input routing boundary.

Covers the reported swapped-enum failure and an unrelated interaction so a
single gameplay prompt cannot special-case the implementation.
"""
from __future__ import annotations

from copy import deepcopy
import pytest

from roblox_mod_ai.semantic_input_contract import (
    canonicalize_interaction_fields, interaction_issues, apply_interaction_patch,
    apply_client_input_completion, CLIENT_INPUT_ONLY_SCHEMA,
)
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect


def test_swap_only_recognizable_disjoint_enum_fields():
    draft = {"systems": [{
        "name": "ParcelDelivery",
        "server_behavior": "Server validates a parcel and moves the owned parcel to the drop-off location.",
        "client_behavior": "Client selects the parcel and sends a delivery request.",
        "observable_result": "Parcel is delivered and the recipient receives it.",
        "interaction": "host_button",
        "input_mode": "request_response",
        "world_entities": [],
    }]}
    original = deepcopy(draft)
    fixed, indices = canonicalize_interaction_fields(draft)
    assert indices == [0]
    assert fixed["systems"][0]["interaction"] == "request_response"
    assert fixed["systems"][0]["input_mode"] == "host_button"
    for key in ("name", "server_behavior", "client_behavior",
                "observable_result", "world_entities"):
        assert fixed["systems"][0][key] == original["systems"][0][key]
    assert draft == original
    assert interaction_issues(fixed) == {}


def test_swap_with_world_targets_is_not_silently_approved():
    original = {"systems": [{
        "name": "DeliverySelection",
        "server_behavior": "Server checks the selected parcel, then transfers it to the chosen recipient.",
        "client_behavior": "Client targets the parcel and the recipient.",
        "observable_result": "Recipient receives the selected parcel.",
        "interaction": "host_button",
        "input_mode": "request_response",
        "world_entities": ["Parcel", "Recipient"],
    }]}
    fixed, _ = canonicalize_interaction_fields(original)
    assert 0 in interaction_issues(fixed)
    assert "host_button" in str(interaction_issues(fixed))
    with pytest.raises(ValueError, match="protocol"):
        apply_interaction_patch(fixed, {"systems": [{
            "index": 0, "interaction": "request_response",
            "input_mode": "host_button",
            "client_behavior": "Client chooses a specific parcel and recipient.",
        }]})
    result = apply_interaction_patch(fixed, {"systems": [{
        "index": 0, "interaction": "request_response",
        "input_mode": "custom",
        "client_behavior": "Client selects a specific parcel and the recipient in a delivery UI.",
    }]})
    assert result["systems"][0]["server_behavior"] == original["systems"][0]["server_behavior"]
    assert result["systems"][0]["world_entities"] == ["Parcel", "Recipient"]
    assert interaction_issues(result) == {}


def test_patch_cannot_edit_implementation_or_omit_invalid_system():
    draft = {"systems": [{
        "name": "Trade",
        "interaction": "event", "input_mode": "world_prompt",
        "world_entities": ["Buyer", "Seller"],
        "client_behavior": "Client initiates a trade against the selected target.",
    }]}
    with pytest.raises(ValueError, match="only protocol"):
        apply_interaction_patch(draft, {"systems": [{
            "index": 0, "interaction": "request_response",
            "input_mode": "custom",
            "client_behavior": "Client selects the trade request.",
            "server_behavior": "Server awards free cash.",
        }]})
    with pytest.raises(ValueError, match="no corrections"):
        apply_interaction_patch(draft, {"systems": []})


def test_architect_repairs_malformed_transport_without_replanning_gameplay(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Ship can depart into space"
    audit = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-journey", "statement": source}],
        "facets": [{
            "id": "intent-journey",
            "requirements": ["req-journey"],
            "source_span": source,
            "search_query": "Roblox launch spacecraft travel into space",
        }],
    }, "evidence": []}
    wrong_action = {"systems": [{
        "name": "ShipUpgrade",
        "server_behavior": (
            "The server validates the player currency then purchases "
            "new components and upgrades the spaceship engine."
        ),
        "client_behavior": "The client displays the purchased upgrade.",
        "observable_result": "Ship components increase in performance.",
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }]}
    malformed = {"systems": [{
        "name": "SpaceTravel",
        "server_behavior": (
            "The server validates the player's active ship, launches the "
            "spacecraft into space, and moves the player to the orbital zone."
        ),
        "client_behavior": (
            "The client displays a launch interface and shows the "
            "spacecraft approaching the orbit region."
        ),
        "observable_result": (
            "The spacecraft launches into space, and the player arrives "
            "at the orbital exploration area."
        ),
        "interaction": "host_button",
        "input_mode": "request_response",
        "world_entities": ["Spacecraft", "OrbitDestination"],
    }]}
    class LocalModel:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append((prompt, options))
            if len(self.calls) == 1:
                return deepcopy(wrong_action)
            if len(self.calls) == 2:
                assert "missing_obligations" in prompt
                return deepcopy(malformed)
            assert len(self.calls) == 3
            assert "interaction protocol" in prompt
            assert options["max_tokens"] <= 600
            return {"systems": [{
                "index": 0, "interaction": "request_response",
                "input_mode": "custom",
                "client_behavior": (
                    "The player selects their spacecraft and intended "
                    "orbital destination, then requests departure."
                ),
            }]}
    model = LocalModel()
    result = RobloxDynamicArchitect(model).design(source, audit, [])
    assert len(model.calls) == 3
    assert any("launches the spacecraft into space" in m.description
               for m in result["modules"])
    assert all("purchases new components" not in m.description
               for m in result["modules"])


def _trade_missing_client():
    return {"systems": [{
        "name": "Trade",
        "server_behavior": (
            "Validate the player's trade request against the authoritative "
            "inventory and money state, transfer resources or credits, then "
            "commit both balances to the server-owned economy."
        ),
        "client_behavior": "",
        "observable_result": (
            "The inventory count and earned currency balance update visibly."
        ),
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }]}


def test_real_plan_56_empty_optional_schema_keys_are_idempotent():
    raw = _trade_missing_client()
    original = deepcopy(raw)
    patch = {"systems": [{
        "index": 0,
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
        "action_choices": [],
        "client_behavior": (
            "The player opens the Trade interface, selects a resource and "
            "quantity, reviews the in-game price, and submits the transaction."
        ),
    }]}
    got = apply_interaction_patch(raw, patch)
    assert interaction_issues(got) == {}
    assert got["systems"][0]["server_behavior"] == raw["systems"][0]["server_behavior"]
    assert "action_choices" not in got["systems"][0]
    assert raw == original


def test_client_only_completion_guards_actual_report_56_unrelated_repair_ui():
    raw = _trade_missing_client()
    wrong = {
        "client_behavior": (
            "Player opens a repair console UI and selects a damaged vehicle "
            "then pays credits to perform a mechanical repair."
        )
    }
    with pytest.raises(ValueError, match="unrelated user action"):
        apply_client_input_completion(raw, wrong, index=0)
    correct = {
        "client_behavior": (
            "The player opens a Trade panel, selects the item and amount "
            "to sell, and submits the trade request to the server."
        )
    }
    fixed = apply_client_input_completion(raw, correct, index=0)
    assert interaction_issues(fixed) == {}
    assert fixed["systems"][0]["client_behavior"] == correct["client_behavior"]
    for key in ("name", "server_behavior", "observable_result",
                "interaction", "input_mode", "world_entities"):
        assert fixed["systems"][0][key] == raw["systems"][0][key]
    assert raw["systems"][0]["client_behavior"] == ""


@pytest.mark.parametrize("bad", [
    {"client_behavior": "Trade animation appears"},
    {"client_behavior": "Trade player selects a resource", "world_entities": []},
    {"systems": [{"client_behavior": "Open trade"}]},
    {"client_behavior": ""},
])
def test_client_only_patch_cannot_change_contract_or_invent_ui(bad):
    with pytest.raises(ValueError):
        apply_client_input_completion(_trade_missing_client(), bad, index=0)


def test_client_only_output_for_full_architect_not_another_protocol_replan(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Trade earned game resources for credits"
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-trade", "statement": source}],
        "facets": [{
            "id": "intent-trade", "source_span": source,
            "requirements": ["req-trade"],
            "search_query": "Roblox Trade earned game resources for credits",
        }],
    }, "evidence": []}
    raw = _trade_missing_client()
    calls = []
    class Router:
        def complete_json(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            if len(calls) == 1:
                return deepcopy(raw)
            if len(calls) == 2:
                assert kwargs["json_schema"] == CLIENT_INPUT_ONLY_SCHEMA
                assert kwargs["max_tokens"] <= 260
                assert "original_source_requirement" in prompt
                # Original 15th-failure repair generated an unrelated UI.
                return {"client_behavior": (
                    "Player opens a repair console and selects a vehicle "
                    "repair item, then confirms the repair request."
                )}
            assert len(calls) == 3
            assert kwargs["json_schema"] == CLIENT_INPUT_ONLY_SCHEMA
            return {"client_behavior": (
                "Player opens the Trade window, selects their stored item "
                "and quantity, then submits the priced trade request."
            )}
    result = RobloxDynamicArchitect(Router()).design(
        source, research, [])
    assert len(calls) == 3
    assert any("transfer resources or credits" in m.description
               for m in result["modules"])
    assert all("repair console" not in m.description
               for m in result["modules"])
    assert research["architecture_attempts"][-1]["passed"]
