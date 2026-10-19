"""Select only executable RMM validation capabilities; report *actual* evidence.

Do not confuse compilation, optional unit tests, or prepared Studio files with
executed Roblox engine scenarios. A missing tool never silently passes.
"""
from __future__ import annotations

from typing import Any

SCHEMA = "rmm/verification-selection-v1"


def make_verification_report(
    *, source_only: bool, addon_mode: bool, tool_results: dict[str, Any],
    analysis_passed: bool, acceptance: dict, artifact_ready: bool,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}

    def put(name: str, status: str, scope: str, reason: str = "") -> None:
        checks[name] = {
            "status": status, "executed": status in ("passed", "failed"),
            "scope": scope, "reason": reason,
        }

    def from_tool(name: str, key: str, scope: str, *, applicable: bool = True):
        if not applicable:
            put(name, "not_applicable", scope)
            return
        info = tool_results.get(key)
        if not isinstance(info, dict) or info.get("executed") is not True:
            reason = (
                info.get("reason") or info.get("message") or "Tool not executed"
                if isinstance(info, dict) else "No execution result recorded"
            )
            put(name, "not_run", scope, str(reason))
            return
        put(name, "passed" if info.get("success", info.get("passed")) is True
            else "failed", scope, str(info.get("error", "")))

    # The Python source checker is a lightweight baseline, not an engine pass.
    put("static_source", "passed" if analysis_passed else "failed",
        "Python-authored Luau static scan and source grammar checks")
    put("gameplay_contract", "passed" if acceptance.get("passed") is True else "failed",
        "on-disk module wiring, requirement coverage and gameplay lifecycle")

    real_place = not source_only and not addon_mode
    from_tool("stylua", "stylua", "formatter/parser", applicable=not source_only)
    from_tool("selene", "selene", "Lua/Luau linter", applicable=not source_only)
    from_tool("luau_analyze", "luau_analyze", "optional standalone Luau analyzer",
              applicable=not source_only)
    from_tool("lune_economy", "lune_economy", "pure generated EconomyRules unit tests",
              applicable=(not source_only and bool(tool_results.get("lune_economy_applicable"))))
    from_tool("rojo_build", "rojo", "Rojo-built local Place", applicable=real_place)
    structure = tool_results.get("compiled_structure")
    if not real_place:
        put("compiled_structure", "not_applicable", "binary Place structure and source map")
    elif not isinstance(structure, dict):
        put("compiled_structure", "not_run", "binary Place structure and source map",
            "Rojo build has not produced a Place")
    else:
        put("compiled_structure",
            "passed" if structure.get("passed") is True else "failed",
            "binary Place structure and source map")
    put("artifact", "passed" if artifact_ready else "failed",
        "packaged sources and Place hashes; not gameplay")
    put("studio_structure", "not_run", "optional Studio edit-mode CLI smoke",
        "Requires a locally installed Windows/macOS Roblox Studio; a generated script is not an executed test")
    put("studio_multiplayer", "not_run", "real client/server playtest",
        "Requires local Studio and actual game-specific scenarios; never run in Colab")
    put("datastore_rejoin", "not_run", "persisted live DataStore save/rejoin",
        "Requires a suitable published test experience; never inferred from offline Place")
    statuses = [x["status"] for x in checks.values()]
    return {
        "schema": SCHEMA,
        "selection_policy": "execute only applicable available tools; report skipped as NOT RUN",
        "checks": checks,
        "summary": {name: statuses.count(name) for name in (
            "passed", "failed", "not_run", "not_applicable")},
        "gameplay_verified": False,
        "studio_executed": False,
    }
