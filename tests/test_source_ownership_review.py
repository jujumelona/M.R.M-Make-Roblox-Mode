"""Real plan-54 lexical-ownership tie, plus unrelated-game control cases.

The fallback is a general semantic evidence boundary, not a game-specific
trade/shop exception. It must not blindly accept user-unrequested mechanics.
"""
from __future__ import annotations

from copy import deepcopy
import pytest

from roblox_mod_ai.source_ownership_review import (
    SOURCE_OWNERSHIP_REVIEW_SCHEMA,
    SourceOwnershipReviewError, ground_source_ownership,
)
from roblox_mod_ai.facet_scope import scope_semantic_systems
from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect


def _system(name, verb, effect):
    return {
        "name": name,
        "server_behavior": (
            "The server checks ownership and a valid request, then " + verb
            + " and records the authoritative state transition."
        ),
        "client_behavior": (
            "The player selects an item and quantity in a client panel, "
            "sends a request and sees the confirmed updated status."
        ),
        "observable_result": (
            "The client displays the confirmed " + effect
            + " with an updated inventory and balance."
        ),
        "interaction": "request_response",
        "input_mode": "custom",
        "world_entities": [],
    }


def _source_facets():
    return [
        {
            "id": "scope-trade", "requirements": ["req-trade"],
            "source_span": "거래 등으로",
            "search_query": "Roblox Trade to build sections, upgrade weapons",
        },
        {
            "id": "scope-equipment", "requirements": ["req-equipment"],
            "source_span": "무기 선원 우주선 성능을 거래",
            "search_query": "Roblox Trade weapon, crew and vehicle performance",
        },
    ]


def _source_draft():
    return {"systems": [
        _system("Server-Validated Trade Purchase",
                "transfers the purchased item to the inventory",
                "successful in-game item purchase"),
        _system("Server-Validated Trade Sale",
                "transfers the sold resource out of inventory",
                "successful in-game resource sale"),
        _system("Server-Validated Trade Offer",
                "records an unsolicited peer-to-peer offer",
                "pending offer to an unrelated player"),
    ]}


def _review(raw):
    return {"bindings": [
        {
            "index": i, "owned": i != 2,
            "source_quote": "거래" if i != 2 else "",
            "server_quote": ("The server checks ownership and a valid request"
                             if i != 2 else ""),
        }
        for i in range(len(raw["systems"]))
    ]}


def test_report_54_all_three_model_systems_are_unattributed_by_lexical_policy():
    facets = _source_facets()
    with pytest.raises(ValueError, match="SCOPED_SYSTEM_UNATTRIBUTED"):
        scope_semantic_systems(_source_draft(), facet=facets[0], all_facets=facets)


def test_review_preserves_only_grounded_trade_actions_without_modifying_rules():
    draft = _source_draft()
    original = deepcopy(draft)
    scoped, excluded = ground_source_ownership(
        draft, _review(draft), source_clause="거래 등으로")
    assert [x["name"] for x in scoped["systems"]] == [
        "Server-Validated Trade Purchase", "Server-Validated Trade Sale",
    ]
    assert excluded == ["Server-Validated Trade Offer"]
    assert draft == original
    assert scoped["systems"][0] == original["systems"][0]


@pytest.mark.parametrize("mutation", [
    lambda r: r["bindings"][0].update(source_quote="not original"),
    lambda r: r["bindings"][1].update(server_quote="irrelevant invented testimony"),
    lambda r: r["bindings"][0].update(index=1),
    lambda r: r["bindings"][0].update(owned="true"),
])
def test_review_never_accepts_ungrounded_or_ambiguous_model_self_certification(mutation):
    raw = _source_draft()
    verdict = _review(raw)
    mutation(verdict)
    with pytest.raises(SourceOwnershipReviewError):
        ground_source_ownership(raw, verdict, source_clause="거래 등으로")


def test_all_rejected_is_fail_closed_even_with_verbatim_source_names():
    raw = _source_draft()
    result = {"bindings": [
        {"index": i, "owned": False, "source_quote": "", "server_quote": ""}
        for i in range(3)
    ]}
    with pytest.raises(SourceOwnershipReviewError, match="REJECTED"):
        ground_source_ownership(raw, result, source_clause="거래 등으로")


def test_real_architect_recovers_plan_54_on_source_grounded_tie(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    facets = _source_facets()
    prompt = "거래 등으로 무기 선원 우주선 성능을 거래"
    research = {
        "ledger": {
            "original_prompt": prompt,
            "requirements": [
                {"id": "req-trade", "statement": "거래 등으로"},
                {"id": "req-equipment", "statement": "무기 선원 우주선 성능을 거래"},
            ],
            "facets": facets,
        },
        "evidence": [],
    }

    class Model:
        supports_source_ownership_review = True
        def __init__(self):
            self.calls = []

        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return _source_draft()
            if len(self.calls) == 2:
                assert "original_source_clause" in prompt
                assert "candidate_systems" in prompt
                assert kwargs["max_tokens"] <= 540
                assert kwargs["json_schema"] == SOURCE_OWNERSHIP_REVIEW_SCHEMA
                return _review(_source_draft())
            assert len(self.calls) == 3
            return {"systems": [_system(
                "EquipmentTrade",
                "validates the owned currency balance, deducts the "
                "server-priced cost on purchase, and transfers the purchased "
                "weapon into owned inventory before equipping it. The server "
                "validates crew hiring, debits the authorized hiring cost and "
                "recruits crew members. The server validates spaceship engine "
                "upgrades, deducts the approved upgrade cost and improves "
                "the spacecraft performance",
                "purchased weapon, hired crew, and upgraded spaceship performance",
            )]}

    model = Model()
    result = RobloxDynamicArchitect(model).design(prompt, research, [])
    assert len(model.calls) == 3
    assert any("deducts the approved upgrade cost" in m.description
               for m in result["modules"])
    assert any("purchased item" in m.description for m in result["modules"])
    assert any("sold resource" in m.description for m in result["modules"])
    assert not any("peer-to-peer offer" in m.description for m in result["modules"])
    assert research["architecture_attempts"][0]["passed"]
    assert "Server-Validated Trade Offer" in research[
        "architecture_attempts"][0]["out_of_scope_systems_ignored"]


def test_missing_binding_fails_without_accepting_unrequested_actions():
    raw = {"systems": [
        _system("Attack", "damages an enemy's health", "enemy defeat"),
        _system("Trade", "exchanges inventory items", "exchange"),
    ]}
    review = {"bindings": [{
        "index": 1, "owned": True, "source_quote": "교환",
        "server_quote": "exchanges inventory items",
    }]}
    with pytest.raises(SourceOwnershipReviewError, match="every candidate"):
        ground_source_ownership(raw, review, source_clause="교환")


def test_completely_different_game_requires_own_source_and_real_server_evidence():
    raw = {"systems": [
        _system("GardenWatering", "waters planted flowers and records growth",
                "planted flowers growing"),
        _system("GardenDecoration", "purchases a garden decoration",
                "garden decoration purchased"),
    ]}
    verdict = {"bindings": [
        {"index": 0, "owned": True, "source_quote": "꽃에 물을 준다",
         "server_quote": "waters planted flowers and records growth"},
        {"index": 1, "owned": False, "source_quote": "", "server_quote": ""},
    ]}
    scoped, excluded = ground_source_ownership(
        raw, verdict, source_clause="꽃에 물을 준다")
    assert [s["name"] for s in scoped["systems"]] == ["GardenWatering"]
    assert excluded == ["GardenDecoration"]
