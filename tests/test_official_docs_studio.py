import httpx
from roblox_mod_ai.official_docs import RobloxOfficialDocs
from roblox_mod_ai.studio_bridge import StudioMCPClient,studio_command
from tools.studio_mcp_config import studio_mcp_config

def test_roblox_docs_search_allowlist_and_excerpts():
    def handler(req):
        assert req.url.host=="create.roblox.com"
        if req.url.path.endswith("llms.txt"):
            return httpx.Response(200,text="- [DataStoreService](https://create.roblox.com/docs/reference/engine/classes/DataStoreService)\n")
        return httpx.Response(200,text="# DataStoreService\nGetDataStore(name)\n")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ret=RobloxOfficialDocs(client=client).search("DataStoreService")
        assert ret["error"] is None and ret["results"]
        assert "GetDataStore" in ret["results"][0]["excerpt"]

def test_official_docs_reject_other_hosts():
    assert not RobloxOfficialDocs.safe_url("https://evil.example/docs/llms.txt")
    assert not RobloxOfficialDocs.safe_url("http://create.roblox.com/docs/llms.txt")
    assert not RobloxOfficialDocs.safe_url("https://create.roblox.com.evil/docs/foo")
    assert RobloxOfficialDocs.safe_url("https://create.roblox.com/docs/llms.txt")

def test_native_studio_transport_config_and_failclosed():
    assert studio_mcp_config("windows")["mcpServers"]["Roblox_Studio"]["command"]=="cmd.exe"
    assert studio_mcp_config("darwin")["mcpServers"]["Roblox_Studio"]["command"].endswith("StudioMCP")
    assert not StudioMCPClient().run("execute_luau",{"code":"print(1)"})["passed"]
    assert not StudioMCPClient().run("get_studio_state").get("passed",False) if __import__("platform").system().lower() not in ("windows","darwin") else True
