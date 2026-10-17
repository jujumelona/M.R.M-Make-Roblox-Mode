"""Offline tests for current Creator Store API: no invented fallback."""
import httpx
from roblox_mod_ai.creator_store import RobloxCreatorStoreCatalog

def transport(request):
    if request.method == "POST":
        assert request.url.path == "/toolbox-service/v2/assets:search"
        body = __import__("json").loads(request.content)
        assert body["searchCategoryType"] in ("Model","Audio")
        assert body["query"]
        typ = body["searchCategoryType"]
        return httpx.Response(200,json={"creatorStoreAssets":[{
            "asset":{"id":"47433" if typ=="Model" else "9114223174",
                     "name":"Verified Sword" if typ=="Model" else "Verified Coin Sound"},
            "creator":{"name":"Trusted","hasVerifiedBadge":True}
        }]})
    if request.method=="GET":
        key=request.url.path.rsplit("/",1)[-1]
        return httpx.Response(200,json={"asset":{"id":key,"name":"Verified"}})
    return httpx.Response(405)

def catalog():
    return httpx.Client(transport=httpx.MockTransport(transport))

def test_official_post_search_and_detail_model():
    with catalog() as client:
        c=RobloxCreatorStoreCatalog(client=client)
        models=c.search("sword",asset_type="Model",limit=1)
        assert len(models)==1 and models[0].verified
        import pytest
        with pytest.raises(ValueError):
            c.get_asset_injection_code(models[0])

def test_official_post_search_audio():
    with catalog() as client:
        c=RobloxCreatorStoreCatalog(client=client)
        assert len(c.search("coin",asset_type="Audio"))==1

def test_no_fabricated_results():
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(503))) as client:
        c=RobloxCreatorStoreCatalog(client=client)
        assert c.search("Shop NPC",asset_type="Model")==[]
        assert c.last_error is not None

def test_blank_input_never_queries():
    with httpx.Client(transport=httpx.MockTransport(lambda _:(_ for _ in ()).throw(AssertionError()))) as client:
        assert RobloxCreatorStoreCatalog(client=client).search("  ")==[]

def test_unverified_not_auto_loaded():
    from roblox_mod_ai.spec import RobloxAssetSpec
    import pytest
    a=RobloxAssetSpec(asset_id="rbxassetid://12345",name="Unverified",creator="Other")
    with pytest.raises(ValueError):
        RobloxCreatorStoreCatalog().get_asset_injection_code(a)
