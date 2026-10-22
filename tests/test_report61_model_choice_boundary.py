"""Uploaded proposal (61), plan_failure_logs (20): input option strings are
untrusted local-model metadata, never a reason to discard gameplay.
This file tests production semantics with multiple unrelated game genres.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from roblox_mod_ai.host_architecture import (
    HOST_OWNED_SEMANTIC_FACET_SCHEMA, expand_semantic_facet,
)
from roblox_mod_ai.typed_action_contract import (
    host_owned_action_contract, validated_host_choice_options,
    validate_contract, lua_server_guard,
)
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect


@pytest.mark.parametrize("raw", [
    ["Harvest"],
    ["Harvest Resource"],
    [None],
    [{"label": "Harvest"}],
    [{"id": "Harvest", "label": "Harvest", "remote": "Exploit"}],
    [{"id": "Harvest", "label": ""}],
    [{"id": "Harvest", "label": "Harvest"},
     {"id": "Harvest", "label": "Collect"}],
    {"Harvest": "Resource"},
    [{"id": "Attack", "label": "Attack"}] * 9,
])
def test_untrusted_local_model_selection_never_becomes_remote_allowlist(raw):
    assert validated_host_choice_options(raw) == []
    contract = host_owned_action_contract(raw)
    assert contract["inputs"][0] == {
        "id": "selection",
        "label": "Item, action, or target ID",
        "type": "text",
    }
    checked = validate_contract(contract, world_entities=[], transport_only=True)
    guard = lua_server_guard(checked)
    assert 'type(actionArgs["selection"]) ~= "string"' in guard
    assert '"Harvest"] = true' not in guard


def test_valid_legacy_choices_are_preserved_without_forging_ids():
    choices = [
        {"id": "Collect", "label": "Collect"},
        {"id": "Sell", "label": "Sell goods"},
    ]
    original = deepcopy(choices)
    contract = host_owned_action_contract(choices)
    assert contract["inputs"][0]["type"] == "choice"
    assert [x["id"] for x in contract["inputs"][0]["options"]] == [
        "Collect", "Sell",
    ]
    assert choices == original


@pytest.mark.parametrize("name,source,server,outcome,malformed", [
    ("CrystalHarvest", "Harvest crystals",
     "Server checks crystal node stock and harvest permission, consumes "
     "a unit of node stock and increases the player's crystal inventory.",
     "The node visually depletes and the crystal inventory count increases.",
     ["Harvest"]),
    ("CropWatering", "Water crops",
     "Server validates available water and owned crop, subtracts water "
     "from inventory and updates crop growth progress.",
     "Crops visibly grow and the water balance decreases.",
     ["Water Crops"]),
    ("MerchantSale", "Sell collected goods",
     "Server verifies item ownership and server-owned sale rate, removes "
     "the items and increases the player's earned credits.",
     "Inventory shrinks and earned credit balance visibly increases.",
     ["Sell"]),
])
def test_local_model_malformed_options_do_not_regenerate_gameplay(
        monkeypatch, name, source, server, outcome, malformed):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    research = {"ledger": {
        "original_prompt": source,
        "requirements": [{"id": "r-1", "statement": source}],
        "facets": [{
            "id": "f-1", "source_span": source, "requirements": ["r-1"],
            "search_query": "Roblox " + source,
        }],
    }, "evidence": []}

    class Model:
        supports_host_standard_transport = True
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            assert self.calls == 1, "No retry on model-authored optional UI metadata"
            assert kwargs["json_schema"] == HOST_OWNED_SEMANTIC_FACET_SCHEMA
            assert "action_choices" not in kwargs["json_schema"][
                "properties"]["systems"]["items"]["properties"]
            return {"systems": [{
                "name": name, "server_behavior": server,
                "observable_result": outcome, "world_entities": [],
                # Some local backends do not strictly enforce nested object
                # grammar; the host must ignore these untrusted option strings.
                "action_choices": malformed,
            }]}
    router = Model()
    result = RobloxDynamicArchitect(router).design(source, research, [])
    assert router.calls == 1
    assert len(result["host_typed_actions"]) == 1
    action = next(iter(result["host_typed_actions"].values()))
    assert action["contract"]["inputs"][0]["type"] == "text"
    assert action["contract"]["state_changes"] == []
    assert research["architecture_attempts"][0]["passed"] is True
    assert not research["architecture_attempts"][0]["typed_contract_attempts"]
    discarded = research["architecture_attempts"][0]["discarded_ui_choices"]
    assert len(discarded) == 1
    assert discarded[0]["fallback"] == "typed_text_selection"
    assert discarded[0]["reason"] == "untrusted_model_choice_format"


def test_exact_report61_harvest_option_strings_cannot_poison_host_contract():
    # The real failure happened after the host had already created a typed
    # action manifest from a source-owned harvesting system. No LLM retry can
    # repair this: validate the producer and complete host expansion instead.
    system = {
        "name": "Resource Harvesting",
        "server_behavior": (
            "Server validates that the player is in Space Mode and that the "
            "target resource object is within the permitted harvest range "
            "before accepting the harvest action; it then changes the "
            "resource's collected state and grants the player's resource "
            "count, rejecting depleted or out-of-range objects."
        ),
        "observable_result": (
            "The targeted resource visibly depletes and the player's "
            "resource total increases."
        ),
        "world_entities": ["resource object"],
        "client_behavior": "Host-owned typed action form sends validated input.",
        "input_mode": "custom", "interaction": "request_response",
        "host_standard_transport": True,
        "action_contract": host_owned_action_contract(["Harvest"]),
    }
    # Unlike report-61, host_owned_action_contract never creates a
    # malformed list of strings under a 'choice' input.
    expanded = expand_semantic_facet(
        {"systems": [system]}, facet_id="facet-1",
        requirement_ids=["req-1"],
        source_requirements=[{
            "id": "req-1", "statement": "Harvest a resource object",
        }],
        reserved_modules=set(), reserved_remotes=set(),
        reserved_objects=set(),
    )
    assert expanded["_host_typed_actions"]
    bound = next(iter(expanded["_host_typed_actions"].values()))
    assert bound["contract"]["inputs"][0]["type"] == "text"
