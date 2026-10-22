"""Small-model failures must not erase already-good semantics in other fields."""
from copy import deepcopy

import pytest

from roblox_mod_ai.dynamic_architect import (
    RobloxDynamicArchitect, _SCOPED_SEMANTIC_REPAIR_SCHEMA,
)


PROMPT = "Fight alien enemies and colonize planets"
SOURCE = "Fight alien enemies and colonize planets"
SERVER_GOOD = (
    "The server validates attacks against hostile alien NPC enemies and "
    "applies enemy health damage. After successful colonization, it "
    "records the planet's owned persistent colony settlement state."
)
CLIENT_GOOD = (
    "The client renders server-confirmed alien enemy combat results, "
    "and displays the planet's colonization status after an action."
)
RESULT_GOOD = (
    "The player sees alien enemies take damage, and the planet becomes "
    "colonized with an established settlement after a valid request."
)


def _research():
    return {"ledger": {
        "original_prompt": PROMPT,
        "requirements": [
            {"id": "req-001", "statement": SOURCE, "source": "user_prompt"}
        ],
        "facets": [{
            "id": "intent-npc-colony", "requirements": ["req-001"],
            "source_span": SOURCE, "search_query": "Roblox NPC colony ownership",
        }],
    }, "evidence": []}


@pytest.mark.parametrize("failed_field,first,replacement", [
    ("observable_result",
     "The client shows alien combat feedback and a generic colony menu.",
     RESULT_GOOD),
    ("server_behavior",
     "The server validates each alien enemy combat hit and shows "
     "the current planet colony screen after client selection.",
     SERVER_GOOD),
])
def test_field_repair_preserves_correct_server_or_outcome(
        monkeypatch, failed_field, first, replacement):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")

    original = {"systems": [{
        "name": "AlienSettlement",
        "server_behavior": SERVER_GOOD,
        "client_behavior": CLIENT_GOOD,
        "observable_result": RESULT_GOOD,
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }]}
    original["systems"][0][failed_field] = first

    class MiniModel:
        def __init__(self):
            self.calls = []

        def complete_json(self, request, **options):
            self.calls.append((request, options))
            if len(self.calls) == 1:
                return deepcopy(original)
            assert len(self.calls) == 2, "Never regenerate the whole feature"
            assert options["json_schema"] == _SCOPED_SEMANTIC_REPAIR_SCHEMA
            assert '"field": "' + failed_field + '"' in request
            return {"replacement": replacement}

    model = MiniModel()
    audit = _research()
    final = RobloxDynamicArchitect(model).design(PROMPT, audit, [])
    assert len(model.calls) == 2
    assert len(final["modules"]) == 2
    servers = [m for m in final["modules"] if "Server" in m.name]
    assert len(servers) == 1
    assert (SERVER_GOOD if failed_field == "observable_result" else replacement) \
           in servers[0].description
    assert RESULT_GOOD in final["acceptance"]["req-001"]
    assert [row["passed"] for row in audit["architecture_attempts"]] == [
        False, True
    ]



def test_real_failure_47_colony_delta_cannot_erase_existing_alien_combat(
        monkeypatch):
    """The original successful NPC hit logic must survive a colony-only patch.

    In plan_failure_logs (7), the old replacement policy dropped alien combat
    on both retry 2 and retry 3 even though the initial JSON had working
    server-owned alien damage and weapon validation.
    """
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    initial_server = (
        "The server runs a space-mode gameplay loop where players fight aliens "
        "and colonize planets. The server owns all combat resolution, planet "
        "colonization state, and progression validation. When a player "
        "activates a combat action, the server validates the player's weapon "
        "and target, applies damage to the alien, and resolves the outcome. "
        "When a player activates a colonization action, the server validates "
        "the player's settlement progress and applies the colonization result. "
        "The server tracks player-owned resources, earned game currency, and "
        "progression state."
    )
    delta = (
        "The server records a colony as established only when the player's "
        "settlement progress reaches the required completion threshold, then "
        "transitions the colony from a label to an established colony state "
        "and confirms the settlement outcome to the player."
    )
    class Model:
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **options):
            self.calls.append((prompt, options))
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "AlienColonization",
                    "server_behavior": initial_server,
                    "client_behavior": (
                        "The client displays alien combat results and confirmed "
                        "changes to colonization progress after server actions."
                    ),
                    "observable_result": (
                        "The player sees alien enemies taking damage and the "
                        "planet becomes colonized after a successful mission."
                    ),
                    "interaction": "request_response", "input_mode": "custom",
                    "world_entities": [],
                }]}
            assert len(self.calls) == 2
            assert options["json_schema"] == _SCOPED_SEMANTIC_REPAIR_SCHEMA
            assert "server_behavior" in prompt
            return {"replacement": delta}
    model = Model()
    report = _research()
    result = RobloxDynamicArchitect(model).design(PROMPT, report, [])
    server = next(m for m in result["modules"] if "Server" in m.name)
    assert "applies damage to the alien" in server.description
    assert "validates the player's weapon" in server.description
    assert "records a colony as established" in server.description
    assert len(model.calls) == 2
    assert [row["passed"] for row in report["architecture_attempts"]] == [
        False, True
    ]


def test_semantic_repair_cannot_accept_an_unrelated_new_feature(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    class Model:
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **options):
            self.calls += 1
            if self.calls == 1:
                return {"systems": [{
                    "name": "Settlement",
                    "server_behavior": (
                        "The server validates an alien NPC combat hit and "
                        "opens the selected planet colonization menu."
                    ),
                    "client_behavior": (
                        "The client displays alien combat results and "
                        "shows the colony status panel after requests."
                    ),
                    "observable_result": RESULT_GOOD,
                    "interaction": "request_response", "input_mode": "custom",
                    "world_entities": [],
                }]}
            return {"replacement": (
                "The game displays a victory animation after trading Robux "
                "with other players without needing to persist a settlement."
            )}
    from roblox_mod_ai.dynamic_architect import DynamicDesignError
    model = Model()
    with pytest.raises(DynamicDesignError):
        RobloxDynamicArchitect(model).design(PROMPT, _research(), [])
