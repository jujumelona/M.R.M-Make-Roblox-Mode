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
    assert {m.name for m in reply.authored_plan.proposal.modules} == {"NetworkRemotes", "PlayerDataManager", "GameObjectiveController"}
    assert reply.authored_plan.proposal.game_design["pre_design_research"]["ledger"]["decomposition_pending"]


def test_short_compound_purchase_does_not_hide_crafting_and_travel():
    prompt = "우주선 구매해서 조립하고 우주로 간다"
    ledger = build_request_ledger(prompt)
    assert is_composite(prompt)
    assert "shop" in {f["id"] for f in ledger["facets"]}
    assert ledger["decomposition_pending"] == ["req-001"]
    assert not ledger_complete(prompt, ledger)


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
    assert any(x["id"].startswith("intent-") for x in ledger["facets"])
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
    # A classifier omitting an action cannot certify it. Source ownership
    # instead comes from the host, with model classification explicitly absent.
    assert ledger["decomposition_pending"] == []
    assert ledger["decomposition_method"] == "source_anchored_host"
    assert ledger["classification_unverified"]
    assert all(x["source_span"] in ATOMIC_REQUEST for x in ledger["atomic_intents"])
    assert not ledger_complete(ATOMIC_REQUEST, ledger)  # never implemented yet
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



def test_novel_action_searches_use_limited_docs_budget_first(monkeypatch):
    """RAG must not spend eight search slots on generic shop/docs instead of user actions."""
    class DocsSpy:
        def __init__(self):
            self.queries = []

        def search(self, query, *, limit, with_excerpt):
            self.queries.append(query)
            return {"results": []}

    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    original = "상점에서 아이템 구매"
    ledger = build_request_ledger(original)
    ledger["atomic_intents"] = [{"facet_id": "intent-0", "requirement_id": "req-001"}]
    for index in range(10):
        ledger["facets"].append({
            "id": f"intent-{index}",
            "requirements": ["req-001"],
            "search_query": f"Roblox original mechanic {index}",
            "source_span": f"mechanic {index}",
            "implementation_key": None,
            "implemented_by_builtin": False,
        })
    docs = DocsSpy()
    research = RobloxPreDesignResearch(docs=docs, live_enabled=True)
    research._decompose_compound = lambda prompt, _ledger: ledger
    result = research.research(original)
    assert len(docs.queries) == 8
    assert all("original mechanic" in query for query in docs.queries)
    assert result["queries"][0]["facet"].startswith("intent-")
    shop_query = next(item for item in result["queries"] if item["facet"] == "shop")
    assert shop_query["status"] == "deferred_budget"


