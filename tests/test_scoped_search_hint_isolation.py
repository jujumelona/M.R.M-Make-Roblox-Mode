"""Retrieval translations must never become executable source requirements."""
from __future__ import annotations

import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect


def _ledger(source: str, wrong_hint: str):
    return {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "req-001", "statement": source}],
        "facets": [{
            "id": "intent-001",
            "requirements": ["req-001"],
            "source_span": source,
            "search_query": wrong_hint,
        }],
    }, "evidence": []}


def test_translated_search_context_cannot_smuggle_unrequested_actions(
        monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Plant seeds in a garden"
    unowned = "Roblox buy expensive pet cosmetic skins and operate an item shop"
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append(prompt)
            assert unowned not in prompt, (
                "search-only wording is NOT an implementation requirement"
            )
            return {"systems": [{
                "name": "PlantSeed",
                "server_behavior": (
                    "The server validates the selected garden soil and "
                    "plants a seed into the plot, recording its growth state."
                ),
                "client_behavior": (
                    "The player picks a seed and selects the plot to plant in."
                ),
                "observable_result": (
                    "The garden plot visibly contains the newly planted seed."
                ),
                "interaction": "request_response",
                "input_mode": "custom",
                "world_entities": ["GardenPlot"],
            }]}
    model = Model()
    result = RobloxDynamicArchitect(model).design(
        source, _ledger(source, unowned), [])
    assert len(model.calls) == 1
    assert any("plants a seed" in m.description for m in result["modules"])
    assert all("pet cosmetic" not in m.description
               for m in result["modules"])


def test_replan_and_reviewer_use_original_not_poisoned_search_hint(
        monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_SOURCE_FIDELITY_AUDIT", "1")
    source = "Water the planted flowers so they grow"
    misleading_hint = "Roblox destroy player homes and purchase battle weapons"
    class Model:
        supports_source_fidelity_audit = True
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append(prompt)
            assert misleading_hint not in prompt
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "OtherGameAction",
                    "server_behavior": (
                        "The server sells an unrelated weapon and credits "
                        "the purchased item to the player's inventory."
                    ),
                    "client_behavior": (
                        "The client displays the unrelated shop purchase."
                    ),
                    "observable_result": (
                        "The inventory shows the newly purchased weapon."
                    ),
                    "interaction": "request_response", "input_mode": "custom",
                    "world_entities": [],
                }]}
            if len(self.calls) == 2:
                return {"covered": False, "server_quote": "",
                        "outcome_quote": "",
                        "missing": "Water the planted flowers to grow them"}
            if len(self.calls) == 3:
                assert "source_requirements" in prompt
                assert "original_request_context_only" in prompt
                return {"systems": [{
                    "name": "GardenFlowerWatering",
                    "server_behavior": (
                        "The server checks the targeted planted flowers, "
                        "waters them and updates their saved growth stage."
                    ),
                    "client_behavior": (
                        "The player selects planted flowers and applies water "
                        "through the garden watering interaction."
                    ),
                    "observable_result": (
                        "The targeted planted flowers visibly grow after "
                        "watering and advance to their next growth stage."
                    ),
                    "interaction": "request_response", "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert len(self.calls) == 4
            return {"covered": True,
                    "server_quote": "waters them and updates their saved growth stage",
                    "outcome_quote": "planted flowers visibly grow after watering",
                    "missing": ""}
    model = Model()
    result = RobloxDynamicArchitect(model).design(
        source, _ledger(source, misleading_hint), [])
    assert len(model.calls) == 4
    assert any("waters them" in m.description for m in result["modules"])
