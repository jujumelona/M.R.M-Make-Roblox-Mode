"""Prompt-invariant CI: new Roblox host path is not a seven-part space template.

Metamorphic tests vary the CONTENT, language, number of independently sourced
mechanics, client/server interaction classes, number of systems in a feature,
and world object counts. These tests use deterministic semantic transports:
they establish CONTRACT robustness, not real-MiMo gameplay quality.
"""
from __future__ import annotations

import json
import random

import pytest

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.host_architecture import SEMANTIC_FACET_SCHEMA

CLAUSES = (
    ("PetNursery", "부화한 펫을 돌보고 먹이를 주면 성장시킨다", "event"),
    ("ObstacleCourse", "Players activate checkpoints in a parkour course", "event"),
    ("RaceKart", "Build a kart and race through timed laps", "request_response"),
    ("WordPuzzle", "사용자가 글자 퍼즐의 정답을 제출하고 판정받는다", "request_response"),
    ("Weather", "Simulate a dynamic rain cycle on a server", "none"),
    ("Garden", "꽃을 심고 물을 줘서 자라게 한다", "event"),
    ("Chess", "Submit a boardgame chess move and get legality result", "request_response"),
    ("Museum", "展示する作品の案内順を管理する", "none"),
    ("Fishing", "Catch fish with a rod and maintain fishing inventory", "event"),
    ("ConveyorFactory", "Create moving conveyor belts and automate packaging", "none"),
    ("StoryChoice", "Narrative branching story selection and saved choice", "request_response"),
    ("PlatformRhythm", "Replay percussion rhythm actions and award a combo", "event"),
    ("DoorAccess", "Scan a keypad credential to unlock laboratory doors", "request_response"),
    ("NightDay", "Update global day and night schedule without player inputs", "none"),
)


def _sample(seed: int, count: int):
    rng = random.Random(seed)
    entries = rng.sample(range(len(CLAUSES)), count)
    statements = []
    for k, index in enumerate(entries):
        label, clause, interaction = CLAUSES[index]
        # Prefix changed between cases so that no seven-facet assumption, name
        # or identifier can be hardcoded into successful outcomes.
        fid = f"source-{seed:03d}-{index:02d}-{k}"
        rid = f"requirement-{seed:03d}-{k:03d}"
        statements.append((fid, rid, label, clause, interaction))
    ledger = {
        "original_prompt": " | ".join(x[3] for x in statements),
        "requirements": [
            {"id": rid, "statement": clause, "source": "user_prompt"}
            for fid, rid, label, clause, mode in statements
        ],
        "facets": [
            {"id": fid, "requirements": [rid], "source_span": clause}
            for fid, rid, label, clause, mode in statements
        ],
    }
    return statements, ledger


class ArbitraryPromptSemanticTransport:
    def __init__(self, statements, *, systems_per_feature=1):
        self.entries = {fid: (rid, label, clause, interaction)
                        for fid, rid, label, clause, interaction in statements}
        self.calls = []
        self.systems_per_feature = systems_per_feature

    def complete_json(self, prompt, **options):
        payload = json.loads(prompt.split("\n")[-1])
        fid = payload["feature_id"]
        rid, label, clause, interaction = self.entries[fid]
        self.calls.append((fid, prompt, options))
        assert payload["source_requirements"] == [
            {"id": rid, "statement": clause, "source": "user_prompt"}
        ]
        assert "overall_game_context" not in payload
        assert options["json_schema"] == SEMANTIC_FACET_SCHEMA
        assert options["max_tokens"] <= 2600
        for other_id, (_, _, other_clause, _) in self.entries.items():
            if other_id != fid:
                assert other_clause not in prompt
        return {"systems": [
            {
                "name": label + ("Phase" + str(i) if self.systems_per_feature > 1 else ""),
                "server_behavior": (
                    "Validate input and maintain server-controlled state for "
                    + label + " and its distinct gameplay outcomes."
                ),
                "client_behavior": (
                    "Render a concrete control panel and show server-authoritative "
                    + label + " state and outcome."
                    if interaction != "none" else ""
                ),
                "interaction": interaction,
                "observable_result": (
                    "Players see server-confirmed " + label +
                    " gameplay state after an actual action."
                ),
                "world_entities": (
                    [label + "Object" + str(i)] if i % 2 == 0 else []
                ),
            }
            for i in range(self.systems_per_feature)
        ]}


