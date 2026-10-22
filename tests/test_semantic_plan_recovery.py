"""Recover small-model source classification without fabricating game mechanics.

Replays the structural causes of a long Korean multi-mechanic planning failure:
short non-standalone source fragments, valid prior classifications, and colony
UI unrelated to authoritative settlement persistence.
"""
import json

from roblox_mod_ai.source_decomposition import (
    source_chunks, classification_context, valid_chunk_classification,
)
from roblox_mod_ai.semantic_preservation import source_intent_conflicts
from roblox_mod_ai.pre_design_research import (
    RobloxPreDesignResearch, build_request_ledger,
)


SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
    "부위마다 만들어서 만들수있고 무기 선원 우주선 성능을 거래 "
    "구매 등으로 업그레이드 확장 할 수 있고 그렇게해서 우주로 "
    "나갈수있고 우주로 나가면 다른행성의 특수 광물 외계인과 싸움 "
    "식민지화등 여러가지가 가능한 모드"
)


def test_selected_short_fragments_have_grounded_adjacent_context():
    spans = source_chunks(SOURCE)
    assert " ".join(spans) == SOURCE
    chunks = [{"chunk_id": f"chunk-{i:03}", "source_span": span,
               "clause_id": "req-001"}
              for i, span in enumerate(spans, 1)]
    center = next(c for c in chunks if "구매" in c["source_span"])
    rows = classification_context(
        chunks, [center], [{"id": "req-001", "statement": SOURCE}])
    assert len(rows) == 1
    assert rows[0]["source_span"] == center["source_span"]
    assert rows[0]["source_clause"] == SOURCE
    assert rows[0]["previous"] or rows[0]["next"]


def test_colony_cannot_pass_from_other_inventory_save_plus_colony_ui():
    source = "Colonize a new planet"
    misleading = ("Server records the weapon inventory and currency. "
                  "The client displays colonization feedback on the colony menu.")
    assert any("SETTLEMENT_DROPPED" in issue for issue in
               source_intent_conflicts(source, misleading))
    valid = ("Server validates colonization and records an owned planet "
             "colony settlement in the saved player profile. "
             "The client reports the confirmed ownership.")
    assert source_intent_conflicts(source, valid) == []


class BoundedContextModel:
    """Fail on the unscoped whole clause, then answer only grounded chunks."""

    def __init__(self, fail_chunk_once=False):
        self.fail_chunk_once = fail_chunk_once
        self.calls = []
        self.failed = False

    def complete_json(self, prompt, **_kwargs):
        if prompt.startswith("Decompose EACH compound"):
            raise ValueError("large clause completion not accepted")
        payload = json.loads(prompt[prompt.index('{"chunks":'):])
        chunks = payload["chunks"]
        self.calls.append([r["chunk_id"] for r in chunks])
        rows = []
        for row in chunks:
            span = row["source_span"]
            if self.fail_chunk_once and "식민" in span:
                continue
            # The model must see the surrounding source; otherwise it cannot
            # safely determine the role of short coordinating fragments.
            assert row["source_clause"]
            assert row["source_span"] in row["source_clause"]
            if "식민" in span and ("외계인" in span or "외게인" in span):
                # One unpunctuated original span can contain TWO actions.
                # The model must retain both, not pretend a UI or PvP target
                # fully implements a player request.
                action = ("Player fights hostile alien NPC enemies and "
                          "establishes a persistent owned colony settlement")
                query = "Roblox NPC battle and colony settlement ownership"
            elif "식민" in span:
                action = "Establish a persistent owned colony settlement on the planet"
                query = "Roblox DataStore persistent colony settlement ownership"
            elif "외계인" in span or "외게인" in span:
                action = "Player attacks hostile alien enemy NPCs with validated damage"
                query = "Roblox server hostile alien NPC attack damage"
            elif "우주로" in span:
                action = "The spacecraft launches into space after ship construction"
                query = "Roblox server validation of launch travel into space"
            else:
                action = "Implement exactly this source gameplay clause: " + span
                query = "Roblox server game mechanic " + span
            rows.append({"chunk_id": row["chunk_id"],
                         "intent": action[:179], "english_query": query[:159]})
        return {"behaviors": rows}


def test_retry_uses_saved_successful_chunks_and_reclassifies_only_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    cache = tmp_path / "semantic.json"
    first = BoundedContextModel(fail_chunk_once=True)
    research = RobloxPreDesignResearch(router=first, live_enabled=False,
                                       classification_cache=cache)
    ledger = research._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert ledger["classification_unverified"]
    assert cache.is_file()
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["behaviors"]
    saved_ids = {b["chunk_id"] for b in saved["behaviors"]}

    second = BoundedContextModel()
    researcher2 = RobloxPreDesignResearch(router=second, live_enabled=False,
                                          classification_cache=cache)
    recovered = researcher2._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert recovered.get("classification_unverified") in (None, [])
    assert recovered["decomposition_strategy"] == "source_chunk_model_classification"
    retried = {id for batch in second.calls for id in batch}
    assert not saved_ids.intersection(retried)
    assert len(recovered["atomic_intents"]) == len(source_chunks(SOURCE))


