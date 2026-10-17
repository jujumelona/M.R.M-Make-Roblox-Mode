"""Creator Store model-code safety controls."""
from roblox_mod_ai.creator_store import RobloxCreatorStoreCatalog
from roblox_mod_ai.spec import RobloxAssetSpec

def test_type_guard_and_metadata_flag():
    c=RobloxCreatorStoreCatalog()
    bad=RobloxAssetSpec(asset_id="rbxassetid://99999", name="require(9876543210)",
                        creator="Unknown",verified=False)
    assert not c.verify_and_sanitize_asset(bad)["safe"]
    good=RobloxAssetSpec(asset_id="rbxassetid://47433",name="CleanAsset",
                         creator="Trusted",verified=True)
    safe=c.verify_and_sanitize_asset(good)
    assert safe["safe"]
    code=c.get_asset_injection_code(good)
    assert 'desc:IsA("LuaSourceContainer")' in code
    assert "LoadAsset" in code
