"""Prevent source-ledger ID coverage from falsifying the requested combat target.

In proposal(9), the user said "외게인과 싸움" (fight aliens), but the
architect produced HostileMineral/FightMineral. A facet ID alone had marked
that as fully implemented, which would silently build the wrong game.
"""
import copy

import pytest

from roblox_mod_ai.dynamic_architect import (
    _clean_model_json, RobloxDynamicArchitect, DynamicDesignError,
)


def _space_contract():
    prompt = "다른행성의 특수 광물 채굴하고 외게인과 싸움"
    ledger = {
        "original_prompt": prompt,
        "requirements": [
            {"id": "req-001", "statement": prompt, "source": "user_prompt"}
        ],
        "facets": [{
            "id": "intent-space", "source_span": prompt,
            "requirements": ["req-001"],
        }],
        "atomic_intents": [{
            "facet_id": "intent-space", "source_span": prompt,
            "requirement_id": "req-001", "intent": "Mine alien ores and fight aliens",
        }],
        "decomposition_method": "source_anchored_model",
    }
    bad = {
        "modules": [
            {"name": "SpecialMineralExtractor", "role": "server",
             "requirement_ids": ["req-001"], "facet_ids": ["intent-space"],
             "behavior": "Validate special ore harvesting at nearby planet nodes."},
            {"name": "HostileMineral", "role": "server",
             "requirement_ids": ["req-001"], "facet_ids": ["intent-space"],
             "behavior": "Hostile mineral combat tracking damage, health, and defeat outcomes."},
            {"name": "ClientInputBridge", "role": "client",
             "requirement_ids": ["req-001"], "facet_ids": ["intent-space"],
             "behavior": "Client input bridge sends actions through remotes to the server."}
        ],
        "remotes": [{"name": "ExtractMineral", "type": "RemoteEvent"},
                    {"name": "FightMineral", "type": "RemoteEvent"}],
        "world_objects": [],
        "acceptance": [{
            "requirement_id": "req-001",
            "observable_result": "Players harvest ore and fight hostile minerals"
        }],
        "acceptance_facets": [{
            "facet_id": "intent-space",
            "observable_result": "Harvest special ore and fight hostile minerals"
        }],
    }
    return ledger, bad


def test_original_alien_request_cannot_be_replaced_by_fighting_rocks():
    ledger, bad = _space_contract()
    with pytest.raises(DynamicDesignError, match="ALIEN ENEMIES"):
        _clean_model_json(bad, ledger, set())


def test_alien_enemy_server_subsystem_restores_original_requested_gameplay():
    ledger, bad = _space_contract()
    corrected = copy.deepcopy(bad)
    corrected["modules"][1]["name"] = "AlienCombat"
    corrected["modules"][1]["behavior"] = (
        "Server-authoritative combat against alien NPC enemies, validating "
        "weapon reach and damage with health and defeat rewards."
    )
    corrected["remotes"][1]["name"] = "FightAlien"
    corrected["acceptance"][0]["observable_result"] = (
        "Players harvest special minerals and fight alien NPC enemies."
    )
    corrected["acceptance_facets"][0]["observable_result"] = (
        "Special ore is harvested and alien enemies can be defeated with weapons."
    )
    design = _clean_model_json(corrected, ledger, set())
    assert len(design["modules"]) == 3
    assert "FightAlien" in design["remotes"]
    assert any(m.name == "AlienCombat" for m in design["modules"])


def test_architecture_agent_repairs_misread_combat_target_without_losing_mining(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    ledger, bad = _space_contract()

    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append(prompt)
            design = copy.deepcopy(bad)
            if len(self.calls) > 1:
                assert "ALIEN ENEMIES" in prompt
                assert "Previous JSON:" in prompt
                design["modules"][1]["name"] = "AlienCombat"
                design["modules"][1]["behavior"] = (
                    "Server validates real alien NPC enemy damage and combat rewards."
                )
                design["remotes"][1]["name"] = "FightAlien"
            return design
    model = Model()
    output = RobloxDynamicArchitect(router=model).design(
        ledger["original_prompt"],
        {"ledger": ledger, "evidence": [], "reuse_candidates": []},
        [],
    )
    assert len(model.calls) == 2
    assert any(m.name == "AlienCombat" for m in output["modules"])
    assert any(m.name == "SpecialMineralExtractor" for m in output["modules"])
