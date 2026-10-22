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
    assert final["acceptance"]["req-001"] == RESULT_GOOD
    assert [row["passed"] for row in audit["architecture_attempts"]] == [
        False, True
    ]
