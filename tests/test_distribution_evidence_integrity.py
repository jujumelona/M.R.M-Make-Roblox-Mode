"""Regression checks from a real, successfully packaged Combat+Shop arena.

The build had matching Luau and rbxlx bytes, but its RAG cited humanoid
rigging art as damage API evidence; saved acceptance text disappeared from
request_traceability, and final ZIP omitted the packaging stage receipt.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roblox_mod_ai.official_docs import RobloxOfficialDocs
from roblox_mod_ai.pre_design_research import _documentation_relevant
from roblox_mod_ai.request_traceability import build_request_traceability
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.quality_gates import make_artifact_manifest


def test_combat_rigging_pages_are_not_api_evidence():
    for url, excerpt in (
        ("https://create.roblox.com/docs/en-us/art/modeling/rig-a-humanoid-model.md",
         "You can rig a Humanoid model with bones"),
        ("https://create.roblox.com/docs/en-us/art/modeling/skin-a-humanoid-model.md",
         "Humanoid armature and upper arms"),
    ):
        assert not _documentation_relevant("combat", url, excerpt)
    assert _documentation_relevant(
        "combat",
        "https://create.roblox.com/docs/reference/engine/classes/Humanoid.md",
        "Method: Humanoid:TakeDamage(amount: number)")


def test_exact_member_lookup_requires_real_fetched_signature():
    docs = RobloxOfficialDocs()
    url = "https://create.roblox.com/docs/reference/engine/classes/Humanoid.md"
    with patch.object(docs, "_get", return_value="# Class Humanoid\n"
                      "### Method: Humanoid:TakeDamage(amount: number)\n"
                      "Damages the humanoid."):
        found = docs.read_exact(url, "TakeDamage")
    assert found["error"] is None
    assert len(found["results"]) == 1
    assert "TakeDamage" in found["results"][0]["excerpt"]
    with patch.object(docs, "_get", return_value="# Rig a Humanoid model\nBones"):
        missing = docs.read_exact(url, "TakeDamage")
    assert missing["results"] == []
    assert missing["error"]


def test_requirement_trace_includes_observable_acceptance_and_round_owners():
    def module(name):
        return SimpleNamespace(name=name, file_path=f"src/server/{name}.server.luau",
                               code="--!strict\nreturn 1\n", module_id="mod_" + name)
    names = ("CombatSystem", "CombatController", "PlayerDataManager",
             "HUDController", "ArenaRoundService", "RoundController")
    plan = SimpleNamespace(requested_prompt="arena leaderboard",
        modules=[module(name) for name in names],
        game_design={
            "pre_design_research": {
                "status": "partial",
                "ledger": {
                    "requirements": [{"id": "req-3", "statement": "arena leaderboard"}],
                    "facets": [
                        {"id": "combat", "requirements": ["req-3"]},
                        {"id": "leaderboard", "requirements": ["req-3"]}],
                    "unmatched_requirements": [], "unimplemented_facets": [],
                    "decomposition_pending": []}},
            "implementation_blueprint": {"requirements": [{
                "id": "req-3", "owners": list(names),
                "acceptance": "At least 2 fighters; winner gets Wins"}]},
        })
    result = build_request_traceability(plan)
    req = result["requirements"][0]
    assert req["acceptance_criterion_proposed"] == "At least 2 fighters; winner gets Wins"
    assert {m["module"] for m in req["module_files"]} == set(names)
    assert req["runtime_observed"] is False


def test_final_package_manifest_includes_receipt_and_last_trajectory(tmp_path):
    place = tmp_path / "game.rbxlx"
    place.write_bytes(b"<roblox>signed-output</roblox>")
    project = tmp_path / "game"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "server.luau").write_text("return 1", encoding="utf-8")
    (project / "work_receipt.json").write_text(
        json.dumps({"overall_success": True, "stages": [{"stage": "package",
                                                       "success": True}]}))
    (project / "agent_trajectory.json").write_text(
        json.dumps({"steps": [{"phase": "result", "passed": True}]}))
    manifest = make_artifact_manifest(project, place)
    (project / "artifact_manifest.json").write_text(json.dumps(manifest))
    generator = RobloxProjectGenerator(tmp_path)
    archive_path = tmp_path / "game.zip"
    generator.pack_project_zip(project, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert "work_receipt.json" in archive.namelist()
        assert "agent_trajectory.json" in archive.namelist()
        assert hashlib.sha256(place.read_bytes()).hexdigest() == manifest["place_sha256"]
        for path, digest in manifest["source_files"].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == digest
