"""Traceability is factual provenance, never an invented Roblox playtest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.pre_design_research import build_request_ledger
from roblox_mod_ai.request_traceability import build_request_traceability
from roblox_mod_ai.spec import RobloxProposal


def test_source_only_build_stores_requirement_files_without_engine_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_PREDESIGN_LIVE_SEARCH", "0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "0")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    session = CompleteRobloxAISession(output_root=tmp_path)
    reply = session.plan("상점에서 아이템 구매")
    assert reply.ready_to_build
    result = session.build(source_only=True)
    project = Path(result.project_dir)
    report = json.loads((project / "request_traceability.json").read_text(encoding="utf-8"))
    assert report["schema"] == "rmm/request-traceability-v1"
    assert report["original_prompt_sha256"] == hashlib.sha256(
        "상점에서 아이템 구매".encode("utf-8")).hexdigest()
    assert not report["roblox_engine_executed"]
    assert len(report["requirements"]) == 1
    requirement = report["requirements"][0]
    assert requirement["status"] == "source_generated_not_engine_verified"
    assert any(file["module"] == "ShopService" for file in requirement["module_files"])
    for item in requirement["module_files"]:
        assert item["source_present"]
        assert item["source_sha256"] == hashlib.sha256(
            (project / item["path"]).read_bytes()
        ).hexdigest()


def test_unresolved_custom_game_remains_unresolved_in_trace():
    prompt = "우주선 구매해서 조립하고 우주로 간다"
    ledger = build_request_ledger(prompt)
    proposal = RobloxProposal(
        requested_prompt=prompt, game_title="SpaceTest", description="",
        game_design={"pre_design_research": {"status": "live_disabled", "ledger": ledger}},
        modules=[],
    )
    report = build_request_traceability(proposal)
    assert report["pending_decomposition"]
    assert report["requirements"][0]["status"] == "unresolved"
    assert not report["requirements"][0]["module_files"]
    assert report["static_acceptance_passed"] is None
    assert report["roblox_engine_executed"] is False
