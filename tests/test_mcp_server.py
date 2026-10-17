"""Tests for RobloxMCPServer and Roblox API Catalog."""

from roblox_mod_ai.mcp_server import RobloxMCPServer
from roblox_mod_ai.roblox_api_catalog import RobloxAPICatalog


def test_roblox_api_catalog():
    catalog = RobloxAPICatalog()
    results = catalog.search("GetAsync", class_name="GlobalDataStore")
    assert len(results) >= 1
    assert results[0]["member_name"] == "GetAsync"
    assert "pcall" in results[0]["description"] or "pcall" in results[0]["example"]


def test_mcp_server_tool_definitions():
    server = RobloxMCPServer()
    tools = server.get_tool_definitions()
    tool_names = [t["name"] for t in tools]

    assert "roblox_api_search" in tool_names
    assert "roblox_creator_store_search" in tool_names
    assert "roblox_luau_validate" in tool_names
    assert "roblox_plan_experience" in tool_names
    assert "roblox_project_write" in tool_names
    assert "roblox_playtest_run" in tool_names
    assert "roblox_rbxlx_build" in tool_names
    assert "roblox_open_cloud_deploy" in tool_names


def test_mcp_server_tool_calling():
    server = RobloxMCPServer()

    # 1. API Search
    api_res = server.call_tool("roblox_api_search", {"query": "FireServer"})
    assert api_res["count"] >= 1
    assert api_res["results"][0]["member_name"] == "FireServer"

    # 2. Creator Store Search
    asset_res = server.call_tool("roblox_creator_store_search", {"query": "sword", "limit": 2})
    assert len(asset_res["assets"]) >= 1

    # 3. Luau Validate
    val_res = server.call_tool("roblox_luau_validate", {"code": "--!strict\nwait(1)"})
    assert val_res["passed"]
    assert any(d["rule"] == "DEPRECATED_GLOBAL_WAIT" for d in val_res["diagnostics"])


def test_mcp_server_json_rpc():
    server = RobloxMCPServer()

    # 1. Initialize
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    init_resp = server.handle_json_rpc(init_req)
    assert init_resp["result"]["serverInfo"]["name"] == "rmm-roblox-mod-ai"

    # 2. Tools List
    list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    list_resp = server.handle_json_rpc(list_req)
    assert len(list_resp["result"]["tools"]) >= 8

    # 3. Tools Call
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "roblox_api_search",
            "arguments": {"query": "TweenService"},
        },
    }
    call_resp = server.handle_json_rpc(call_req)
    assert "result" in call_resp
    assert "TweenService" in call_resp["result"]["content"][0]["text"]


def test_roblox_model_registry():
    from roblox_mod_ai.model_registry import RobloxModelRegistry
    models = RobloxModelRegistry.list_models()
    assert len(models) >= 4
    model_ids = [m["model_id"] for m in models]
    assert "roblox-coder-v2-gguf" in model_ids
    assert "roblox-luau-mistral-7b-lora" in model_ids

    meta = RobloxModelRegistry.get_model("roblox-coder-v2-gguf")
    assert meta is not None
    assert meta.recommended_vram_gb <= 8.0

