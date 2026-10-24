"""Plan 69: malformed one-field repairs must not abort a whole feature.

The submitted failure log had ATOMIC_LOCAL_REPAIR_INVALID: 1:
server_behavior on consecutive facet retries. Regression ensures the host
retains the first verified action and generates ONLY the defective sibling.
"""
from copy import deepcopy
import pytest
from roblox_mod_ai import atomic_action_authoring as atomic


class FakeShortRouter:
    supports_host_standard_transport = True
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete_json(self, prompt, *, json_schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": deepcopy(json_schema),
                           "max_tokens": kwargs.get("max_tokens")})
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def server(name):
    return {
        "name": name,
        "server_behavior": (
            "Server verifies the requested source-owned action and records "
            "a visible update in the player's authoritative world state."
        ),
        "world_entities": ["Item"],
    }


def result():
    return {
        "observable_result": (
            "The world state visibly changes and the inventory reflects it."
        ),
    }


def actions():
    return [
        {"source_quote": "자원파밍", "action": "Harvest resources"},
        {"source_quote": "돈모으기", "action": "Earn currency"},
    ]


def schema():
    return {
        "type": "object",
        "properties": {"systems": {
            "type": "array", "maxItems": 3,
            "items": {"type": "object"},
        }},
        "required": ["systems"],
    }


def _mock_semantics(monkeypatch):
    # Intentionally isolate response-shape control flow from source
    # vocabulary. Field validation is represented by a deterministic
    # rejection of the initial second action only.
    def field_issues(action, proposal, source):
        if proposal.get("name") == "BadEarn":
            return {"server_behavior": [
                "SOURCE_CURRENCY_EARNING_MISSING: money must be earned",
            ]}
        return {}

    monkeypatch.setattr(atomic, "_field_issues", field_issues)
    monkeypatch.setattr(atomic, "validate_atomic_system_ownership",
                        lambda *_args, **_kwargs: None)


@pytest.mark.parametrize("bad_patch", [
    {"unexpected": "no server_behavior field"},
    {"server_behavior": None},
    {"server_behavior": "x"},
])
def test_invalid_short_field_patch_retries_only_bad_action(
        monkeypatch, bad_patch):
    _mock_semantics(monkeypatch)
    router = FakeShortRouter([
        server("HarvestOre"), result(),
        server("BadEarn"), result(),
        bad_patch,
        server("GoodEarn"), result(),
    ])
    retained = {}
    produced = atomic.author_verified_atomic_systems(
        router, actions(), source_clause="자원파밍 돈모으기",
        original_prompt="자원파밍 돈모으기", json_schema=schema(),
        retained_verified=retained,
    )
    assert [s["name"] for s in produced] == ["HarvestOre", "GoodEarn"]
    assert len(router.calls) == 7
    assert retained[(actions()[0]["source_quote"], actions()[0]["action"])]["name"] == "HarvestOre"
    assert retained[(actions()[1]["source_quote"], actions()[1]["action"])]["name"] == "GoodEarn"
    patch_request = router.calls[4]
    assert patch_request["max_tokens"] == 280
    assert patch_request["schema"]["properties"]["server_behavior"]["maxLength"] == 450
    assert patch_request["schema"]["additionalProperties"] is False
    assert "Invalid or repeated server_behavior patch" in router.calls[5]["prompt"]


def test_repeated_same_field_is_not_counted_as_progress(monkeypatch):
    _mock_semantics(monkeypatch)
    bad = server("BadEarn")
    router = FakeShortRouter([
        server("HarvestOre"), result(),
        bad, result(),
        {"server_behavior": bad["server_behavior"]},
        server("GoodEarn"), result(),
    ])
    output = atomic.author_verified_atomic_systems(
        router, actions(), source_clause="자원파밍 돈모으기",
        original_prompt="자원파밍 돈모으기", json_schema=schema(),
    )
    assert [s["name"] for s in output] == ["HarvestOre", "GoodEarn"]


def test_invalid_repair_recovers_prior_sibling_next_facet_try(monkeypatch):
    _mock_semantics(monkeypatch)
    router = FakeShortRouter([
        server("HarvestOre"), result(),
        server("BadEarn"), result(),
        {"unexpected": "missing"},
        ValueError("model truncated"),
        server("GoodEarn"), result(),
    ])
    retained = {}
    with pytest.raises(atomic.SourceActionBindingError, match="ATOMIC_LOCAL_REPAIR_EXHAUSTED"):
        atomic.author_verified_atomic_systems(
            router, actions(), source_clause="자원파밍 돈모으기",
            original_prompt="자원파밍 돈모으기", json_schema=schema(),
            retained_verified=retained,
        )
    assert len(retained) == 1
    output = atomic.author_verified_atomic_systems(
        router, actions(), source_clause="자원파밍 돈모으기",
        original_prompt="자원파밍 돈모으기", json_schema=schema(),
        retained_verified=retained,
    )
    assert [s["name"] for s in output] == ["HarvestOre", "GoodEarn"]
    assert len(router.calls) == 8, "Accepted sibling must not be reauthored"



def test_plan69_duplicate_craft_builders_do_not_take_two_candidate_slots():
    from roblox_mod_ai.source_action_aggregation import (
        collect_source_action_candidates,
    )
    source = (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
        "우주선을 부위마다 만들어서 만들수있고"
    )
    a = {
        "name": "Craft section construction",
        "server_behavior": (
            "Server validates the player's requested section type and required "
            "resources before creating a new craft section; it rejects invalid "
            "section types, missing resources, and duplicate sections, then "
            "adds the approved section to the craft's server-owned section list "
            "and updates the craft's state."
        ),
        "observable_result": (
            "The craft visibly gains the newly constructed section in place, "
            "with its parts grouped into the craft model."
        ),
        "world_entities": ["craft"],
    }
    b = {
        "name": "Section-by-section craft construction",
        "server_behavior": (
            "Server validates each requested section against the craft's "
            "current state and rejects invalid or incomplete construction; "
            "on success it adds the section to the craft's server-owned section "
            "list and updates the craft's state."
        ),
        "observable_result": a["observable_result"],
        "world_entities": ["craft"],
    }
    retained = collect_source_action_candidates(
        [], [a, b], original_request=source,
    )
    assert retained == [a], "Near-identical same-state builders are one action"


def test_same_world_different_observable_effects_are_retained():
    from roblox_mod_ai.source_action_aggregation import (
        collect_source_action_candidates,
    )
    a = {
        "name": "Gather Ore",
        "server_behavior": (
            "Server validates a resource node's availability, mines ore "
            "from that node and credits it to the player's inventory."
        ),
        "observable_result": "The node visibly depletes and owned ore increases.",
        "world_entities": ["OreNode"],
    }
    b = {
        "name": "Build From Ore",
        "server_behavior": (
            "Server validates the player's ore inventory and owned craft, "
            "consumes materials, and adds a built section to the craft."
        ),
        "observable_result": "The craft visibly gains a new physical part.",
        "world_entities": ["OreNode"],
    }
    pool = collect_source_action_candidates(
        [], [a, b],
        original_request="자원파밍 우주선을 부위마다 만들어서 만들수있고",
    )
    assert pool == [a, b]
