"""Standard Model Context Protocol (MCP) server for R.M.M (Roblox Mod & Experience AI)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .api import CompleteRobloxAISession
from .creator_store import RobloxCreatorStoreCatalog
from .official_docs import RobloxOfficialDocs
from .studio_bridge import StudioMCPClient
from .implementation_blueprint import audit_implementation_blueprint
from .luau_analyzer import LuauStaticAnalyzer
from .open_cloud import RobloxOpenCloudClient
from .playtest_runner import RobloxPlaytestRunner
from .project_generator import RobloxProjectGenerator
from .roblox_api_catalog import RobloxAPICatalog
from .roblox_toolchain import RobloxToolchainManager

SERVER_NAME = "rmm-roblox-mod-ai"
SERVER_VERSION = "0.1.0"


class RobloxMCPServer:
    """Provides discrete, fine-grained MCP tools for small AI models."""

    def __init__(self, workspace_root: str = "rmm-output") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.api_catalog = RobloxAPICatalog()
        self.creator_store = RobloxCreatorStoreCatalog()
        self.official_docs = RobloxOfficialDocs()
        self.studio_bridge = StudioMCPClient()
        self.analyzer = LuauStaticAnalyzer()
        self.playtest_runner = RobloxPlaytestRunner()
        self.open_cloud = RobloxOpenCloudClient()
        self.toolchain = RobloxToolchainManager()
        self.session = CompleteRobloxAISession(output_root=self.workspace_root)

    def _resolve_safe_path(self, rel_path: str) -> Path:
        """Validates that rel_path is strictly within self.workspace_root to prevent traversal."""
        if not rel_path or not isinstance(rel_path, str):
            raise ValueError("File path must be a non-empty string.")
        if "\0" in rel_path:
            raise ValueError("Null bytes in path are prohibited.")
        raw_path = Path(rel_path)
        if raw_path.is_absolute():
            raise PermissionError(f"Absolute path '{rel_path}' is not permitted. Paths must be relative to workspace.")

        resolved = (self.workspace_root / raw_path).resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            raise PermissionError(
                f"Directory traversal detected: path '{rel_path}' escapes workspace boundary '{self.workspace_root}'."
            )
        return resolved

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Returns tool declarations adhering to MCP protocol schema."""
        return [
            {
                "name": "roblox_api_search",
                "description": "Look up official Roblox Engine API methods, properties, and signals with code examples. Prevents hallucination of invalid Roblox functions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term (e.g. 'GetAsync', 'TweenService', 'FireServer')"},
                        "class_name": {"type": "string", "description": "Optional class name filter (e.g. 'DataStoreService')"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "roblox_creator_store_search",
                "description": "Search live Creator Store; no guessed fallback assets. Creator badge does not prove model-code safety.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Asset search query (e.g. 'sword', 'coin sound', 'car')"},
                        "asset_type": {"type": "string", "enum": ["Model", "Audio", "Decal", "MeshPart"], "default": "Model"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "roblox_official_docs_search",
                "description": "Search verified URLs and limited excerpts from official Roblox Creator Hub llms.txt; do not invent API signatures.",
                "inputSchema": {
                    "type":"object",
                    "properties":{"query":{"type":"string"},"limit":{"type":"integer","default":5}},
                    "required":["query"],
                },
            },
            {
                "name": "roblox_studio_status",
                "description": "Query the actual running local official Roblox Studio MCP (Windows/macOS only). Never simulates Studio.",
                "inputSchema": {"type":"object","properties":{}},
            },
            {
                "name": "roblox_studio_playtest",
                "description": "Operate local Studio MCP start_stop_play with explicitly approved commands. No cloud fallback.",
                "inputSchema": {"type":"object","properties":{
                    "arguments":{"type":"object"},
                    "allow_write":{"type":"boolean","default":False}
                }},
            },
            {
                "name": "roblox_luau_validate",
                "description": "Statically analyze and lint a Luau code snippet. Detects unbalanced blocks, syntax errors, and deprecated wait() calls.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Luau source code to analyze"},
                        "file_path": {"type": "string", "description": "Virtual file path (e.g. src/server/Game.server.luau)", "default": "script.luau"},
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "roblox_plan_experience",
                "description": "Decomposes a user game description into structured subsystems, modules, and Creator Store assets.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Natural language game description"},
                    },
                    "required": ["prompt"],
                },
            },
            {
                "name": "roblox_plan_audit",
                "description": "Inspect the current full requirement-to-module blueprint, integration obligations and unverified Studio tests. Fails on stale or unowned design.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "roblox_studio_inspect",
                "description": "Read actual connected local Studio state, tree, source or logs. No fabricated Studio responses.",
                "inputSchema": {"type": "object", "properties": {
                    "tool": {"type": "string", "enum": [
                        "get_studio_state", "list_roblox_studios",
                        "search_game_tree", "inspect_instance", "script_read",
                        "script_search", "script_grep", "get_console_output"]},
                    "arguments": {"type": "object"}}, "required": ["tool"]},
            },
            {
                "name": "roblox_studio_action",
                "description": "Perform an explicitly authorized local Studio playtest, input or Luau action; never deploys or simulates a running engine.",
                "inputSchema": {"type": "object", "properties": {
                    "tool": {"type": "string", "enum": [
                        "start_stop_play", "execute_luau", "character_navigation",
                        "user_keyboard_input", "user_mouse_input"]},
                    "arguments": {"type": "object"},
                    "allow_write": {"type": "boolean", "default": False}},
                    "required": ["tool", "allow_write"]},
            },
            {
                "name": "roblox_project_write",
                "description": "Writes or updates a Luau script within the active Roblox project directory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Relative path (e.g. src/server/Combat.server.luau)"},
                        "content": {"type": "string", "description": "Luau code content"},
                    },
                    "required": ["file_path", "content"],
                },
            },
            {
                "name": "roblox_project_read",
                "description": "Reads a script or configuration file from the active Roblox project directory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Relative path (e.g. default.project.json)"},
                    },
                    "required": ["file_path"],
                },
            },
            {
                "name": "roblox_playtest_run",
                "description": "Reports unexecuted Roblox headless tests as unverified; real playtests require Studio or Open Cloud.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "roblox_rbxlx_build",
                "description": "Compiles the full experience into a native Roblox XML Place file (.rbxlx) and project ZIP.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_name": {"type": "string", "default": "production-run"},
                    },
                },
            },
            {
                "name": "roblox_open_cloud_deploy",
                "description": "Publishes the generated .rbxlx place file to Roblox Open Cloud.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "universe_id": {"type": "string"},
                        "place_id": {"type": "string"},
                        "file_path": {"type": "string"},
                    },
                    "required": ["universe_id", "place_id", "file_path"],
                },
            },
            {
                "name": "roblox_toolchain_status",
                "description": "Checks the availability and version numbers of installed Roblox open-source tools (Rojo, Wally, Selene, StyLua, NPX).",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "roblox_toolchain_run",
                "description": "Runs official Roblox CLI tools directly: 'stylua' (format), 'selene' (lint), 'wally_install' (fetch packages), or 'rojo_build' (compile .rbxlx).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["stylua", "selene", "wally_install", "rojo_build"],
                            "description": "Action to run",
                        },
                        "target_dir": {"type": "string", "description": "Target project directory", "default": "."},
                    },
                    "required": ["action"],
                },
            },
        ]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Executes the specified tool with arguments and returns structured output."""
        try:
            if tool_name == "roblox_api_search":
                query = arguments.get("query", "")
                class_name = arguments.get("class_name")
                results = self.api_catalog.search(query=query, class_name=class_name)
                return {"results": results, "count": len(results)}

            elif tool_name == "roblox_official_docs_search":
                return self.official_docs.search(arguments.get("query",""),arguments.get("limit",5))

            elif tool_name == "roblox_studio_status":
                return self.studio_bridge.run("get_studio_state")

            elif tool_name == "roblox_studio_playtest":
                return self.studio_bridge.run("start_stop_play",arguments.get("arguments") or {},
                                              allow_write=arguments.get("allow_write") is True)

            elif tool_name == "roblox_creator_store_search":
                query = arguments.get("query", "")
                asset_type = arguments.get("asset_type", "Model")
                limit = arguments.get("limit", 5)
                assets = self.creator_store.search(query=query, asset_type=asset_type, limit=limit)
                return {"assets": [a.to_dict() for a in assets],
                        "error": self.creator_store.last_error}

            elif tool_name == "roblox_luau_validate":
                code = arguments.get("code", "")
                path = arguments.get("file_path", "script.luau")
                diags = self.analyzer.analyze_source(code, file_path=path)
                errors = [d for d in diags if d.severity == "ERROR"]
                return {
                    "passed": len(errors) == 0,
                    "diagnostics": [
                        {
                            "line": d.line_number,
                            "rule": d.rule,
                            "severity": d.severity,
                            "message": d.message,
                            "suggestion": d.suggestion,
                        }
                        for d in diags
                    ],
                }

            elif tool_name == "roblox_plan_experience":
                prompt = arguments.get("prompt", "")
                reply = self.session.plan(prompt)
                return {
                    "plan_text": reply.message,
                    "approval_hash": reply.approval_hash,
                    "modules": [m.to_dict() for m in reply.authored_plan.proposal.modules],
                    "implementation_blueprint": reply.authored_plan.proposal.game_design.get("implementation_blueprint"),
                }

            elif tool_name == "roblox_plan_audit":
                if not self.session.authored_plan:
                    return {"passed": False, "error": "No active proposal loaded"}
                return audit_implementation_blueprint(self.session.authored_plan.proposal)

            elif tool_name == "roblox_studio_inspect":
                requested = str(arguments.get("tool", ""))
                from .studio_bridge import ALLOWED_READ
                if requested not in ALLOWED_READ:
                    return {"passed": False, "error": "Studio read tool not approved"}
                return self.studio_bridge.run(requested, arguments.get("arguments") or {})

            elif tool_name == "roblox_studio_action":
                requested = str(arguments.get("tool", ""))
                from .studio_bridge import ALLOWED_ACTIONS
                if requested not in ALLOWED_ACTIONS or arguments.get("allow_write") is not True:
                    return {"passed": False, "error": "Explicit Studio action approval required"}
                return self.studio_bridge.run(requested, arguments.get("arguments") or {}, allow_write=True)

            elif tool_name == "roblox_project_write":
                rel_path = arguments.get("file_path", "")
                content = arguments.get("content", "")
                try:
                    dest = self._resolve_safe_path(rel_path)
                except (ValueError, PermissionError) as exc:
                    return {"error": str(exc), "success": False}
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                return {"success": True, "written_bytes": len(content), "path": str(dest)}

            elif tool_name == "roblox_project_read":
                rel_path = arguments.get("file_path", "")
                try:
                    src = self._resolve_safe_path(rel_path)
                except (ValueError, PermissionError) as exc:
                    return {"error": str(exc)}
                if not src.is_file():
                    return {"error": f"File not found: {rel_path}"}
                return {"content": src.read_text(encoding="utf-8"), "path": str(src)}

            elif tool_name == "roblox_playtest_run":
                if not self.session.authored_plan:
                    return {"error": "No active proposal loaded."}
                report = self.playtest_runner.run_headless_playtest(self.session.authored_plan.proposal)
                return report.to_dict()

            elif tool_name == "roblox_rbxlx_build":
                result = self.session.build(run_name=arguments.get("run_name", "mcp-run"))
                return {
                    "success": result.success,
                    "rbxlx_path": result.rbxlx_path,
                    "project_zip_path": result.project_zip_path,
                    "analysis": result.analysis_report.to_dict(),
                    "playtest": result.playtest_report.to_dict(),
                }

            elif tool_name == "roblox_open_cloud_deploy":
                res = self.open_cloud.publish_place(
                    arguments.get("universe_id", ""),
                    arguments.get("place_id", ""),
                    arguments.get("file_path", ""),
                )
                return res

            elif tool_name == "roblox_toolchain_status":
                return self.toolchain.get_status().to_dict()

            elif tool_name == "roblox_toolchain_run":
                action = arguments.get("action", "")
                target = arguments.get("target_dir", ".")
                try:
                    safe_target = self._resolve_safe_path(target)
                except (ValueError, PermissionError) as exc:
                    return {"error": str(exc)}
                resolved_target = str(safe_target)

                if action == "stylua":
                    return self.toolchain.run_stylua(resolved_target)
                elif action == "selene":
                    return self.toolchain.run_selene(resolved_target)
                elif action == "wally_install":
                    return self.toolchain.run_wally_install(resolved_target)
                elif action == "rojo_build":
                    out_file = Path(resolved_target) / "out.rbxlx"
                    proj_file = Path(resolved_target) / "default.project.json"
                    return self.toolchain.run_rojo_build(proj_file, out_file)
                else:
                    return {"error": f"Unknown toolchain action: {action}"}

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except Exception as exc:
            return {"error": str(exc), "tool": tool_name}

    def handle_json_rpc(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handles standard JSON-RPC 2.0 requests for MCP clients."""
        method = request.get("method")
        req_id = request.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                },
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tool_definitions()},
            }

        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            args = params.get("arguments", {})
            output = self.call_tool(tool_name, args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(output, indent=2, ensure_ascii=False)}]
                },
            }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def run_stdio(self) -> None:
        """Run standard I/O loop for MCP client communication."""
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            line_str = line.strip()
            if not line_str:
                continue
            try:
                payload = json.loads(line_str)
                response = self.handle_json_rpc(payload)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except Exception as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


def main() -> None:
    server = RobloxMCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
