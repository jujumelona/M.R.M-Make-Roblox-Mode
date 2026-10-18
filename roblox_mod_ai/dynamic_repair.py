"""Bounded repair of actually executed Luau compiler/linter diagnostics.

Never retries a failed tool by changing an unrelated first-party template or by
silently ignoring a failed check.  The actual error must identify a dynamic
module source file.  The same external tool must pass again after the patch.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable
import json

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


def model_triage_modules(proposal: RobloxProposal, diagnostic: str, router,
                         *, max_files: int = 3) -> list:
    """Ask model WHICH existing generated file owns an unlocated diagnostic.

    Never let the model invent a path, choose a third-party file, or bypass the
    failing check. Only use when tool output cannot be mapped by exact pathname.
    """
    available = [m for m in proposal.modules if m.module_id.startswith("dyn_")]
    if not available:
        return []
    try:
        result = router.complete_json(
            "Given the ACTUAL failed Roblox source/tool diagnostic, identify "
            "the existing generated Luau files that need fixing. Return JSON "
            '{"files":["src/..."]}. No new filenames or invented modules. '
            "Consider server/client roles and the current source. "
            "Choose only files relevant to the failed action; do not rewrite "
            "unrelated code.\n" +
            json.dumps({
                "diagnostic": diagnostic[:7500],
                "files": [{"path": m.file_path, "role": str(m.kind),
                           "purpose": m.description[:240],
                           "code_excerpt": m.code[:1500]} for m in available],
            }, ensure_ascii=False),
            role="planner", temperature=0.0,
        )
        paths = result.get("files") if isinstance(result, dict) else None
        if not isinstance(paths, list) or not paths or len(paths) > max_files:
            return []
        by_path = {m.file_path: m for m in available}
        if len(set(paths)) != len(paths) or any(
                not isinstance(path, str) or path not in by_path
                for path in paths):
            return []
        return [by_path[path] for path in paths]
    except Exception:
        return []


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
            selected = model_triage_modules(proposal, diagnostics, router)
            history.append({"attempt": attempt, "action": "model diagnostic triage",
                            "diagnostics": diagnostics,
                            "candidate_files": [m.file_path for m in selected]})
        if not selected:
            return {"passed": False, "tool": tool_name, "history": history,
                    "reason": "Model could not attribute tool error to a real generated source",
                    "last_tool": result}
        if attempt > 1 and diagnostics == previous_diagnostic:
            history.append({"attempt": attempt,
                            "diagnostics": diagnostics,
                            "decision": "repeat observed, requesting different targeted edit"})
            # The previous edit did not alter the verifier's observation.
            # Give the agent the prior failure again rather than prematurely
            # declaring a finished repair attempt.
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
                # When the CLIENT has no remote call, only the SERVER source
                # mentions the name. Editing server-only code cannot repair a
                # missing client sender. Let the model locate the absent side.
                selected = model_triage_modules(
                    proposal, check_id + ": " + detail, router)
                for module in selected:
                    errors_by_path.setdefault(module.file_path, []).append(
                        check_id + ": " + detail)
                if not selected:
                    for module in path_to_module.values():
                        if remote in module.code or remote in module.description:
                            errors_by_path.setdefault(module.file_path, []).append(
                                check_id + ": " + detail)
        if not errors_by_path:
            # General acceptance checks may not mention a file (e.g. wiring
            # with a missing client sender). Ask the model to select ONLY known
            # generated modules; retain exact checker failures for its edit.
            detail = json.dumps({
                "acceptance_checks": failures,
                "analyzer_diagnostics": [getattr(d, "message", "") for d in diagnostics],
            }, ensure_ascii=False)
            selected = model_triage_modules(proposal, detail, router)
            for mod in selected:
                errors_by_path.setdefault(mod.file_path, []).append(detail)
            if trajectory:
                trajectory.record("static", "diagnostic triage", {
                    "failed_checks": [x.get("id") for x in failures],
                    "model_selected_files": [m.file_path for m in selected],
                }, passed=bool(selected), attempt=round_num)
            if not errors_by_path:
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
