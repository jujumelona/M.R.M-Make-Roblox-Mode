"""Regression tests for source-owned atomic planner response shape.

The tests isolate the transport/repair contract from semantic validators, so
the failure that occurred in proposal (64) can be reproduced without a GGUF.
"""
from copy import deepcopy

import pytest

from roblox_mod_ai import atomic_action_authoring as atomic


class _Router:
    def __init__(self, responses):
        self.responses = list(responses)
        self.schemas = []
        self.prompts = []

    def complete_json(self, prompt, *, json_schema, **kwargs):
        self.prompts.append(prompt)
        self.schemas.append(deepcopy(json_schema))
        return self.responses.pop(0)


def _action(label):
    return {"source_quote": label, "action": label}


def _valid(name):
    return {"systems": [{
        "name": name,
        "server_behavior": "The authoritative server changes the game state.",
        "observable_result": "The player sees the changed game world state.",
        "world_entities": [],
    }]}


def _schema():
    return {
        "type": "object",
        "properties": {"systems": {
            "type": "array", "maxItems": 3,
            "items": {"type": "object"},
        }},
        "required": ["systems"],
    }


@pytest.fixture(autouse=True)
def _focus_on_wire_format(monkeypatch):
    monkeypatch.setattr(atomic, "_field_issues", lambda *args: {})
    monkeypatch.setattr(
        atomic, "validate_atomic_system_ownership",
        lambda actions, systems, **kwargs: None,
    )


def test_retries_invalid_format_without_losing_accepted_sibling():
    router = _Router([
        _valid("First"),
        {"systems": [_valid("ExtraA")["systems"][0],
                     _valid("ExtraB")["systems"][0]]},
        _valid("Second"),
    ])
    shared_schema = _schema()
    systems = atomic.author_verified_atomic_systems(
        router, [_action("First"), _action("Second")],
        source_clause="First and second", original_prompt="First and second",
        json_schema=shared_schema,
    )
    assert [row["name"] for row in systems] == ["First", "Second"]
    assert len(router.prompts) == 3
    assert all(schema["properties"]["systems"]["minItems"] == 1
               for schema in router.schemas)
    assert all(schema["properties"]["systems"]["maxItems"] == 1
               for schema in router.schemas)
    assert shared_schema["properties"]["systems"]["maxItems"] == 3
    assert "minItems" not in shared_schema["properties"]["systems"]


def test_rejects_repeated_non_atomic_response_instead_of_taking_first_system():
    wrong = {"systems": [
        _valid("WrongA")["systems"][0],
        _valid("WrongB")["systems"][0],
    ]}
    router = _Router([wrong, deepcopy(wrong)])
    with pytest.raises(atomic.SourceActionBindingError,
                       match="ATOMIC_LOCAL_REPAIR_NO_PROGRESS"):
        atomic.author_verified_atomic_systems(
            router, [_action("Alien combat")],
            source_clause="Alien combat", original_prompt="Alien combat",
            json_schema=_schema(),
        )


def test_retry_after_wrong_root_key_stays_local():
    router = _Router([
        {"actions": [{"action": "Harvest minerals"}]},
        _valid("Harvest Minerals"),
    ])
    systems = atomic.author_verified_atomic_systems(
        router, [_action("Harvest minerals")],
        source_clause="Harvest minerals",
        original_prompt="Harvest minerals", json_schema=_schema(),
    )
    assert len(systems) == 1
    assert systems[0]["name"] == "Harvest Minerals"
    assert len(router.prompts) == 2
