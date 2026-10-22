"""Reproduce plan_failure_logs (21): two source actions, invented quotations.

Unlike the old 9B prompt, the model only selects an ID; Korean source text is
kept byte-identical by the host. No title, game genre, or prompt-specific
action labels are used by the production implementation.
"""
import pytest

from roblox_mod_ai.atomic_action_quotes import (
    SourceActionBindingError,
    indexed_source_spans,
    verify_or_bind_actions,
)


SOURCE = "외게인과 싸움 식민지화등 여러가지가 가능한 모드"


class SpanSelector:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        assert kwargs["role"] == "planner"
        assert kwargs["max_tokens"] <= 400
        assert "candidate_source_spans" in prompt
        import json
        obj = json.loads(prompt.split("\n")[-1])
        candidates = {row["quote"]: row["id"]
                      for row in obj["candidate_source_spans"]}
        unbound = obj.get("unbound_actions", obj.get("actions", []))
        return {"bindings": [
            {"action_index": row["action_index"],
             "source_id": candidates[
                 (self.mapping[row["action_index"]]
                  if len(self.mapping) != len(unbound)
                  else self.mapping[position])]}
            for position, row in enumerate(unbound)
        ]}


def test_report21_multilingual_unquoted_actions_get_exact_host_source():
    raw = [
        {"source_quote": "fight aliens", "action": "Fight hostile alien NPC enemies"},
        {"source_quote": "colonize planets", "action": "Establish new planet colony ownership"},
    ]
    selector = SpanSelector(["외게인과 싸움", "식민지화등"])
    result = verify_or_bind_actions(selector, SOURCE, raw)
    assert result == [
        {"source_quote": "외게인과 싸움", "action": "Fight hostile alien NPC enemies"},
        {"source_quote": "식민지화등", "action": "Establish new planet colony ownership"},
    ]
    assert len(selector.calls) == 1


def test_valid_original_quotes_do_not_call_model_again():
    class NoExtraRequest:
        def complete_json(self, *a, **kw):
            raise AssertionError("Already valid source quotes must not be replanned")
    rows = [
        {"source_quote": "Fight alien enemies", "action": "Fight hostile alien enemies"},
        {"source_quote": "colonize planets", "action": "Establish settlements on planets"},
    ]
    source = "Fight alien enemies and colonize planets"
    assert verify_or_bind_actions(NoExtraRequest(), source, rows) == rows


def test_duplicate_quote_is_reanchored_to_distinct_source_spans():
    selector = SpanSelector(["Fight alien enemies", "colonize planets"])
    result = verify_or_bind_actions(selector, "Fight alien enemies and colonize planets", [
        {"source_quote": "Fight alien enemies", "action": "Attack hostile aliens"},
        {"source_quote": "Fight alien enemies", "action": "Establish a colony on planets"},
    ])
    assert result[0]["source_quote"] != result[1]["source_quote"]


def test_unrequested_premium_pet_action_rejected_despite_real_source_id():
    selector = SpanSelector(["Fight alien enemies", "colonize planets"])
    with pytest.raises(SourceActionBindingError, match="SEMANTIC_MISMATCH|DROPPED"):
        verify_or_bind_actions(selector, "Fight alien enemies and colonize planets", [
            {"source_quote": "Combat alien enemies",
             "action": "Fight hostile alien enemies"},
            {"source_quote": "premium robot pets",
             "action": "Purchase premium robot pets"},
        ])


def test_schema_rejects_fake_indexes_and_fake_source_ids():
    class InvalidID:
        def complete_json(self, *args, **kwargs):
            return {"bindings": [
                {"action_index": 0, "source_id": "s0"},
                {"action_index": 1, "source_id": "invented"},
            ]}
    with pytest.raises(SourceActionBindingError, match="MAPPING_INVALID"):
        verify_or_bind_actions(InvalidID(), SOURCE, [
            {"source_quote": "invented a", "action": "Fight hostile alien enemies"},
            {"source_quote": "invented b", "action": "Establish the new planet colony"},
        ])


