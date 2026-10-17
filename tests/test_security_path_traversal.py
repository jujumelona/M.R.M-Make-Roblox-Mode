"""Security tests verifying protection against path traversal in MCP server."""

from pathlib import Path
import pytest
from roblox_mod_ai.mcp_server import RobloxMCPServer


def test_mcp_path_traversal_prevention(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    server = RobloxMCPServer(workspace_root=str(workspace))

    # 1. Attempt path traversal in roblox_project_write
    res = server.call_tool("roblox_project_write", {
        "file_path": "../../secret.txt",
        "content": "malicious content",
    })
    assert res.get("success") is False
    assert "Directory traversal detected" in res.get("error", "")
    assert not (tmp_path / "secret.txt").exists()

    # 2. Attempt absolute path in roblox_project_write
    res_abs = server.call_tool("roblox_project_write", {
        "file_path": "C:/Windows/System32/evil.dll" if Path("C:/").is_dir() else "/etc/evil.so",
        "content": "malicious content",
    })
    assert res_abs.get("success") is False
    assert "Absolute path" in res_abs.get("error", "")

    # 3. Attempt null-byte injection
    res_null = server.call_tool("roblox_project_write", {
        "file_path": "valid_name.luau\0../evil.luau",
        "content": "malicious content",
    })
    assert res_null.get("success") is False
    assert "Null bytes" in res_null.get("error", "")

    # 4. Attempt path traversal in roblox_project_read
    secret_file = tmp_path / "outside_secret.txt"
    secret_file.write_text("classified data", encoding="utf-8")

    res_read = server.call_tool("roblox_project_read", {
        "file_path": "../outside_secret.txt",
    })
    assert "error" in res_read
    assert "Directory traversal detected" in res_read.get("error", "")
    assert "content" not in res_read

    # 5. Legitimate write and read inside workspace should succeed
    write_ok = server.call_tool("roblox_project_write", {
        "file_path": "src/server/Game.server.luau",
        "content": "print('Hello Roblox!')",
    })
    assert write_ok.get("success") is True
    assert (workspace / "src" / "server" / "Game.server.luau").is_file()

    read_ok = server.call_tool("roblox_project_read", {
        "file_path": "src/server/Game.server.luau",
    })
    assert read_ok.get("content") == "print('Hello Roblox!')"
