"""Regression for multi-action facets and planner world reference normalization.

Different game domains share identical source-ownership and host schema rules.
"""
from __future__ import annotations

from copy import deepcopy
import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.semantic_world_entities import normalize_world_names
from roblox_mod_ai.host_architecture import HostArchitectureError, expand_semantic_facet


def _proposal(game: str):
    return {"ledger": {
        "original_prompt": game,
        "requirements": [{"id": "req-1", "statement": game}],
        "facets": [{"id": "intent-1", "requirements": ["req-1"],
                    "source_span": game,
                    "search_query": "Roblox fight alien enemies and colonize planets"}],
    }, "evidence": []}


def _system(name: str, server: str, outcome: str, client: str):
    return {
        "name": name,
        "server_behavior": server,
        "client_behavior": client,
        "observable_result": outcome,
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }


def test_host_normalizes_named_world_metadata_but_never_engine_geometry():
    original = {"systems": [{
        "name": "CreatureEncounter",
        "world_entities": [{
            "name": "HostileNPC",
            "type": "NPC",
            "state": "active",
            "damage": "hostile",
            "health": "finite",
        }],
    }]}
    normalized, changed = normalize_world_names(original)
    assert changed == [(0, 0)]
    assert normalized["systems"][0]["world_entities"] == ["HostileNPC"]
    assert original["systems"][0]["world_entities"][0]["state"] == "active"

    invalid = {"systems": [{
        "name": "Ground",
        "world_entities": [{"name": "Ground", "position": [1, 2, 3]}],
    }]}
    untouched, changed = normalize_world_names(invalid)
    assert changed == []
    assert untouched is invalid


def test_real_host_still_refuses_engine_geometry_from_model():
    wrong = {"systems": [{
        "name": "WorldObject",
        "server_behavior": "The server spawns and tracks a player-owned world object safely.",
        "client_behavior": "The player sees the world object in the game.",
        "observable_result": "The generated object is visible in the player's world.",
        "interaction": "none",
        "world_entities": [{"name": "Tree", "position": [1, 2, 3]}],
    }]}
    cleaned, _ = normalize_world_names(wrong)
    with pytest.raises(HostArchitectureError, match="world_entities"):
        expand_semantic_facet(
            cleaned, facet_id="facet-1",
            requirement_ids=["req-1"],
            source_requirements=[{"id": "req-1", "statement": "World object"}],
            reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
        )


