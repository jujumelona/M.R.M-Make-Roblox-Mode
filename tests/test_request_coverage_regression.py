"""Regression: a shop keyword must never certify an entire custom Roblox game."""
from __future__ import annotations

import hashlib

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.pre_design_research import RobloxPreDesignResearch, build_request_ledger
from roblox_mod_ai.request_contract import (
    is_composite, ledger_complete, span_coverage, validate_model_behaviors,
)


SPACE_REQUEST = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 부위마다 만들어서 "
    "만들수있고 무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고 "
    "그렇게해서 우주로 나갈수있고 우주로 나가면 다른행성의 특수 광물 "
    "외게인과 싸움 식민지화등 여러가지가 가능한 모드"
)

ATOMIC_REQUEST = (
    "광물을 채굴하고 거래해서 우주선 부품을 제작하고 우주로 이동한 다음 "
    "외계인과 전투하고 기지를 건설할 수 있는 게임"
)
ATOMS = [
    "광물을 채굴하고",
    "거래해서",
    "우주선 부품을 제작하고",
    "우주로 이동한 다음",
    "외계인과 전투하고",
    "기지를 건설할 수 있는 게임",
]


class SourceAnchoredModel:
    def __init__(self, spans=ATOMS):
        self.spans = spans

    def complete_json(self, prompt, **kwargs):
        assert "Decompose EACH compound Roblox" in prompt
        return {"behaviors": [
            {"clause_id": "req-001", "source_span": span,
             "intent": "Implement a server-authoritative gameplay action for " + span,
             "english_query": "Roblox Studio server authoritative gameplay API "
                              + str(i)}
            for i, span in enumerate(self.spans)
        ]}


def test_space_request_without_separators_is_not_a_complete_shop(monkeypatch, tmp_path):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "0")
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "0")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    ledger = build_request_ledger(SPACE_REQUEST)
    assert len(ledger["requirements"]) == 1
    assert "shop" in {x["id"] for x in ledger["facets"]}
    assert ledger["decomposition_pending"] == ["req-001"]
    assert "semantic_decomposition_required" in ledger["unimplemented_facets"]
    assert not ledger_complete(SPACE_REQUEST, ledger)

    planner = RobloxGameDesignPlanner(
        pre_design_research=RobloxPreDesignResearch(live_enabled=False))
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.planner = planner
    reply = session.plan(SPACE_REQUEST)
    assert not reply.ready_to_build
    assert reply.authored_plan.proposal.game_design["genre"] == "Custom"
    assert reply.authored_plan.proposal.game_design["dynamic_design"] is None
    assert reply.authored_plan.proposal.game_design["pre_design_research"]["ledger"]["decomposition_pending"]


def test_simple_shop_request_can_still_use_builtin():
    ledger = build_request_ledger("상점에서 아이템 구매")
    assert ledger_complete("상점에서 아이템 구매", ledger)
    assert ledger["decomposition_pending"] == []


def test_compound_atomic_source_spans_are_individually_tracked(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    research = RobloxPreDesignResearch(
        router=SourceAnchoredModel(), live_enabled=False
    ).research(ATOMIC_REQUEST)
    ledger = research["ledger"]
    assert is_composite(ATOMIC_REQUEST)
    assert not ledger["decomposition_pending"]
    assert ledger["decomposition_method"] == "source_anchored_model"
    assert len(ledger["requirements"]) == len(ATOMS)
    assert len(ledger["atomic_intents"]) == len(ATOMS)
    assert span_coverage(ATOMIC_REQUEST, ATOMS) >= .78
    assert {"shop", "intent-"} and any(
        x["id"].startswith("intent-") for x in ledger["facets"]
    )
    assert all(x["facet_id"] in ledger["unimplemented_facets"]
               for x in ledger["atomic_intents"])
    structural = dict(ledger, unimplemented_facets=[], unmatched_requirements=[])
    assert ledger_complete(ATOMIC_REQUEST, structural)
    assert not ledger_complete(ATOMIC_REQUEST, ledger)


def test_omitting_atomic_actions_cannot_pass_as_verified(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    research = RobloxPreDesignResearch(
        router=SourceAnchoredModel(spans=ATOMS[:2]), live_enabled=False
    ).research(ATOMIC_REQUEST)
    ledger = research["ledger"]
    assert ledger["decomposition_pending"] == ["req-001"]
    assert "semantic_decomposition_required" in ledger["unimplemented_facets"]
    assert not ledger_complete(ATOMIC_REQUEST, ledger)
    assert any(x["facet"] == "semantic_decomposition"
               for x in research["provider_failures"])


def test_untrusted_saved_ledger_cannot_erase_unknown_parts():
    ledger = build_request_ledger(SPACE_REQUEST)
    ledger["unimplemented_facets"] = []
    ledger["unmatched_requirements"] = []
    ledger["decomposition_pending"] = []
    assert not ledger_complete(SPACE_REQUEST, ledger)
    ledger["decomposition_method"] = "source_anchored_model"
    assert not ledger_complete(SPACE_REQUEST, ledger)


def test_model_spans_must_be_exact_distinct_and_cover_source():
    valid = [
        {"source_span": x, "intent": "Gameplay implements " + x,
         "english_query": "Roblox server APIs " + str(i)}
        for i, x in enumerate(ATOMS)
    ]
    assert validate_model_behaviors(ATOMIC_REQUEST, valid)
    assert not validate_model_behaviors(ATOMIC_REQUEST, valid[:2])
    assert not validate_model_behaviors(
        ATOMIC_REQUEST, [dict(valid[0], source_span="unrequested rocket launch")] + valid[1:]
    )
    assert not validate_model_behaviors(
        ATOMIC_REQUEST, [valid[0], valid[0]] + valid[2:]
    )
