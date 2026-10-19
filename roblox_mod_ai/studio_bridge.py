"""Native Roblox Studio MCP client. Uses official local stdio transport.

Not available inside Colab/Linux. Calls require a locally running Studio with
MCP enabled and an installed optional Python 'mcp' SDK. No fake fallbacks.
"""
from __future__ import annotations

import asyncio
import os
import platform
from pathlib import Path
from typing import Any

ALLOWED_READ = frozenset({"get_studio_state", "screen_capture", "skill", "search_game_tree",
    "inspect_instance", "script_read", "script_search", "script_grep",
    "get_console_output", "list_roblox_studios"})
ALLOWED_ACTIONS = frozenset({"start_stop_play", "execute_luau",
    "character_navigation", "user_keyboard_input", "user_mouse_input"})

def studio_command(system: str | None = None) -> tuple[str,list[str]]:
    system=(system or platform.system()).lower()
    if system=="windows":
        return "cmd.exe", ["/c", "%LOCALAPPDATA%\\Roblox\\mcp.bat"]
    if system=="darwin":
        return "/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP", []
    raise RuntimeError("Native Roblox Studio MCP requires local Windows/macOS Studio")

class StudioMCPClient:
    async def call(self, tool_name: str, arguments: dict[str,Any] | None = None,
                   allow_write: bool = False) -> dict:
        if tool_name not in ALLOWED_READ and tool_name not in ALLOWED_ACTIONS:
            raise PermissionError("Unapproved Studio tool: "+tool_name)
        if tool_name in ALLOWED_ACTIONS and not allow_write:
            raise PermissionError("Studio interactions require explicit allow_write=True")
        command,args=studio_command()
        try:
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client, StdioServerParameters
        except ImportError as exc:
            raise RuntimeError("Install optional extra: pip install 'mcp>=1.0'") from exc
        from mcp.client.stdio import StdioServerParameters
        params=StdioServerParameters(command=command,args=args)
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                # Do not assume Studio implements a particular tool version.
                catalog=await session.list_tools()
                if tool_name not in {x.name for x in catalog.tools}:
                    raise RuntimeError("Studio MCP tool unavailable: "+tool_name)
                result=await session.call_tool(tool_name,arguments=arguments or {})
                return {"passed":not bool(result.isError),
                        "tool":tool_name,
                        "content":[str(x.text) for x in result.content if getattr(x,"type",None)=="text"],
                        "media":[{"mimeType":getattr(x, "mimeType", "image/png"),
                                  "data":str(getattr(x, "data", ""))}
                                 for x in result.content if getattr(x, "type", None)=="image"],
                        "executed":True}

    def run(self, tool_name: str, arguments: dict[str,Any] | None = None,
            allow_write: bool=False) -> dict:
        try:
            return asyncio.run(self.call(tool_name, arguments, allow_write))
        except (RuntimeError,PermissionError,OSError,ImportError) as exc:
            return {"passed":False,"executed":False,"tool":tool_name,"reason":str(exc)}
