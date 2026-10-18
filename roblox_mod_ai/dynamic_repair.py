"""Bounded repair of actually executed Luau compiler/linter diagnostics.

Never retries a failed tool by changing an unrelated first-party template or by
silently ignoring a failed check.  The actual error must identify a dynamic
module source file.  The same external tool must pass again after the patch.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from .agent_loop import RobloxCodeRepairAgent
from .spec import RobloxProposal

def affected_dynamic_modules(proposal: RobloxProposal, diagnostics: str) -> list:
    # Exact path or basename required. Avoid "all files" retries.
    affected=[]
    normalized=diagnostics.replace("\\","/")
    for mod in proposal.modules:
        if not mod.module_id.startswith("dyn_"):
            continue
        if mod.file_path in normalized or Path(mod.file_path).name in normalized:
            affected.append(mod)
    return affected[:2]


def repair_tool_diagnostics(proposal: RobloxProposal, output_dir: Path,
                            tool_name: str, failed_result: dict[str, Any],
                            retry_tool: Callable[[], dict[str, Any]],
                            format_sources: Callable[[], dict[str, Any]] | None,
                            router, max_attempts: int = 3) -> dict[str, Any]:
    """Aider-style: real tool observation -> targeted edit -> same tool again.

    Repeated failures use the NEW tool stderr, not the stale first traceback.
    Every iteration and source path is included in the returned report.
    """
    if not failed_result.get("executed"):
        return {"passed": False, "reason": "Tool was not executed; missing binary cannot be repaired"}
    agent = RobloxCodeRepairAgent(router=router)
    result = failed_result
    history: list[dict[str, Any]] = []
    rewritten: set[str] = set()
    previous_diagnostic = ""
    for attempt in range(1, max_attempts + 1):
        diagnostics = (
            str(result.get("stderr") or "") + "\n" +
            str(result.get("stdout") or "") + "\n" +
            str(result.get("error") or "")
        )[:16000]
        selected = affected_dynamic_modules(proposal, diagnostics)
        if not selected:
            return {"passed": False, "tool": tool_name, "history": history,
                    "reason": "No exact generated module mentioned in current tool diagnostic",
                    "last_tool": result}
        if attempt > 1 and diagnostics == previous_diagnostic:
            return {"passed": False, "tool": tool_name, "history": history,
                    "reason": "Identical compiler error after previous correction",
                    "last_tool": result}
        previous_diagnostic = diagnostics
        attempt_record: dict[str, Any] = {
            "attempt": attempt, "diagnostics": diagnostics,
            "files": [m.file_path for m in selected],
        }
        try:
            for module in selected:
                fixed = agent.repair(module, proposal, existing_code=module.code,
                                     diagnostics=diagnostics, attempts=2)
                module.code = fixed
                target = output_dir / module.file_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(fixed, encoding="utf-8")
                rewritten.add(module.file_path)
            if format_sources is not None:
                formatted = format_sources()
                attempt_record["formatter"] = formatted
                if not formatted.get("executed") or not formatted.get("success"):
                    attempt_record["passed"] = False
                    history.append(attempt_record)
                    return {"passed": False, "tool": tool_name, "history": history,
                            "reason": "StyLua reformat failed", "last_tool": formatted}
                for module in selected:
                    module.code = (output_dir / module.file_path).read_text(
                        encoding="utf-8")
            result = retry_tool()
            attempt_record["retried_tool"] = result
            attempt_record["passed"] = bool(result.get("executed") and result.get("success"))
            history.append(attempt_record)
            if attempt_record["passed"]:
                return {"passed": True, "tool": tool_name,
                        "repaired": sorted(rewritten), "retried_tool": result,
                        "history": history,
                        "scope": "actual_tool_reexecuted_after_targeted_model_correction"}
        except Exception as exc:
            attempt_record["passed"] = False
            attempt_record["error"] = type(exc).__name__ + ": " + str(exc)
            history.append(attempt_record)
            return {"passed": False, "tool": tool_name, "history": history,
                    "reason": attempt_record["error"], "last_tool": result}
    return {"passed": False, "tool": tool_name, "history": history,
            "reason": "Tool still failed after targeted repair", "last_tool": result}