def test_host_span_inventory_preserves_unmodified_original_substrings():
    candidates = indexed_source_spans(SOURCE)
    assert 1 < len(candidates) <= 48
    for row in candidates:
        assert SOURCE[row["start"]:row["end"]] == row["quote"]
    assert any(row["quote"] == "식민지화등" for row in candidates)


def test_no_invented_duplicate_action_descriptions():
    with pytest.raises(SourceActionBindingError, match="duplicate gameplay action"):
        verify_or_bind_actions(None, "Fight enemies and colonize planets", [
            {"source_quote": "Fight enemies", "action": "Attack enemies"},
            {"source_quote": "colonize planets", "action": "Attack enemies"},
        ])


def test_initial_indexed_action_contract_never_needs_quote_repair_call():
    class NeverGenerateAnotherAction:
        def complete_json(self, *a, **kw):
            raise AssertionError("Already checked source IDs require no extra model call")
    choices = {row["quote"]: row["id"] for row in indexed_source_spans(SOURCE)}
    original = [
        {"source_id": choices["외게인과 싸움"],
         "action": "Fight hostile alien NPC enemies"},
        {"source_id": choices["식민지화등"],
         "action": "Establish new planet colony ownership"},
    ]
    output = verify_or_bind_actions(NeverGenerateAnotherAction(), SOURCE, original)
    assert output[0]["source_quote"] == "외게인과 싸움"
    assert output[1]["source_quote"] == "식민지화등"


def test_model_cannot_supply_unauthorized_source_id_even_with_valid_quote():
    with pytest.raises(SourceActionBindingError, match="SOURCE_ID_NOT_IN_ORIGINAL"):
        verify_or_bind_actions(None, SOURCE, [
            {"source_id": "outside-list", "source_quote": "외게인과 싸움",
             "action": "Fight hostile alien enemies"},
            {"source_quote": "식민지화등",
             "action": "Establish a new planet colony"},
        ])



def test_long_composite_request_retains_source_tail_and_multitoken_choices():
    source = " ".join("action" + str(i) for i in range(65))
    indexed = indexed_source_spans(source)
    assert len(indexed) <= 48
    assert all(source[row["start"]:row["end"]] == row["quote"] for row in indexed)
    assert any("action0" in row["quote"].split() for row in indexed)
    assert any("action64" in row["quote"].split() for row in indexed)
    assert any(len(row["quote"].split()) >= 3 for row in indexed)
    assert any("action32" in row["quote"].split() for row in indexed)


def test_repair_request_freezes_accepted_source_owner():
    original = "Fight alien enemies and colonize planets"
    selector = SpanSelector(["Fight alien enemies", "colonize planets"])
    output = verify_or_bind_actions(selector, original, [
        {"source_quote": "Fight alien enemies",
         "action": "Fight and defeat hostile alien enemies"},
        {"source_quote": "translated colony",
         "action": "Establish new colonies on planets"},
    ])
    assert output[0]["source_quote"] == "Fight alien enemies"
    assert output[1]["source_quote"] == "colonize planets"
    assert len(selector.calls) == 1
    payload = __import__("json").loads(selector.calls[0][0].split("\n")[-1])
    assert [row["action_index"] for row in payload["unbound_actions"]] == [1]
    assert payload["retained_verified_owners"] == [
        {"action_index": 0, "source_quote": "Fight alien enemies"}]
    assert "Fight alien enemies" not in [
        row["quote"] for row in payload["candidate_source_spans"]]


def test_repair_may_not_reassign_valid_owner_even_when_model_invents_an_index():
    class HostileRebinder:
        def complete_json(self, prompt, **kwargs):
            return {"bindings": [
                {"action_index": 0, "source_id": "s1"},
            ]}
    with pytest.raises(SourceActionBindingError, match="MAPPING_INVALID"):
        verify_or_bind_actions(HostileRebinder(),
            "Fight alien enemies and colonize planets", [
                {"source_quote": "Fight alien enemies",
                 "action": "Fight hostile alien enemies"},
                {"source_quote": "translated colony",
                 "action": "Establish colonies on planets"},
            ])