@pytest.mark.parametrize("seed,count,systems", [
    (1, 1, 1), (2, 2, 1), (3, 3, 1), (4, 5, 1),
    (5, 7, 1), (6, 10, 1), (7, 12, 1),
    (10, 2, 2), (11, 3, 2), (12, 8, 2),
])
def test_unseen_genres_and_variable_size_use_same_host_architect(
        monkeypatch, seed, count, systems):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.delenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", raising=False)
    statements, ledger = _sample(seed, count)
    router = ArbitraryPromptSemanticTransport(
        statements, systems_per_feature=systems)
    research = {"ledger": ledger, "evidence": []}
    result = RobloxDynamicArchitect(router).design(
        ledger["original_prompt"], research, [])
    remotes_per_feature = sum(
        mode != "none" for _, rid, label, clause, mode in statements
    )
    assert len(router.calls) == count, research.get("architecture_attempts")
    assert len(result["modules"]) == (count + remotes_per_feature) * systems
    assert len(result["remotes"]) == remotes_per_feature * systems
    assert len(result.get("host_actions", {})) == remotes_per_feature * systems
    assert len(result["world_objects"]) == count * ((systems + 1) // 2)
    assert len(result["acceptance"]) == count
    assert len(result["acceptance_facets"]) == count
    assert len({m.name for m in result["modules"]}) == len(result["modules"])
    assert {fid for facets in result["module_facets"].values()
            for fid in facets} == set(x[0] for x in statements)
    assert research["architecture_assembly"]["validated"]
    assert not research["architecture_assembly"]["gameplay_verified"]
    assert all(
        row["validated"] for row in research["architecture_subplans"]
    )
    for fid, request, options in router.calls:
        assert "file paths, Roblox coordinates" in request
        assert fid in request
        assert '"modules"' not in request.split("\n")[-1]


def test_permutation_does_not_change_covered_mechanics_or_role_counts(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.delenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", raising=False)
    statements, _ = _sample(55, 8)
    outcomes = []
    for ordered in (statements, list(reversed(statements))):
        ledger = {
            "original_prompt": " | ".join(row[3] for row in ordered),
            "requirements": [
                {"id": rid, "statement": clause, "source": "user_prompt"}
                for fid, rid, name, clause, mode in ordered
            ],
            "facets": [
                {"id": fid, "requirements": [rid], "source_span": clause}
                for fid, rid, name, clause, mode in ordered
            ],
        }
        router = ArbitraryPromptSemanticTransport(ordered)
        design = RobloxDynamicArchitect(router).design(
            ledger["original_prompt"], {"ledger": ledger, "evidence": []}, [])
        outcomes.append({
            "facets": set(design["acceptance_facets"]),
            "remotes": set(design["remotes"]),
            "module_names": {m.name for m in design["modules"]},
            "module_count": len(design["modules"]),
        })
    assert outcomes[0] == outcomes[1]


def test_only_server_work_has_no_fabricated_client_or_remote(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.delenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", raising=False)
    clauses = [("only-server", "r1", "DayNightSchedule",
                "Cycle through daytime and nighttime periodically on server", "none")]
    ledger = {
        "original_prompt": clauses[0][3],
        "requirements": [{"id": "r1", "statement": clauses[0][3], "source": "user_prompt"}],
        "facets": [{"id": "only-server", "requirements": ["r1"],
                    "source_span": clauses[0][3]}],
    }
    plan = RobloxDynamicArchitect(
        ArbitraryPromptSemanticTransport(clauses)).design(
            ledger["original_prompt"], {"ledger": ledger, "evidence": []}, [])
    assert len(plan["modules"]) == 1
    assert plan["remotes"] == {}
    assert plan.get("host_actions") == {}
    assert not any(m.file_path.endswith(".client.luau") for m in plan["modules"])
