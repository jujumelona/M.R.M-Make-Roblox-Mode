"""Regression for uploaded proposal (12): 3 scoped 9B completions all used fac-001/fac-002
instead of the authoritative source-anchored intent-6d061fc96c feature id.

The model may design *behavior*, but feature ownership IDs are host-owned.
Other design rules remain strict. Tests use deterministic transport and do not
claim MiMo generated executable Roblox gameplay.
"""
import copy
import json
import pytest

from roblox_mod_ai.dynamic_architect import (
    RobloxDynamicArchitect, _bind_scoped_feature_ids,
    _clean_model_json, DynamicDesignError,
)


def _sample(facet_id="intent-6d061fc96c", req_id="req-001"):
    return {
        "modules": [
            {"name": "MiningEconomyServer", "role": "server",
             "requirement_ids": [req_id], "facet_ids": ["fac-001", "fac-002"],
             "behavior": "Validate mining input and trade spending on the server, then grant mining currency.",
             "uses_remotes": ["MiningPulse"]},
            {"name": "MiningEconomyClient", "role": "client",
             "requirement_ids": [req_id], "facet_ids": ["fac-001"],
             "behavior": "Provide mining button and currency HUD, invoke MiningPulse with selected ore.",
             "uses_remotes": ["MiningPulse"]},
        ],
        "remotes": [{"name": "MiningPulse", "type": "RemoteEvent"}],
        "world_objects": [],
        "acceptance": [{"requirement_id": req_id,
                        "observable_result": "Nearby ore mining grants validated currency."}],
        "acceptance_facets": [
            {"facet_id": "fac-001", "observable_result": "Mining produces server-owned currency."},
            {"facet_id": "fac-002", "observable_result": "Trade purchases use validated currency."},
        ],
    }


def _ledger():
    return {"requirements": [{"id": "req-001", "statement": "mine ore trade credits"}],
            "facets": [{"id": "intent-6d061fc96c", "requirements": ["req-001"],
                        "source_span": "mine ore trade credits"}],
            "original_prompt": "mine ore trade credits"}


def test_proposal12_alias_rebinding_preserves_behavior_and_strict_validation():
    original = _sample()
    with pytest.raises(DynamicDesignError, match="actual requested gameplay facets"):
        _clean_model_json(original, _ledger(), set())
    normalized, proof = _bind_scoped_feature_ids(
        original, facet_id="intent-6d061fc96c", owned_ids=["req-001"],
        all_facet_ids={"intent-6d061fc96c", "intent-b157431a7c"})
    assert proof["model_aliases"] == ["fac-001", "fac-002"]
    assert [x["facet_ids"] for x in normalized["modules"]] == [
        ["intent-6d061fc96c"], ["intent-6d061fc96c"]
    ]
    assert len(normalized["acceptance_facets"]) == 1
    assert "Trade purchases" in normalized["acceptance_facets"][0]["observable_result"]
    assert original["modules"][0]["facet_ids"] == ["fac-001", "fac-002"]
    checked = _clean_model_json(normalized, _ledger(), set())
    assert len(checked["modules"]) == 2
    assert checked["remotes"]["MiningPulse"] == "RemoteEvent"


def test_alias_binding_never_changes_other_facet_ownership_or_makes_empty_acceptance():
    foreign = _sample()
    foreign["modules"][0]["facet_ids"] = ["intent-b157431a7c"]
    with pytest.raises(DynamicDesignError, match="different original feature"):
        _bind_scoped_feature_ids(foreign, facet_id="intent-6d061fc96c",
                                 owned_ids=["req-001"],
                                 all_facet_ids={"intent-6d061fc96c", "intent-b157431a7c"})
    bad = _sample()
    bad["modules"][0]["requirement_ids"] = ["req-002"]
    with pytest.raises(DynamicDesignError, match="foreign or missing"):
        _bind_scoped_feature_ids(bad, facet_id="intent-6d061fc96c",
                                 owned_ids=["req-001"],
                                 all_facet_ids={"intent-6d061fc96c"})
    absent = _sample()
    absent["acceptance_facets"] = []
    with pytest.raises(DynamicDesignError, match="no facet acceptance"):
        _bind_scoped_feature_ids(absent, facet_id="intent-6d061fc96c",
                                 owned_ids=["req-001"],
                                 all_facet_ids={"intent-6d061fc96c"})


def test_scoped_three_feature_host_merge_does_not_regenerate_fake_ids(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    features = [
        ("intent-mine", "req-001", "mine ore trade credits", "Mining", "mining"),
        ("intent-ship", "req-002", "build and upgrade spaceship", "Ship", "ship"),
        ("intent-alien", "req-003", "fight alien enemies in combat", "AlienCombat", "alien combat"),
    ]
    ledger = {"original_prompt": "mine ore trade credits, build ship, fight alien enemies in combat",
              "requirements": [
                  {"id": rid, "statement": statement} for fid, rid, statement, name, subject in features
              ],
              "facets": [
                  {"id": fid, "requirements": [rid], "source_span": statement}
                  for fid, rid, statement, name, subject in features
              ]}
    class Model:
        def __init__(self):
            self.calls = 0
        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            payload = json.loads(prompt.split("\n")[-1])
            fid = payload["feature_id"]
            _, rid, statement, name, subject = next(row for row in features if row[0] == fid)
            remote = name + "Action"
            return {
                "modules": [
                    {"name": name + "Server", "role": "server",
                     "requirement_ids": [rid], "facet_ids": ["fac-001"],
                     "behavior": "Server validates " + subject +
                                 " events and owns the state, damage and money.",
                     "uses_remotes": [remote]},
                    {"name": name + "Client", "role": "client",
                     "requirement_ids": [rid], "facet_ids": ["fac-002"],
                     "behavior": "Client displays " + subject +
                                 " UI and submits the button input to server.",
                     "uses_remotes": [remote]},
                ],
                "remotes": [{"name": remote, "type": "RemoteEvent"}],
                "world_objects": [],
                "acceptance": [{"requirement_id": rid,
                                "observable_result": "Player can " + subject +
                                                     " and sees gameplay state updates."}],
                "acceptance_facets": [
                    {"facet_id": "fac-001",
                     "observable_result": "Server executes " + subject + " gameplay."},
                    {"facet_id": "fac-002",
                     "observable_result": "Client sees " + subject + " gameplay feedback."}],
            }
    model = Model()
    research = {"ledger": ledger, "evidence": []}
    plan = RobloxDynamicArchitect(router=model).design(ledger["original_prompt"], research, [])
    assert model.calls == 3, research.get("architecture_attempts")
    assert len(plan["modules"]) == 6
    assert len(research["architecture_subplans"]) == 3
    assert {fid for owner in plan["module_facets"].values() for fid in owner} == {
        "intent-mine", "intent-ship", "intent-alien"}
    assert all(record["id_binding"]["model_aliases"] == ["fac-001", "fac-002"]
               for record in research["architecture_subplans"])
