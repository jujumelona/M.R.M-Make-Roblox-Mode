"""Tests for RobloxCreatorStoreCatalog."""

from roblox_mod_ai.creator_store import RobloxCreatorStoreCatalog


def test_creator_store_curated_search():
    catalog = RobloxCreatorStoreCatalog()
    results = catalog.search("sword", asset_type="Model", limit=3)
    assert len(results) > 0
    assert any("sword" in r.name.lower() for r in results)

    # Test asset code generation
    sword_asset = results[0]
    code = catalog.get_asset_injection_code(sword_asset)
    assert "InsertService" in code or "Sound" in code


def test_creator_store_audio_search():
    catalog = RobloxCreatorStoreCatalog()
    results = catalog.search("coin sound", asset_type="Audio", limit=2)
    assert len(results) > 0
    audio_asset = results[0]
    code = catalog.get_asset_injection_code(audio_asset)
    assert "SoundService" in code
