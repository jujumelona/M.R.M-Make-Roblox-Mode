"""E2E planner-contract regression for all 7 parts of the uploaded space request.

This drives the *real* _design_by_facets + _clean_model_json orchestrator with
a deterministic fake local transport, not a real MiMo GGUF or Studio playtest.
In particular each prompt must omit the other six source requirements.
"""
import copy
import json

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect, DynamicDesignError
import pytest

_SPACE = [
    ("req-001", "intent-mining", "우주모드 인데 자원파밍 돈모으기 거래 등으로", "MiningTrade"),
    ("req-002", "intent-ship", "우주선을 부위마다 만들어서 만들수있고", "ShipBuilder"),
    ("req-003", "intent-crew", "무기 선원 우주선 성능을 거래 구매 등으로", "CrewWeapon"),
    ("req-004", "intent-upgrade", "업그레이드 확장 할 수 있고", "ShipUpgrade"),
    ("req-005", "intent-launch", "그렇게해서 우주로 나갈수있고", "LaunchTravel"),
    ("req-006", "intent-alien", "우주로 나가면 다른행성의 특수 광물 외게인과 싸움", "AlienCombat"),
    ("req-007", "intent-colony", "식민지화등 여러가지가 가능한 모드", "Colonization"),
]
_PROMPT = " ".join(x[2] for x in _SPACE)


class FakeLocalModel:
    def __init__(self):
        self.calls = []
    def complete_json(self, prompt, **kwargs):
        self.calls.append(prompt)
        payload = json.loads(prompt.split("\n")[-1])
        fid = payload["feature_id"]
        req, _, source, stem = next(x for x in _SPACE if x[1] == fid)
        assert payload["source_requirements"] == [
            {"id": req, "statement": source, "source": "user_prompt"}
        ]
        assert "overall_game_context" not in payload
        assert payload["game_context"]["scope"] == "only_this_source_clause"
        assert payload["game_context"]["original_request"] == _PROMPT
        # The earlier request was copied wholesale into every model call:
        # the mining feature then wrote ship construction and 14 remotes.
        for other_id, other_fid, other_source, _ in _SPACE:
            if other_fid != fid:
                assert other_source not in json.dumps(payload["source_requirements"], ensure_ascii=False)
        behavior = (
            "Server validates alien NPC enemy combat damage, defeat and health."
            if fid == "intent-alien" else
            "Server validates all " + stem + " operations and stores player progress."
        )
        return {
            "modules": [
                {"name": stem + "Server", "role": "server",
                 "requirement_ids": [req], "facet_ids": ["fac-001"],
                 "behavior": behavior, "uses_remotes": [stem + "Action"]},
                {"name": stem + "Client", "role": "client",
                 "requirement_ids": [req], "facet_ids": ["fac-002"],
                 "behavior": "Client sends " + stem +
                             " commands and displays server-confirmed updates.",
                 "uses_remotes": [stem + "Action"]},
            ],
            "remotes": [{"name": stem + "Action", "type": "RemoteEvent"}],
            "world_objects": [],
            "acceptance": [{"requirement_id": req,
                            "observable_result": "Player performs " + stem +
                                                 " and receives an authoritative game result."}],
            "acceptance_facets": [
                {"facet_id": "fac-001", "observable_result": stem + " server action works."},
                {"facet_id": "fac-002", "observable_result": stem + " player UI shows updates."},
            ],
        }



def _user_space_ledger():
    return {
        "original_prompt": _PROMPT,
        "requirements": [
            {"id": req, "statement": source, "source": "user_prompt"}
            for req, fid, source, stem in _SPACE
        ],
        "facets": [
            {"id": fid, "requirements": [req], "source_span": source}
            for req, fid, source, stem in _SPACE
        ],
    }


def test_failure_on_seventh_feature_resumes_six_without_new_model_calls(
        monkeypatch, tmp_path):
    """The 9B service can die after 6 completed slices without losing them."""
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    ledger = _user_space_ledger()

    class OfflineOnLast(FakeLocalModel):
        def complete_json(self, prompt, **kwargs):
            if '"feature_id": "intent-colony"' in prompt:
                self.calls.append(prompt)
                raise ConnectionError("local MiMo backend unavailable")
            return super().complete_json(prompt, **kwargs)

    offline = OfflineOnLast()
    first = {"ledger": copy.deepcopy(ledger), "evidence": []}
    with pytest.raises(DynamicDesignError, match="intent-colony"):
        RobloxDynamicArchitect(offline, checkpoint_dir=tmp_path).design(
            _PROMPT, first, [])
    assert len(offline.calls) == 9  # six successes, three honest failed retries
    cache = tmp_path / "architecture_subplans_checkpoint.json"
    assert cache.is_file()
    assert len(json.loads(cache.read_text(encoding="utf-8"))["facets"]) == 6

    online = FakeLocalModel()
    second = {"ledger": copy.deepcopy(ledger), "evidence": []}
    output = RobloxDynamicArchitect(online, checkpoint_dir=tmp_path).design(
        _PROMPT, second, [])
    assert len(online.calls) == 1, "Must not regenerate six verified architecture slices"
    assert len(output["modules"]) == 14
    assert [row["cache_hit"] for row in second["architecture_subplans"]] == (
        [True] * 6 + [False]
    )


def test_user_space_request_full_ledger_is_scoped_and_kept_without_replanning(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    ledger = {
        "original_prompt": _PROMPT,
        "requirements": [
            {"id": req, "statement": source, "source": "user_prompt"}
            for req, fid, source, stem in _SPACE
        ],
        "facets": [
            {"id": fid, "requirements": [req], "source_span": source}
            for req, fid, source, stem in _SPACE
        ],
    }
    model = FakeLocalModel()
    report = {"ledger": copy.deepcopy(ledger), "evidence": []}
    result = RobloxDynamicArchitect(router=model).design(_PROMPT, report, [])
    assert len(model.calls) == 7, report["architecture_attempts"]
    assert len(result["modules"]) == 14
    assert len(result["remotes"]) == 7
    assert set(result["module_facets"].values().__iter__().__next__()) <= {
        x[1] for x in _SPACE
    }
    assert {facet for refs in result["module_facets"].values() for facet in refs} == {
        fid for req, fid, source, stem in _SPACE
    }
    assert len(report["architecture_subplans"]) == 7
    assert all(row["validated"] for row in report["architecture_subplans"])
    assert all(row["passed"] for row in report["architecture_attempts"])
    assert report["architecture_assembly"]["validated"] is True
    assert report["architecture_assembly"]["gameplay_verified"] is False
