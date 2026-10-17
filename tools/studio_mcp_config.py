"""Render official OS-specific Studio MCP configurations for a local agent."""
from __future__ import annotations
import json
from roblox_mod_ai.studio_bridge import studio_command

def studio_mcp_config(os_name: str) -> dict:
    command,args=studio_command(os_name)
    return {"mcpServers":{"Roblox_Studio":{"command":command,"args":args}}}

def main() -> None:
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--os",choices=["windows","darwin"],required=True)
    args=parser.parse_args()
    print(json.dumps(studio_mcp_config(args.os),indent=2))
if __name__=="__main__": main()
