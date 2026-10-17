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
                            tool_name: str, failed_result: dict[str,Any],
                            retry_tool: Callable[[], dict[str,Any]],
                            format_sources: Callable[[], dict[str,Any]] | None,
                            router) -> dict[str,Any]:
    if not failed_result.get("executed"):
        return {"passed":False,"reason":"Missing executable tool cannot be repaired"}
    diagnostics=(str(failed_result.get("stderr") or "")+"\n"+
                 str(failed_result.get("stdout") or "")+
                 "\n"+str(failed_result.get("error") or ""))[:12000]
    selected=affected_dynamic_modules(proposal, diagnostics)
    if not selected:
        return {"passed":False,"reason":"No exact novel-module diagnostic; no unrelated template edits"}
    agent=RobloxCodeRepairAgent(router=router)
    for module in selected:
        code=agent.repair(module,proposal,
            existing_code=module.code,diagnostics=diagnostics,attempts=2)
        module.code=code
        (output_dir/module.file_path).write_text(code,encoding="utf-8")
    if format_sources is not None:
        formatted=format_sources()
        if not formatted.get("executed") or not formatted.get("success"):
            return {"passed":False,"reason":"StyLua reformat failed","tool":formatted}
        for module in selected:
            module.code=(output_dir/module.file_path).read_text(encoding="utf-8")
    retried=retry_tool()
    return {
        "passed":bool(retried.get("executed") and retried.get("success")),
        "tool":tool_name,
        "repaired":[m.file_path for m in selected],
        "retried_tool":retried,
        "scope":"one_explicit_compiler_or_linter_retry_not_gameplay_proof",
    }
