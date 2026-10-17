"""MMM parity: request-ledger -> retrieval -> evidence handoff -> design.

Offline transport fakes return genuine-shaped docs, and never grant more authority
than the source observed. Production defaults to live Creator Hub retrieval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.pre_design_research import RobloxPreDesignResearch, build_request_ledger
from roblox_mod_ai.official_docs import RobloxOfficialDocs


def fake_docs_client():
    index = (
        "# Creator Hub\n"
        "- [RemoteEvent](/docs/en-us/scripting/events/remote.md): use Remotes\n"
        "- [ProximityPrompt](/docs/en-us/ui/proximity-prompts.md): interact\n"
        "- [DataStoreService](/docs/en-us/cloud-services/data-stores.md): store data\n"
        "- [Checkpoint](/docs/en-us/tutorials/use-case-tutorials/physics/obstacle-course.md): checkpoint\n"
        "- [NPC Pathfinding](/docs/en-us/characters/pathfinding.md): NPC agents\n"
        "- [VehicleSeat](/docs/en-us/parts/vehicles.md): driving\n"
    )

    def respond(request):
        assert request.url.host == "create.roblox.com"
        if request.url.path == "/docs/llms.txt":
            return httpx.Response(200, text=index)
        return httpx.Response(200, text=(
            "# Roblox API reference\n\n"
            "ProximityPrompt Roblox RemoteFunction gameplay interactions and "
            "server DataStoreService UpdateAsync NPC PathfindingService.\n"
        ))
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_requirements_are_preserved_before_any_search():
    prompt = "코인 수집, 검투 아레나 그리고 펫 부화 및 우주선 게임"
    ledger = build_request_ledger(prompt)
    assert ledger["original_prompt"] == prompt
    assert "pets" in ledger["unimplemented_facets"]
    assert ledger["request_sha256"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert len(ledger["requirements"]) >= 3
    assert any(f["id"] == "combat" for f in ledger["facets"])


def test_official_doc_retrieval_is_prompt_specific_and_hashed():
    with fake_docs_client() as client:
        retrieval = RobloxPreDesignResearch(
            docs=RobloxOfficialDocs(client=client),live_enabled=True
        )
        result = retrieval.research("상점과 코인 수집")
        assert result["status"] in ("grounded", "partial")
        official = [r for r in result["evidence"] if r["provider"] == "official_docs"]
        assert official
        assert {q["facet"] for q in result["queries"]} >= {"shop", "coins"}
        for item in official:
            assert item["url"].startswith("https://create.roblox.com/docs/")
            assert len(item["content_sha256"]) == 64
            assert item["grounding"] == "fetched_official_document"
            assert item["content_sha256"] == hashlib.sha256(
                item["excerpt"].encode("utf-8")
            ).hexdigest()
        assert not result["asset_candidates"]


def test_plan_calls_research_before_generation_and_saves_evidence(tmp_path: Path):
    with fake_docs_client() as client:
        research=RobloxPreDesignResearch(
            docs=RobloxOfficialDocs(client=client),live_enabled=True
        )
        planner=RobloxGameDesignPlanner(pre_design_research=research)
        session=CompleteRobloxAISession(output_root=tmp_path)
        session.planner=planner
        plan=session.plan("코인 수집, 상점")
        assert plan.ready_to_build
        stored=plan.authored_plan.proposal.game_design["pre_design_research"]
        assert stored["queries"]
        assert stored["ledger"]["original_prompt"]=="코인 수집, 상점"
        assert stored["evidence"]
        assert plan.authored_plan.structured_sections["request_ledger"] == stored["ledger"]
        saved=json.loads((tmp_path/"proposal.json").read_text(encoding="utf-8"))
        assert saved["proposal"]["game_design"]["pre_design_research"]==stored
        result=session.build(source_only=True)
        assert (Path(result.project_dir)/"pre_design_research.json").is_file()
        assert result.metadata["acceptance"]["passed"]


def test_unimplemented_requested_gameplay_never_passes_as_default_combat(tmp_path:Path):
    research=RobloxPreDesignResearch(live_enabled=False)
    session=CompleteRobloxAISession(output_root=tmp_path)
    session.planner=RobloxGameDesignPlanner(pre_design_research=research)
    reply=session.plan("펫 부화와 퀘스트")
    assert not reply.ready_to_build
    modules=[m.name for m in reply.authored_plan.proposal.modules]
    assert "CombatSystem" not in modules
    result=session.build(source_only=True)
    assert not result.success
    assert not result.metadata["acceptance"]["passed"]
    assert "planning.request_coverage" in {x["id"] for x in
        result.metadata["acceptance"]["checks"] if not x["passed"]}


def test_revision_researches_complete_updated_request(tmp_path:Path):
    with fake_docs_client() as client:
        docs=RobloxOfficialDocs(client=client)
        session=CompleteRobloxAISession(output_root=tmp_path)
        session.planner=RobloxGameDesignPlanner(pre_design_research=
            RobloxPreDesignResearch(docs=docs,live_enabled=True))
        session.plan("코인 수집")
        result=session.revise("상점 추가")
        pre=result.authored_plan.proposal.game_design["pre_design_research"]
        assert pre["ledger"]["original_prompt"]==result.authored_plan.proposal.requested_prompt
        assert {q["facet"] for q in pre["queries"]}>={"coins","shop"}
        assert result.authored_plan.checkpoints[-1]["hash"]==result.approval_hash


def test_no_search_fabrication_when_provider_unavailable():
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(503))) as client:
        result=RobloxPreDesignResearch(
            docs=RobloxOfficialDocs(client=client),live_enabled=True).research("코인")
        assert result["status"]=="unresolved"
        assert not any(x["provider"]=="official_docs" for x in result["evidence"])
        assert result["provider_failures"]
        assert all(q["status"]=="no_fetched_evidence" for q in result["queries"])


def test_docs_offline_is_labelled_not_a_real_fetch():
    result=RobloxPreDesignResearch(live_enabled=False).research("코인 상점")
    assert result["status"]=="live_disabled"
    assert not any(x["provider"]=="official_docs" for x in result["evidence"])
    assert any(x["provider"]=="local_api_index" for x in result["evidence"])


class QueryOnlyModel:
    def complete_json(self, prompt, **kwargs):
        return {"searches":[
            {"source_span":"펫 부화","english_query":"PathfindingService pet hatching follower"},
            {"source_span":"unmentioned dungeon","english_query":"Roblox dungeon loot"}]}

def test_small_model_query_rewrite_only_uses_exact_prompt_spans(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION","1")
    with fake_docs_client() as client:
        result=RobloxPreDesignResearch(
            docs=RobloxOfficialDocs(client=client),
            live_enabled=True,router=QueryOnlyModel()
        ).research("펫 부화")
    ids={q["facet"] for q in result["queries"]}
    assert "pets" in ids
    assert len([x for x in ids if x.startswith("semantic-")])==1
    assert "dungeon" not in " ".join(q["query"] for q in result["queries"])
    assert "pets" in result["ledger"]["unimplemented_facets"]


def test_command_exposes_saved_research_without_fabricated_official_docs(tmp_path,monkeypatch):
    from roblox_mod_ai import cli
    import sys
    monkeypatch.setattr(sys,"argv",["rmm","research","코인 상점","--offline",
                                    "--output",str(tmp_path/"research.json")])
    cli.main()
    result=json.loads((tmp_path/"research.json").read_text(encoding="utf-8"))
    assert result["status"]=="live_disabled"
    assert result["ledger"]["original_prompt"]=="코인 상점"
    assert not [x for x in result["evidence"] if x["provider"]=="official_docs"]


def test_researched_module_references_are_source_bound(tmp_path):
    with fake_docs_client() as client:
        research=RobloxPreDesignResearch(
            docs=RobloxOfficialDocs(client=client),live_enabled=True)
        planner=RobloxGameDesignPlanner(pre_design_research=research)
        plan=planner.plan("코인 수집, 상점")
        p=plan.proposal
        sources={e["url"] for e in p.game_design["pre_design_research"]["evidence"]
                 if e["provider"]=="official_docs"}
        shop=next(m for m in p.modules if m.name=="ShopService")
        assert shop.evidence_refs
        assert set(shop.evidence_refs)<=sources
        saved=p.to_dict()
        restored=type(p).from_dict(saved)
        assert next(m for m in restored.modules if m.name=="ShopService").evidence_refs==shop.evidence_refs
