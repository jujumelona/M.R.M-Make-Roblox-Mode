"""Plan 67: local T4 GGUF truncated a 600-token one-system JSON twice.

Host transport must generate separate short server/outcome fields, and the
verified first child must survive a later child's truncated completion.
"""
from copy import deepcopy
import pytest

from roblox_mod_ai import atomic_action_authoring as atomic
from roblox_mod_ai.compact_atomic_authoring import author_compact_atomic_system


class _ShortRouter:
    supports_host_standard_transport = True

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, deepcopy(kwargs)))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def _short_server(name):
    return {
        "name": name,
        "server_behavior": (
            "Server checks the action and updates the actual resource "
            "inventory on a validated input, rejecting invalid requests."
        ),
        "world_entities": ["ResourceNode"],
    }


def _outcome():
    return {
        "observable_result": (
            "The resource node is depleted and the inventory visibly grows."
        ),
    }


def _actions():
    return [
        {"source_quote": "채굴", "action": "Collect real resources"},
        {"source_quote": "거래", "action": "Trade collected resources"},
    ]


def _schema():
    return {"type": "object", "properties": {"systems": {
        "type": "array", "maxItems": 3,
        "items": {"type": "object"},
    }}, "required": ["systems"]}


def test_compact_host_calls_cannot_request_600_token_atomic_envelopes():
    router = _ShortRouter([_short_server("GatherOre"), _outcome()])
    result = author_compact_atomic_system(
        router, _actions()[0], previous_issues={},
    )
    assert result["name"] == "GatherOre"
    assert len(router.calls) == 2
    assert [kwargs["max_tokens"] for _, kwargs in router.calls] == [360, 190]
    assert set(router.calls[0][1]["json_schema"]["required"]) == {
        "name", "server_behavior", "world_entities",
    }
    assert router.calls[1][1]["json_schema"]["required"] == ["observable_result"]


def test_truncated_later_action_does_not_regenerate_verified_sibling(monkeypatch):
    monkeypatch.setattr(atomic, "_field_issues", lambda *_args: {})
    monkeypatch.setattr(
        atomic, "validate_atomic_system_ownership",
        lambda *_args, **_kwargs: None,
    )
    retained = {}
    router = _ShortRouter([
        _short_server("GatherOre"), _outcome(),
        ValueError("Model JSON completion truncated (finish_reason=length)"),
        ValueError("Model JSON completion truncated (finish_reason=length)"),
        ValueError("Model JSON completion truncated (finish_reason=length)"),
        _short_server("SellOre"), _outcome(),
    ])
    with pytest.raises(atomic.SourceActionBindingError,
                       match="ATOMIC_LOCAL_REPAIR_EXHAUSTED"):
        atomic.author_verified_atomic_systems(
            router, _actions(), source_clause="채굴 거래",
            original_prompt="채굴 거래", json_schema=_schema(),
            retained_verified=retained,
        )
    assert ("채굴", "Collect real resources") in retained
    assert len(router.calls) == 5

    authored = atomic.author_verified_atomic_systems(
        router, _actions(), source_clause="채굴 거래",
        original_prompt="채굴 거래", json_schema=_schema(),
        retained_verified=retained,
    )
    assert [s["name"] for s in authored] == ["GatherOre", "SellOre"]
    assert len(router.calls) == 7, "Already verified child must not be regenerated"


def test_non_host_model_keeps_original_single_action_schema(monkeypatch):
    monkeypatch.setattr(atomic, "_field_issues", lambda *_args: {})
    monkeypatch.setattr(
        atomic, "validate_atomic_system_ownership",
        lambda *_args, **_kwargs: None,
    )
    class Legacy(_ShortRouter):
        supports_host_standard_transport = False

    router = Legacy([{
        "systems": [{
            "name": "OnlyAction",
            "server_behavior": "Server authoritatively creates a new world state.",
            "observable_result": "The player sees the modified game state.",
            "world_entities": [],
        }],
    }])
    results = atomic.author_verified_atomic_systems(
        router, [_actions()[0]],
        source_clause="채굴", original_prompt="채굴",
        json_schema=_schema(),
    )
    assert len(results) == 1
    assert len(router.calls) == 1
    systems = router.calls[0][1]["json_schema"]["properties"]["systems"]
    assert systems["maxItems"] == 1