def test_auto_model_availability_does_not_rewrite_exact_stock_shop(monkeypatch):
    """Availability of llama-server must not disable inspected first-party reuse."""
    class ModelMustNotBeUsed:
        def complete_json(self, *args, **kwargs):
            raise AssertionError("Stock shop unexpectedly replanned with an LLM")

    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "auto")
    monkeypatch.setenv("ROBLOX_LLAMA_SERVER_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    research = RobloxPreDesignResearch(live_enabled=False)
    planner = RobloxGameDesignPlanner(pre_design_research=research)
    planner.router = ModelMustNotBeUsed()
    plan = planner.plan("상점에서 아이템 구매")
    assert plan.proposal.game_design["dynamic_design"] is None
    assert {"ShopService", "ShopController"}.issubset(
        {module.name for module in plan.proposal.modules}
    )


def test_atomic_doc_queries_drop_unrequested_generic_api_terms(monkeypatch):
    class DocsSpy:
        def __init__(self): self.calls = []
        def search(self, query, *, limit, with_excerpt):
            self.calls.append(query)
            return {"results": [], "error": None}
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    ledger = build_request_ledger("상점에서 아이템 구매")
    ledger["facets"].append({
        "id": "intent-custom", "requirements": ["req-001"],
        "search_query": "Roblox implement pet collection with DataStoreService Chat",
        "implementation_key": None, "implemented_by_builtin": False,
        "source_span": "아이템 구매",
    })
    ledger["atomic_intents"] = [{"facet_id": "intent-custom",
                                  "intent": "Implement pet collection and hatching"}]
    docs = DocsSpy()
    research = RobloxPreDesignResearch(docs=docs, live_enabled=True)
    monkeypatch.setattr(research, "_decompose_compound", lambda prompt, old: ledger)
    result = research.research("상점에서 아이템 구매")
    entry = next(q for q in result["queries"] if q["facet"] == "intent-custom")
    assert entry["retrieval_query"] == "Roblox Implement pet collection and hatching"
    assert docs.calls[0] == entry["retrieval_query"]
    assert "DataStoreService" in entry["query"]


def test_failed_whole_request_recovers_every_original_source_chunk(monkeypatch):
    """A 9B model that omits a long compound clause must classify every local part."""
    import json
    from roblox_mod_ai.source_decomposition import source_chunks
    calls = []
    class PartlyReliableModel:
        def complete_json(self, prompt, **kwargs):
            calls.append(prompt)
            if "Decompose EACH compound Roblox" in prompt:
                return {"behaviors": []}  # reproduces user's repeated failure
            batch = json.loads(prompt[prompt.index('{"chunks"'):])["chunks"]
            return {"behaviors": [
                {"chunk_id": c["chunk_id"],
                 "intent": (
                     "Players mine special minerals on other planets, fight hostile "
                     "alien NPC enemies, and establish a persisted planet "
                     "colony settlement"
                     if "식민" in c["source_span"] and (
                         "외계인" in c["source_span"] or
                         "외게인" in c["source_span"]) else
                     "Server establishes and persists a planet colony settlement"
                     if "식민" in c["source_span"] else
                     "Server handles hostile alien NPC enemy combat"
                     if "외계인" in c["source_span"] or "외게인" in c["source_span"] else
                     "Ship launches into space after completing construction"
                     if "우주로" in c["source_span"] else
                     "Implement the gameplay action from " + c["source_span"]
                 ),
                 "english_query": "Roblox API for gameplay chunk " + c["chunk_id"]}
                for c in batch
            ]}
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "1")
    clauses = source_chunks(SPACE_REQUEST)
    assert len(clauses) >= 3
    # Character count must not create independent server actors.
    assert all(piece not in {"구매 등으로", "거래 등으로"} for piece in clauses)
    assert any("외게인과 싸움" in piece for piece in clauses)
    assert span_coverage(SPACE_REQUEST, clauses) >= .99
    assert " ".join(clauses) == SPACE_REQUEST
    researched = RobloxPreDesignResearch(
        router=PartlyReliableModel(), live_enabled=False).research(SPACE_REQUEST)
    ledger = researched["ledger"]
    assert ledger["decomposition_pending"] == []
    assert ledger["decomposition_strategy"] == "source_chunk_model_classification"
    assert len(ledger["atomic_intents"]) == len(clauses)
    assert len(ledger["requirements"]) == len(clauses)
    assert "semantic_decomposition_required" not in ledger["unimplemented_facets"]
    assert not any(f["id"].startswith("semantic-") for f in ledger["facets"])
    structural = dict(ledger, unimplemented_facets=[], unmatched_requirements=[])
    assert ledger_complete(SPACE_REQUEST, structural)
    assert len(calls) >= 2


def test_model_omitting_only_one_chunk_gets_targeted_retry(monkeypatch):
    import json
    original = ATOMIC_REQUEST
    recorded = []
    class Model:
        def complete_json(self, prompt, **kwargs):
            if "Decompose EACH compound Roblox" in prompt:
                return {"behaviors": []}
            batch = json.loads(prompt[prompt.index('{"chunks"'):])["chunks"]
            recorded.append([c["chunk_id"] for c in batch])
            if len(recorded) == 1:
                batch = batch[:-1]
            return {"behaviors": [
                {"chunk_id": c["chunk_id"],
                 "intent": ("Players attack hostile alien NPC enemies"
                            if "외계인" in c["source_span"]
                            else "Launch the player's ship into space"
                            if "우주로" in c["source_span"]
                            else "Implement the source mechanic"),
                 "english_query": "Roblox source implementation " + c["chunk_id"]}
                for c in batch
            ]}
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    ledger = RobloxPreDesignResearch(
        router=Model(), live_enabled=False).research(original)["ledger"]
    assert ledger["decomposition_pending"] == []
    assert len(recorded) >= 2 and len(recorded[1]) == 1
    assert ledger_complete(original, dict(
        ledger, unimplemented_facets=[], unmatched_requirements=[]))


