"""Generic regression tests for the typed interaction/input routing boundary.

Covers the reported swapped-enum failure and an unrelated interaction so a
single gameplay prompt cannot special-case the implementation.
"""
from __future__ import annotations

from copy import deepcopy
import pytest

from roblox_mod_ai.semantic_input_contract import (
    canonicalize_interaction_fields, interaction_issues, apply_interaction_patch,
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
