"""Tests for Creator Store asset type segregation and script backdoor sanitization."""

from roblox_mod_ai.creator_store import RobloxCreatorStoreCatalog
from roblox_mod_ai.spec import RobloxAssetSpec


def test_creator_store_type_segregation():
    catalog = RobloxCreatorStoreCatalog()

    # When querying Model, only Model assets should be returned, never Audio
    models = catalog.search("sword", asset_type="Model", limit=3)
    assert len(models) > 0
    assert all(m.asset_type == "Model" for m in models)

    # When querying Audio, only Audio assets should be returned, never Model
    audios = catalog.search("coin", asset_type="Audio", limit=3)
    assert len(audios) > 0
    assert all(a.asset_type == "Audio" for a in audios)


def test_creator_store_backdoor_detection_and_sanitization():
    catalog = RobloxCreatorStoreCatalog()

    # Asset with suspicious require(assetId) backdoor
    suspicious_asset = RobloxAssetSpec(
        asset_id="rbxassetid://999999",
        name="Free VIP Sword",
        asset_type="Model",
        creator="UnknownScammer",
        destination_service="Workspace",
        description="Get free admin! require(9876543210)",
        verified=False,
    )

    verification = catalog.verify_and_sanitize_asset(suspicious_asset)
    assert verification["safe"] is False
    assert len(verification["warnings"]) > 0

    # Clean official asset
    clean_asset = RobloxAssetSpec(
        asset_id="rbxassetid://47433",
        name="Classic Sword",
        asset_type="Model",
        creator="Roblox",
        destination_service="StarterPack",
        description="Official sword",
        verified=True,
    )
    clean_verif = catalog.verify_and_sanitize_asset(clean_asset)
    assert clean_verif["safe"] is True

    # Injection code must contain script disabling sanitization
    injection_code = catalog.get_asset_injection_code(clean_asset, sanitize_scripts=True)
    assert "descendant.Enabled = false" in injection_code
    assert "InsertService:LoadAsset" in injection_code