def test_failed_chunk_classifier_preserves_all_source_without_fake_model_success(monkeypatch):
    """Proposal 14: model cannot describe the first space-game source chunk.

    This must not leave the entire game as one unowned, unimplemented clause.
    The host records exact original source while classifying it as *unverified*.
    """
    from roblox_mod_ai.source_decomposition import source_chunks
    class BrokenModel:
        def complete_json(self, prompt, **kwargs):
            return {"behaviors": []}
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    result = RobloxPreDesignResearch(
        router=BrokenModel(), live_enabled=False).research(SPACE_REQUEST)
    ledger = result["ledger"]
    pieces = source_chunks(SPACE_REQUEST)
    assert ledger["decomposition_pending"] == []
    assert ledger["decomposition_method"] == "source_anchored_host"
    assert ledger["decomposition_strategy"] == "source_chunk_host_recovery"
    assert len(ledger["requirements"]) == len(pieces)
    assert len(ledger["atomic_intents"]) == len(pieces)
    assert len(ledger["classification_unverified"]) == len(pieces)
    assert [x["source_span"] for x in ledger["atomic_intents"]] == pieces
    assert all(x["classification_origin"] == "host_source_only"
               for x in ledger["atomic_intents"])
    assert all(x["source_span"] in x["intent"]
               for x in ledger["atomic_intents"])
    # A partial implementation is still NOT game completion. The requirements
    # only become satisfied after a *separate* architecture/code validation.
    assert ledger["unimplemented_facets"]
    assert "semantic_decomposition_required" not in ledger["unimplemented_facets"]
    assert ledger_complete(SPACE_REQUEST, dict(
        ledger, unimplemented_facets=[], unmatched_requirements=[]))
    # Classification failure is not hidden or relabelled model success.
    assert any(x["facet"] == "semantic_decomposition" for x in
               result["provider_failures"])
    assert not any(f["id"].startswith("semantic-") for f in ledger["facets"])


def test_unclassified_partial_chunk_preserves_verified_classifications(monkeypatch):
    """Host retains good scoped model outputs; only missing chunks fall back."""
    import json
    from roblox_mod_ai.source_decomposition import source_chunks
    class PartialModel:
        def complete_json(self, prompt, **kwargs):
            if "Decompose EACH compound Roblox" in prompt:
                return {"behaviors": []}
            batch = json.loads(prompt[prompt.index('{"chunks"'):])["chunks"]
            return {"behaviors": [
                {"chunk_id": x["chunk_id"],
                 "intent": ("Players buy and upgrade weapons, recruit and "
                            "upgrade crew, and purchase spacecraft performance "
                            "upgrades using earned currency"),
                 "english_query": "Roblox weapon crew spaceship performance purchase upgrades"}
                for x in batch if x["chunk_id"] == "chunk-002"]}
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    result = RobloxPreDesignResearch(
        router=PartialModel(), live_enabled=False).research(SPACE_REQUEST)
    ledger = result["ledger"]
    assert len(ledger["requirements"]) == len(source_chunks(SPACE_REQUEST))
    origins = {x["chunk_id"]: x["classification_origin"]
               for x in ledger["atomic_intents"]}
    assert origins["chunk-002"] == "model_classified"
    assert origins["chunk-001"] == "host_source_only"
    assert len(ledger["classification_unverified"]) == len(origins) - 1
    assert ledger_complete(SPACE_REQUEST, dict(
        ledger, unimplemented_facets=[], unmatched_requirements=[]))
    corrupt = dict(ledger, unimplemented_facets=[], unmatched_requirements=[],
                   classification_unverified=[])
    assert not ledger_complete(SPACE_REQUEST, corrupt)



def test_chunk_partition_never_invents_or_drops_request_words():
    from roblox_mod_ai.source_decomposition import source_chunks
    for statement in (
        ATOMIC_REQUEST, SPACE_REQUEST, "우주선 구매해서 조립하고 우주로 간다",
        "Build a spaceship then visit a planet and discover minerals",
    ):
        chunks = source_chunks(statement)
        assert " ".join(chunks) == statement
        assert span_coverage(statement, chunks) >= .99


