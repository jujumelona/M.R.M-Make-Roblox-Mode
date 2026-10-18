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



def repair_static_failures(proposal: RobloxProposal, output_dir: Path,
                           analysis: Any, acceptance: dict[str, Any],
                           router: Any, recheck: Callable[[], tuple[Any, dict]],
                           format_sources: Callable[[], dict] | None = None,
                           trajectory: Any = None,
                           max_rounds: int = 3) -> tuple[Any, dict, bool]:
    """Use *actual* static/acceptance observations to repair implicated code.

    Patches only generated novel modules whose exact file, module name, or
    declared remote is implicated in diagnostics. Reruns BOTH validators and
    rolls back candidates that fail to reduce errors or regress passed checks.
    """
    current_analysis, current_acceptance = analysis, acceptance
    agent = RobloxCodeRepairAgent(router=router)
    path_to_module = {
        m.file_path: m for m in proposal.modules if m.module_id.startswith("dyn_")
    }
    name_to_module = {m.name: m for m in path_to_module.values()}
    for round_num in range(1, max_rounds + 1):
        failures = [x for x in current_acceptance.get("checks", []) if not x.get("passed")]
        diagnostics = [d for d in getattr(current_analysis, "diagnostics", [])
                       if getattr(d, "severity", "") == "ERROR"]
        if not diagnostics and not failures:
            return current_analysis, current_acceptance, True
        errors_by_path: dict[str, list[str]] = {}
        for d in diagnostics:
            path = str(getattr(d, "file_path", "")).replace("\\", "/")
            for file_path in path_to_module:
                if path == file_path or path.endswith("/" + file_path):
                    errors_by_path.setdefault(file_path, []).append(
                        f"{path}:{getattr(d, 'line_number', 0)}: {getattr(d, 'message', '')}")
        for check in failures:
            check_id = str(check.get("id", ""))
            detail = str(check.get("detail", ""))
            if check_id.startswith("dynamic.code."):
                target = name_to_module.get(check_id.removeprefix("dynamic.code."))
                if target:
                    errors_by_path.setdefault(target.file_path, []).append(
                        check_id + ": " + detail)
            if check_id.startswith("wiring."):
                remote = check_id.removeprefix("wiring.")
                for module in path_to_module.values():
                    if (remote in module.code or remote in module.description):
                        errors_by_path.setdefault(module.file_path, []).append(
                            check_id + ": " + detail)
        if not errors_by_path:
            if trajectory:
                trajectory.record("static", "diagnostic triage", {
                    "unrepairable_checks": [x.get("id") for x in failures],
                    "errors": [getattr(d, "message", "") for d in diagnostics],
                    "reason": "No exact generated source implicated",
                }, passed=False, attempt=round_num)
            break
        before = set(x.get("id") for x in failures)
        before_errors = len(diagnostics)
        originals = {}
        modified = []
        for file_path, messages in errors_by_path.items():
            module = path_to_module[file_path]
            original = module.code
            originals[file_path] = original
            try:
                diagnostic_text = "\n".join(messages)
                replacement = agent.repair(
                    module, proposal, existing_code=original,
                    diagnostics=diagnostic_text, attempts=3,
                )
                if replacement != original:
                    module.code = replacement
                    (output_dir / file_path).write_text(replacement, encoding="utf-8")
                    modified.append(file_path)
                if trajectory:
                    trajectory.record("static", "repair " + file_path, {
                        "diagnostics": messages, "source_changed": replacement != original,
                    }, passed=True, attempt=round_num)
            except Exception as exc:
                if trajectory:
                    trajectory.record("static", "repair " + file_path,
                                      type(exc).__name__ + ": " + str(exc),
                                      passed=False, attempt=round_num)
        if not modified:
            break
        if format_sources is not None:
            fmt = format_sources()
            if not fmt.get("success") or not fmt.get("executed"):
                for file_path, original in originals.items():
                    if file_path in modified:
                        path_to_module[file_path].code = original
                        (output_dir / file_path).write_text(original, encoding="utf-8")
                if trajectory:
                    trajectory.record("static", "format repaired source", fmt,
                                      passed=False, attempt=round_num)
                break
            for file_path in modified:
                path_to_module[file_path].code = (
                    output_dir / file_path).read_text(encoding="utf-8")
        revised_analysis, revised_acceptance = recheck()
        after = {x.get("id") for x in revised_acceptance.get("checks", [])
                 if not x.get("passed")}
        after_errors = sum(1 for d in getattr(revised_analysis, "diagnostics", [])
                           if getattr(d, "severity", "") == "ERROR")
        improved = (not (after - before)
                    and after_errors <= before_errors
                    and (len(after) < len(before) or after_errors < before_errors))
        if trajectory:
            trajectory.record("static", "revalidate source and acceptance", {
                "failed_before": sorted(before), "failed_after": sorted(after),
                "errors_before": before_errors, "errors_after": after_errors,
                "changed_files": modified,
            }, passed=improved, attempt=round_num)
        if not improved:
            for file_path, original in originals.items():
                if file_path in modified:
                    path_to_module[file_path].code = original
                    (output_dir / file_path).write_text(original, encoding="utf-8")
            # Recheck after rollback, since formatting may also have modified
            # files outside the agent's explicit patch.
            current_analysis, current_acceptance = recheck()
            break
        current_analysis, current_acceptance = revised_analysis, revised_acceptance
    return (current_analysis, current_acceptance,
            bool(getattr(current_analysis, "passed", False)
                 and current_acceptance.get("passed", False)))
