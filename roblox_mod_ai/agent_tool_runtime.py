"""Bounded, auditable Roblox tool use for *any* authored game mechanic.

The MCP server provides the same read-only API/docs/validation tools exposed
to external clients. The active proposal is inspected by an additional local,
read-only contract tool. No model may publish, modify Studio, run a build or
write a project through this channel. Those effects remain orchestrator-owned.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# The absence of a connected Studio is not a simulated Studio result.
APPROVED_MCP_READ_TOOLS = frozenset((
    "roblox_api_search",
    "roblox_official_docs_search",
    "roblox_luau_validate",
    "roblox_toolchain_status",
    "roblox_studio_status",
    "roblox_studio_inspect",
))
CONTRACT_TOOL = "roblox_module_contract_inspect"
MAX_TOOL_RESULT_CHARS = 2400


class RobloxToolPermissionError(ValueError):
    pass


def _preview(value: Any, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)[:limit]


def module_contract_snapshot(module: Any, proposal: Any) -> dict[str, Any]:
    """Facts from the actual authored plan, never inferred world/state names."""
    from .world_object_abi import world_names
    from .luau_service_contract import exported_methods

    dynamic = (proposal.game_design or {}).get("dynamic_design") or {}
    declared, authorized = world_names(proposal, module)
    module_id = module.module_id
    routed = list((dynamic.get("module_remotes") or {}).get(module_id) or [])
    routes = {
        key: (dynamic.get("host_actions") or {}).get(key)
        for key in routed
        if isinstance(key, str)
    }
    peer_methods = {}
    for peer in getattr(proposal, "modules", []):
        if peer is module or not peer.file_path.startswith("src/server/"):
            continue
        if peer.code:
            peer_methods[peer.name] = sorted(exported_methods(peer.code)[1])
    dependencies = [
        {"module_id": peer.module_id, "name": peer.name, "source_ready": bool(peer.code)}
        for peer in getattr(proposal, "modules", [])
        if peer.module_id in getattr(module, "depends_on", [])
    ]
    return {
        "module_id": module_id,
        "name": module.name,
        "path": module.file_path,
        "role": str(getattr(module.kind, "value", module.kind)),
        "description": str(module.description or "")[:900],
        "dependencies": dependencies,
        "linked_remotes": routes,
        "linked_world_objects": authorized,
        "all_declared_world_object_count": len(declared),
        "verified_peer_methods": peer_methods,
        "typed_actions": {
            remote: (dynamic.get("host_typed_actions") or {}).get(remote)
            for remote in routed
            if remote in (dynamic.get("host_typed_actions") or {})
        },
        "scope": "source_plan_only_not_runtime_verified",
    }


class RobloxAgentToolRuntime:
    """Strict per-module adapter between native tool calls and the MCP server."""

    def __init__(self, module: Any, proposal: Any, mcp: Any = None) -> None:
        self.module = module
        self.proposal = proposal
        self._mcp = mcp
        self.records: list[dict[str, Any]] = []

    def definitions(self) -> list[dict[str, Any]]:
        from .mcp_server import RobloxMCPServer
        declared = RobloxMCPServer.get_tool_definitions(None)
        tools = [entry for entry in declared
                 if entry["name"] in APPROVED_MCP_READ_TOOLS]
        tools.append({
            "name": CONTRACT_TOOL,
            "description": (
                "Inspect this module's actual declared remotes, approved world "
                "parts, loaded dependency source and exported sibling APIs. "
                "Use before generating state mutation code; does not create objects."
            ),
            "inputSchema": {"type": "object", "properties": {},
                            "additionalProperties": False},
        })
        # OpenAI-compatible function-call transport; original MCP schemas
        # remain the source of truth instead of free-form model function names.
        return [{
            "type": "function",
            "function": {
                "name": entry["name"],
                "description": entry["description"],
                "parameters": entry["inputSchema"],
            },
        } for entry in tools]

    @staticmethod
    def _validate_arguments(name: str, arguments: Any) -> dict[str, Any]:
        if name not in APPROVED_MCP_READ_TOOLS and name != CONTRACT_TOOL:
            raise RobloxToolPermissionError("TOOL_NOT_APPROVED: " + str(name)[:80])
        if not isinstance(arguments, dict):
            raise RobloxToolPermissionError("Tool arguments must be a JSON object")
        allowed = {
            CONTRACT_TOOL: frozenset(),
            "roblox_api_search": frozenset(("query", "class_name")),
            "roblox_official_docs_search": frozenset(("query", "limit")),
            "roblox_luau_validate": frozenset(("code", "file_path")),
            "roblox_toolchain_status": frozenset(),
            "roblox_studio_status": frozenset(),
            "roblox_studio_inspect": frozenset(("tool", "arguments")),
        }[name]
        if any(k not in allowed for k in arguments):
            raise RobloxToolPermissionError("Unknown tool argument")
        if name in ("roblox_api_search", "roblox_official_docs_search"):
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 300:
                raise RobloxToolPermissionError("Invalid bounded search query")
            if "class_name" in arguments and (
                    not isinstance(arguments["class_name"], str)
                    or len(arguments["class_name"]) > 90):
                raise RobloxToolPermissionError("Invalid API class")
            if "limit" in arguments and (
                    type(arguments["limit"]) is not int
                    or not 1 <= arguments["limit"] <= 5):
                raise RobloxToolPermissionError("Search limit must be 1..5")
        if name == "roblox_studio_inspect":
            requested = arguments.get("tool")
            approved = {
                "get_studio_state", "list_roblox_studios", "search_game_tree",
                "inspect_instance", "script_read", "script_search",
                "script_grep", "get_console_output",
            }
            if requested not in approved:
                raise RobloxToolPermissionError("Unapproved Studio read capability")
            nested = arguments.get("arguments", {})
            if not isinstance(nested, dict) or len(nested) > 10:
                raise RobloxToolPermissionError("Invalid Studio inspection arguments")
            if len(_preview(nested, 2001)) > 2000:
                raise RobloxToolPermissionError("Studio inspection arguments too large")
        if name == "roblox_luau_validate":
            code = arguments.get("code")
            if not isinstance(code, str) or not code or len(code) > 16000:
                raise RobloxToolPermissionError("Luau input must be 1..16000 chars")
            path = arguments.get("file_path", "script.luau")
            if not isinstance(path, str) or not re.fullmatch(
                    r"[A-Za-z0-9_./-]{1,150}\.luau", path
            ) or ".." in path:
                raise RobloxToolPermissionError("Unsafe virtual Luau path")
        return arguments

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Always return a real observation or a recorded error, never success-shaped data."""
        try:
            valid = self._validate_arguments(name, arguments)
            if name == CONTRACT_TOOL:
                data = module_contract_snapshot(self.module, self.proposal)
            else:
                if self._mcp is None:
                    from .mcp_server import RobloxMCPServer
                    self._mcp = RobloxMCPServer()
                data = self._mcp.call_tool(name, valid)
            if not isinstance(data, dict):
                raise TypeError("MCP tool returned a non-object response")
            error = data.get("error")
            if data.get("passed") is False and not error:
                error = "tool_reported_failed_check"
            ok = error is None
            result = {
                "ok": ok,
                "source": ("authored_module_contract" if name == CONTRACT_TOOL
                           else "roblox_mcp_tool"),
                "observation": _preview(data),
            }
            if error is not None:
                result["error"] = str(error)[:400]
        except Exception as exc:
            result = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:450],
                      "source": "tool_dispatch_rejected"}
        receipt = {
            "tool": name[:90],
            "arguments_preview": _preview(arguments, 360),
            "result_preview": _preview(result, 420),
            "args_sha256": hashlib.sha256(
                _preview(arguments, 20000).encode("utf-8")).hexdigest(),
            "ok": result["ok"], "source": result["source"],
            "observation_sha256": hashlib.sha256(
                result.get("observation", result.get("error", "")).encode("utf-8")
            ).hexdigest(),
        }
        if "error" in result:
            receipt["error"] = result["error"]
        self.records.append(receipt)
        return result