def test_source_classifier_rejects_category_label_as_gameplay_intent():
    """Uploaded proposal 13 promoted gameplay_mode_capability into 18 modules."""
    from roblox_mod_ai.source_decomposition import valid_chunk_classification

    chunks = [{"chunk_id": "chunk-001",
               "source_span": "식민지화등 여러가지가 가능한 모드"}]
    wrong = {"behaviors": [{
        "chunk_id": "chunk-001",
        "intent": "gameplay_mode_capability",
        "english_query": "Roblox colonization gameplay mode capability",
    }]}
    assert valid_chunk_classification(wrong, chunks) == {}

    specific = {"behaviors": [{
        "chunk_id": "chunk-001",
        "intent": "Allow players to establish and expand colonies on other planets",
        "english_query": "Roblox colony construction and expansion scripts",
    }]}
    assert valid_chunk_classification(specific, chunks)["chunk-001"]["intent"].startswith(
        "Allow players to establish"
    )


def test_short_unseparated_source_remains_one_clause_until_model_grounds_actions():
    """The host must never invent mechanics at 22-character word boundaries."""
    from roblox_mod_ai.source_decomposition import source_chunks

    for source in (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로",
        "우주로 나가면 다른행성의 특수 광물 외게인과 싸움",
    ):
        segments = source_chunks(source)
        assert segments == [source]
        assert span_coverage(source, segments) == 1.0
    # An explicit conjunction remains a safe *text* boundary, not proof
    # that either generated server actually implements its original action.
    assert source_chunks("우주선 구매해서 조립하고 우주로 간다") == [
        "우주선 구매해서", "조립하고 우주로 간다",
    ]


def test_model_source_id_recovery_from_unseparated_korean_multi_action_clause():
    import json
    from roblox_mod_ai.source_decomposition import recover_unseparated_actions

    source = "외게인과 싸움 식민지화등 여러가지가 가능한 모드"
    assert is_composite(source)

    class GroundedSelector:
        def complete_json(self, prompt, **kwargs):
            assert kwargs["role"] == "planner"
            payload = json.loads(prompt.split("\n")[-1])
            ids = {row["quote"]: row["id"] for row in payload["candidate_source_spans"]}
            return {"actions": [
                {"source_id": ids["외게인과 싸움"],
                 "action": "Fight and defeat hostile alien NPC enemies"},
                {"source_id": ids["식민지화등 여러가지가 가능한 모드"],
                 "action": "Establish new colonies and record ownership"},
            ]}

    result = recover_unseparated_actions(GroundedSelector(), source)
    assert [row["source_span"] for row in result] == [
        "외게인과 싸움", "식민지화등 여러가지가 가능한 모드"]
    assert validate_model_behaviors(source, result)


def test_short_english_compound_marked_for_semantic_decomposition():
    assert is_composite("Fight alien enemies and colonize planets")




def test_pre_design_unsplittable_source_becomes_two_real_owned_intents(monkeypatch):
    """Exercise research -> source-span selection -> ledger, not just the helper."""
    import json
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    source = "외게인과 싸움 식민지화등 여러가지가 가능한 모드"

    class Selector:
        def complete_json(self, prompt, **kwargs):
            if "Decompose EACH compound Roblox" in prompt:
                return {"behaviors": []}
            assert prompt.startswith("SOURCE-SCOPED DECOMPOSITION ONLY")
            available = json.loads(prompt.split("\n")[-1])
            ids = {row["quote"]: row["id"]
                   for row in available["candidate_source_spans"]}
            return {"actions": [
                {"source_id": ids["외게인과 싸움"],
                 "action": "Fight and defeat hostile alien NPC enemies"},
                {"source_id": ids["식민지화등 여러가지가 가능한 모드"],
                 "action": "Establish new colonies and record ownership"},
            ]}

    ledger = RobloxPreDesignResearch(
        router=Selector(), live_enabled=False).research(source)["ledger"]
    assert ledger["decomposition_pending"] == []
    assert ledger["decomposition_method"] == "source_anchored_model"
    assert [row["source_span"] for row in ledger["atomic_intents"]] == [
        "외게인과 싸움", "식민지화등 여러가지가 가능한 모드"]
    assert len(ledger["requirements"]) == 2
    assert ledger_complete(source, dict(ledger,
        unmatched_requirements=[], unimplemented_facets=[]))


