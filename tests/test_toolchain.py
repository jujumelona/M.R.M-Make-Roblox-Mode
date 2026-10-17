"""Tests for RobloxToolchainManager."""

from pathlib import Path
from roblox_mod_ai.mcp_server import RobloxMCPServer
from roblox_mod_ai.roblox_toolchain import RobloxToolchainManager


def test_toolchain_manager_status():
    manager = RobloxToolchainManager()
    status = manager.get_status()

    # status should return valid structure
    assert isinstance(status.rojo_available, bool)
    assert isinstance(status.wally_available, bool)
    assert isinstance(status.selene_available, bool)
    assert isinstance(status.stylua_available, bool)
    assert isinstance(status.npx_available, bool)

    status_dict = status.to_dict()
    assert "rojo" in status_dict
    assert "npx" in status_dict


def test_toolchain_manifest_generation():
    manager = RobloxToolchainManager()
    rokit_text = manager.generate_rokit_manifest()
    aftman_text = manager.generate_aftman_manifest()

    assert "rojo-rbx/rojo" in rokit_text
    assert "UpliftGames/wally" in rokit_text
    assert "Kampfkarren/selene" in rokit_text
    assert "JohnnyMorganz/StyLua" in rokit_text
    assert "rojo-rbx/rojo" in aftman_text


def test_toolchain_mcp_integration():
    server = RobloxMCPServer()
    tools = server.get_tool_definitions()
    tool_names = [t["name"] for t in tools]

    assert "roblox_toolchain_status" in tool_names
    assert "roblox_toolchain_run" in tool_names

    # Test status tool call
    res = server.call_tool("roblox_toolchain_status", {})
    assert "rojo" in res
    assert "wally" in res
    assert "npx" in res
    assert "available" in res["npx"]
    assert isinstance(res["npx"]["available"], bool)