def test_full_verified_decomposition_survives_later_plan_failure(tmp_path, monkeypatch):
    """An identical user request must retain the same facets after codegen fails."""
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    cache = tmp_path / "classified_chunks.json"
    # Reproduce actual recoverable failure first: only part of the source
    # can be classified in run one, the missing spans in run two.
    first_model = BoundedContextModel(fail_chunk_once=True)
    first = RobloxPreDesignResearch(
        router=first_model, live_enabled=False, classification_cache=cache)
    partial = first._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert partial.get("classification_unverified")
    recovered_model = BoundedContextModel()
    second = RobloxPreDesignResearch(
        router=recovered_model, live_enabled=False, classification_cache=cache)
    accepted = second._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert accepted.get("decomposition_strategy") == "source_chunk_model_classification"
    assert not accepted.get("classification_unverified")
    assert (tmp_path / "semantic_decomposition_checkpoint.json").is_file()
    # The complete-graph cache and independent chunk cache must be two files:
    # previously a shadowed variable overwrote the chunk cache with the whole
    # graph and no stable decomposition checkpoint was ever created.
    chunk_doc = json.loads(cache.read_text(encoding="utf-8"))
    graph_doc = json.loads((tmp_path / "semantic_decomposition_checkpoint.json")
                           .read_text(encoding="utf-8"))
    assert chunk_doc["schema"] == "rmm/semantic-chunk-cache-v1"
    assert graph_doc["schema"] == "rmm/verified-decomposition-v1"
    assert chunk_doc["behaviors"]
    assert graph_doc["ledger"] == accepted

    class NoModel:
        def complete_json(self, *_args, **_kwargs):
            raise AssertionError("A fully validated source graph must be reused")

    another = RobloxPreDesignResearch(
        router=NoModel(), live_enabled=False, classification_cache=cache)
    restored = another._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert restored == accepted
    assert [x["facet_id"] for x in restored["atomic_intents"]] == [
        x["facet_id"] for x in accepted["atomic_intents"]
    ]


def test_tampered_decomposition_signature_cannot_be_used(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    cache = tmp_path / "classified_chunks.json"
    partial = RobloxPreDesignResearch(
        router=BoundedContextModel(fail_chunk_once=True), live_enabled=False,
        classification_cache=cache)
    partial._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    researcher = RobloxPreDesignResearch(
        router=BoundedContextModel(), live_enabled=False,
        classification_cache=cache)
    accepted = researcher._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert accepted.get("decomposition_strategy") == "source_chunk_model_classification"
    path = tmp_path / "semantic_decomposition_checkpoint.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["input_sha256"] = "old-implementation"
    path.write_text(json.dumps(payload), encoding="utf-8")
    restarted = BoundedContextModel()
    recovered = RobloxPreDesignResearch(
        router=restarted, live_enabled=False, classification_cache=cache
    )._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    assert not recovered.get("classification_unverified")
    assert restarted.calls == [] or all(
        isinstance(batch, list) for batch in restarted.calls
    )
    # The saved complete ledger was rejected, but separately signed individual
    # verified chunks may still be reused, which is safe and avoids LLM waste.
    assert json.loads(path.read_text(encoding="utf-8"))["input_sha256"] != "old-implementation"


def test_cached_model_claims_are_revalidated_and_only_unsafe_chunks_reasked(
        tmp_path, monkeypatch):
    """An old model's invented peer-trade cannot survive semantic-policy updates."""
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "1")
    cache = tmp_path / "classified_chunks.json"
    first = RobloxPreDesignResearch(
        router=BoundedContextModel(fail_chunk_once=True),
        live_enabled=False, classification_cache=cache)
    first._decompose_compound(SOURCE, build_request_ledger(SOURCE))
    contents = json.loads(cache.read_text(encoding="utf-8"))
    assert contents["behaviors"]
    corrupt = contents["behaviors"][0]
    corrupted_id = corrupt["chunk_id"]
    corrupt["intent"] = "Player-to-Player Trading"
    corrupt["english_query"] = "Roblox trade between other players inventories"
    cache.write_text(json.dumps(contents), encoding="utf-8")
    new_model = BoundedContextModel()
    recovered = RobloxPreDesignResearch(
        router=new_model, live_enabled=False,
        classification_cache=cache)._decompose_compound(
            SOURCE, build_request_ledger(SOURCE))
    assert recovered.get("decomposition_strategy") == "source_chunk_model_classification"
    queried = {cid for group in new_model.calls for cid in group}
    assert corrupted_id in queried
    assert all(atom["intent"] != "Player-to-Player Trading"
               for atom in recovered["atomic_intents"])


def test_grammatical_source_units_no_longer_create_fifteen_pseudo_features():
    """Regression from plan failure (5): 11-character source buckets."""
    source = (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
        "부위마다 만들어서 만들수있고 무기 선원 우주선 성능을 거래 "
        "구매 등으로 업그레이드 확장 할 수 있고 그렇게해서 우주로 "
        "나갈수있고 우주로 나가면 다른행성의 특수 광물 외게인과 싸움 "
        "식민지화등 여러가지가 가능한 모드"
    )
    spans = source_chunks(source)
    assert " ".join(spans) == source
    assert 5 <= len(spans) < 15
    assert all(span != "가능한 모드" for span in spans)
    assert any("식민지화" in span and "가능한 모드" in span for span in spans)
    # A connector must not be a model-owned game mechanic on its own.
    assert all(span not in ("수 있고", "등으로", "그렇게해서") for span in spans)


def test_colony_intent_classification_is_not_persistence_implementation():
    """Recognizing a requested mechanic is not yet designing its state ABI."""
    assert source_intent_conflicts(
        "식민지화등 여러가지가 가능한 모드", "Planet colonization",
        require_implementation=False
    ) == []
    assert source_intent_conflicts(
        "식민지화등 여러가지가 가능한 모드", "Planet colonization"
    )
    selected = [{
        "chunk_id": "chunk-colony",
        "source_span": "식민지화등 여러가지가 가능한 모드"
    }]
    classified = valid_chunk_classification({
        "behaviors": [{
            "chunk_id": "chunk-colony",
            "intent": "Enable planet colonization as a player gameplay goal",
            "english_query": "Roblox planet colonization action planning"
        }]
    }, selected)
    assert "chunk-colony" in classified