def test_independent_source_actions_use_bounded_host_verified_subtasks(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Fight alien enemies and colonize planets"
    class Model:
        supports_atomic_action_decomposition = True
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append((prompt, options))
            n = len(self.calls)
            if n == 1:
                return {"systems": [_system(
                    "UnrelatedDecoration",
                    "The server validates a cosmetic purchase and records a purchased skin.",
                    "The player receives a purchased avatar decoration.",
                    "The client displays a cosmetic catalog and its purchases.",
                )]}
            if n == 2:
                assert "source_quote" in prompt
                assert "coverage_failures" in prompt
                assert options["max_tokens"] <= 400
                return {"actions": [
                    {"source_quote": "Fight alien enemies",
                     "action": "Fight and damage hostile alien enemies"},
                    {"source_quote": "colonize planets",
                     "action": "Establish and own settlements on planets"},
                ]}
            if n == 3:
                assert "this_action" in prompt
                assert "Fight and damage" in prompt
                return {"systems": [_system(
                    "AlienCombat",
                    "The server checks the attack range, then attacks a "
                    "hostile alien enemy NPC, reduces its health and records defeat.",
                    "The alien enemy loses health and is defeated after attacks.",
                    "The player attacks a hostile alien enemy and sees damage.",
                )]}
            assert n == 4
            assert "Establish and own settlements" in prompt
            return {"systems": [_system(
                "PlanetColonization",
                "The server verifies supplies then establishes a new planet "
                "colony and records the player's ownership of the settlement.",
                "The planet becomes colonized, showing newly established colony ownership.",
                "The player requests the establishment of a colony on a planet.",
            )]}
    model = Model()
    result = RobloxDynamicArchitect(model).design(source, _proposal(source), [])
    assert len(model.calls) == 4
    assert len(result["modules"]) >= 4
    assert any("alien enemy" in m.description for m in result["modules"])
    assert any("establishes a new planet colony" in m.description for m in result["modules"])
    assert all("cosmetic purchase" not in m.description for m in result["modules"])


def test_atomic_action_decomposition_rejects_fabricated_quotations(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "Fight alien enemies and colonize planets"
    class Model:
        supports_atomic_action_decomposition = True
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return {"systems": [_system(
                    "DecorationShop",
                    "The server validates and saves cosmetic purchases.",
                    "Player receives the purchased cosmetic.",
                    "The client opens cosmetic shop choices.",
                )]}
            return {"actions": [
                {"source_quote": "Fight alien enemies",
                 "action": "Attack and defeat alien enemies"},
                {"source_quote": "buy premium robot pets",
                 "action": "Purchase robot pets"},
            ]}
    model = Model()
    with pytest.raises(Exception, match="could not be validated"):
        RobloxDynamicArchitect(model).design(source, _proposal(source), [])
    # Every invalid quotation now triggers a bounded source-ID binding
    # decision rather than letting the model invent a replacement quote.
    # The unrequested robot-pet action is still rejected in every attempt.
    assert len(model.calls) == 5
    assert sum(call.startswith("SOURCE OWNERSHIP ONLY")
               for call in model.calls) == 2



def test_report21_korean_compound_facets_reach_real_gameplay_modules_from_source_ids(monkeypatch):
    """Run the real architect path for the uploaded two-mechanic Korean clause.

    A scripted planner simulates the original partial first attempt. This is
    an architecture integration test, NOT a claim of local-LLM/Studio success.
    """
    import json
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "외게인과 싸움 식민지화등 여러가지가 가능한 모드"

    class IndexedModel:
        supports_atomic_action_decomposition = True

        def __init__(self):
            self.calls = []

        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            n = len(self.calls)
            if n == 1:
                # A menu/mode label is neither NPC combat nor a colony
                # transition. It must be replanned.
                return {"systems": [_system(
                    "Colonization mode",
                    "The server validates and enters colonization mode.",
                    "The player sees the colonization mode screen.",
                    "The client shows a colony mode button.",
                )]}
            if n == 2:
                assert "source_id" in prompt
                payload = json.loads(prompt.split("\n")[-1])
                choices = {row["quote"]: row["id"]
                           for row in payload["candidate_source_spans"]}
                return {"actions": [
                    {"source_id": choices["외게인과 싸움"],
                     "action": "Fight hostile alien NPC enemies"},
                    {"source_id": choices["식민지화등"],
                     "action": "Establish a planet colony and record ownership"},
                ]}
            if n == 3:
                assert "Fight hostile alien" in prompt
                return {"systems": [_system(
                    "AlienCombat",
                    "The server verifies attack range then damages hostile "
                    "alien enemies, reducing NPC health and recording defeat.",
                    "The alien enemy loses health and is defeated in combat.",
                    "Player fights and damages alien enemy NPCs.",
                )]}
            assert n == 4
            assert "record ownership" in prompt
            return {"systems": [_system(
                "PlanetColonization",
                "The server checks colony resources then establishes the "
                "new planet colony and records ownership in world state.",
                "The planet becomes colonized and new colony ownership is visible.",
                "Player selects a planet to establish a settlement.",
            )]}

    model = IndexedModel()
    result = RobloxDynamicArchitect(model).design(source, _proposal(source), [])
    assert len(model.calls) == 4
    assert any("alien" in module.description.casefold()
               for module in result["modules"])
    assert any("colony" in module.description.casefold()
               for module in result["modules"])
    assert all("colonization mode screen" not in module.description.casefold()
               for module in result["modules"])
