"""Roblox Creator Store account badge is NOT permission to execute third-party assets."""
import json
from pathlib import Path
import pytest
from roblox_mod_ai.spec import RobloxAssetSpec, RobloxProposal
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.creator_store import RobloxCreatorStoreCatalog

def test_asset_import_requires_manual_studio_review(tmp_path: Path):
    asset=RobloxAssetSpec(asset_id="rbxassetid://47433",name="Example Model",
                          creator="Roblox",verified=True)
    proposal=RobloxProposal(requested_prompt="coin game",game_title="X",description="",
                             game_design={},assets=[asset],modules=[])
    root=tmp_path/"project"
    RobloxProjectGenerator(root).materialize_project_tree(proposal,root)
    plan=json.loads((root/"creator_store_assets.json").read_text(encoding="utf-8"))
    assert plan["automatic_runtime_import"] is False
    assert plan["assets"][0]["game_usage_permission_verified"] is False
    assert plan["assets"][0]["content_sanitized"] is False
    assert not (root/"src/server/AssetLoader.server.luau").exists()
    with pytest.raises(ValueError):
        RobloxCreatorStoreCatalog().get_asset_injection_code(asset)
