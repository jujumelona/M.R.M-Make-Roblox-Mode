"""Regression: Roblox add-ons cannot masquerade as replacement full games."""
import json
from pathlib import Path

import pytest
from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.project_modes import EXISTING_ADDON


def test_explicit_owned_addon_has_no_baseplace_and_no_rojo_replace(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    plan = session.plan("코인 수집 상점 검투 아레나", project_mode=EXISTING_ADDON)
    assert plan.authored_plan.proposal.game_design["project_mode"] == EXISTING_ADDON
    result = session.build(source_only=True)
    root = Path(result.project_dir)
    assert result.metadata["acceptance"]["passed"], result.metadata["acceptance"]
    assert result.metadata["addon_prepared"] is True
    assert result.success is True  # Owned additive sources prepared, no Studio claim.
    assert result.metadata["release_status"] == "addon_packaged"
    assert result.playtest_report.total_tests == 0
    assert not (root / "default.project.json").exists()
    assert not result.rbxlx_path
    assert Path(result.project_zip_path).is_file()
    manifest = json.loads((root / "addon.manifest.json").read_text(encoding="utf-8"))
    assert "Coins" in manifest["workspace_additions"]
    assert "ShopStalls" in manifest["workspace_additions"]
    assert "Baseplate" not in manifest["workspace_additions"]
    assert "SpawnLocation" not in manifest["workspace_additions"]
    assert manifest["ownership_required"] and not manifest["auto_publish"]
    assert "PlayerDataManager" in " ".join(manifest["source_modules"])


def test_unsupported_project_type_is_rejected():
    with pytest.raises(ValueError):
        RobloxGameDesignPlanner().plan("코인 상점", project_mode="third_party_exploit")


def test_default_full_place_unchanged(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 상점")
    result = session.build(source_only=True)
    assert (Path(result.project_dir) / "default.project.json").is_file()
    assert result.metadata["addon_prepared"] is False