def test_unseparated_source_fails_closed_when_model_invents_actions(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    source = "외게인과 싸움 식민지화등 여러가지가 가능한 모드"
    class Malformed:
        def complete_json(self, prompt, **kwargs):
            return {"behaviors": []} if "Decompose EACH compound" in prompt else {
                "actions": [{"source_id": "invented", "action": "Buy premium pets"}]}
    ledger = RobloxPreDesignResearch(
        router=Malformed(), live_enabled=False).research(source)["ledger"]
    assert ledger["decomposition_pending"]
    assert not ledger_complete(source, ledger)



def test_clause_partition_never_deletes_original_conjunctions_or_invents_actions():
    from roblox_mod_ai.request_contract import clauses
    for source in (
        "Buy red and blue construction materials",
        "외계인 및 광물을 얻는 모드",
        "우주선 제작 그리고 우주로 이동",
        "Build ship and travel to orbit",
    ):
        assert clauses(source) == [source]
        ledger = build_request_ledger(source)
        assert [row["statement"] for row in ledger["requirements"]] == [source]


def test_long_english_source_is_partitioned_after_linguistic_classification_not_before():
    from roblox_mod_ai.request_contract import clauses
    from roblox_mod_ai.source_decomposition import source_chunks
    source = "Fight alien enemies and colonize planets"
    assert clauses(source) == [source]
    assert is_composite(source)
    groups = source_chunks(source)
    assert " ".join(groups) == source
    assert len(groups) == 2
    assert all(group in source for group in groups)



def test_saved_atomic_ledger_cannot_claim_deleted_behavior_as_complete(monkeypatch):
    import copy
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    ledger = RobloxPreDesignResearch(
        router=SourceAnchoredModel(), live_enabled=False).research(ATOMIC_REQUEST)["ledger"]
    original = dict(ledger, unimplemented_facets=[], unmatched_requirements=[])
    assert ledger_complete(ATOMIC_REQUEST, original)

    deleted_atom = copy.deepcopy(original)
    deleted_atom["atomic_intents"].pop()
    assert not ledger_complete(ATOMIC_REQUEST, deleted_atom)

    altered_owner = copy.deepcopy(original)
    altered_owner["atomic_intents"][0]["source_span"] = ATOMS[1]
    assert not ledger_complete(ATOMIC_REQUEST, altered_owner)

    duplicated_owner = copy.deepcopy(original)
    duplicated_owner["atomic_intents"][1]["requirement_id"] = (
        duplicated_owner["atomic_intents"][0]["requirement_id"])
    assert not ledger_complete(ATOMIC_REQUEST, duplicated_owner)

    deleted_facet = copy.deepcopy(original)
    lost_id = deleted_facet["atomic_intents"][-1]["facet_id"]
    deleted_facet["facets"] = [f for f in deleted_facet["facets"]
                               if f["id"] != lost_id]
    assert not ledger_complete(ATOMIC_REQUEST, deleted_facet)


def test_whole_source_echo_twice_is_not_atomic_decomposition():
    import copy
    ledger = build_request_ledger(ATOMIC_REQUEST)
    # A corrupted save cannot claim multiple distinct action owners merely
    # by assigning two IDs to the same undivided original user clause.
    ledger["requirements"] = [
        {"id": "req-001", "statement": ATOMIC_REQUEST, "source": "user_prompt"},
        {"id": "req-002", "statement": ATOMIC_REQUEST, "source": "user_prompt"},
    ]
    ledger["decomposition_method"] = "source_anchored_model"
    ledger["decomposition_pending"] = []
    assert not ledger_complete(ATOMIC_REQUEST, dict(
        ledger, unmatched_requirements=[], unimplemented_facets=[]))



def test_numeric_comma_does_not_split_requested_amount_into_fake_features():
    from roblox_mod_ai.request_contract import clauses
    assert clauses("Collect 1,000 coins") == ["Collect 1,000 coins"]
    assert clauses("Collect 1,000 coins, upgrade a ship") == [
        "Collect 1,000 coins", "upgrade a ship"]
    assert clauses("Mine ore, trade resources") == [
        "Mine ore", "trade resources"]
