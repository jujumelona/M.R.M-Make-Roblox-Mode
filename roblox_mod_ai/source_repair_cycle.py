"""Evidence-led review -> root cause -> change plan -> patch -> checks -> re-review.

No Roblox Studio execution. Every edit is scoped to model-authored sources,
is reverted if validation regresses, and the full history is persisted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from .agent_loop import RobloxCodeRepairAgent
from .generation_provenance import host_source_must_regenerate
from .generation_scope import generation_scope

SCHEMA = "rmm/source-repair-cycle-v1"
HOST_OWNED_IDS = {
    "mod_game_objective", "mod_arena_round", "mod_arena_round_controller",
    "mod_dynamic_server_bootstrap", "mod_player_data", "mod_network_bridge",
}


def _hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _blocking(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in report.get("findings", [])
        if isinstance(item, dict) and item.get("severity") == "blocking"
    ]


def _plan_change(module: Any, issues: list[dict[str, Any]], router: Any,
                 proposal: Any, previous_failures: list[dict[str, Any]]) -> dict[str, Any]:
    """A second AI call diagnoses actual quoted defects before touching code."""
    result = router.complete_json(
        prompt=(
            "Produce a scoped Roblox Luau defect repair plan ONLY. Do not write "
            "source code yet. Analyze root causes, affected states and how to "
            "fix the observed defects while keeping the original game behavior. "
            "Return JSON with file:string, root_cause:string, change_strategy:string, "
            "invariants:array of strings, regression_tests:array of strings. "
            "No new files. No removal of requested functionality. Do not disable "
            "checks or mark Roblox engine tests passed.\n"
            + json.dumps({
                "file": module.file_path,
                "module": module.name,
                "requirements": [
                    req for req in (proposal.game_design.get(
                        "detailed_implementation_plan") or {}).get(
                            "required_functions", [])
                    if module.name in req.get("owner_modules", [])
                ][:8],
                "real_source_findings": issues,
                "previous_failed_repair_attempts": previous_failures[-3:],
            }, ensure_ascii=False, default=str)[:8000]
        ),
        role="planner", temperature=0, max_tokens=1100,
    )
    if not isinstance(result, dict) or result.get("file") != module.file_path:
        raise ValueError("Repair plan changed the source filename or returned invalid JSON")
    for field in ("root_cause", "change_strategy"):
        if not isinstance(result.get(field), str) or len(result[field].strip()) < 8:
            raise ValueError("Repair plan has no specific " + field)
    for field in ("invariants", "regression_tests"):
        values = result.get(field)
        if not isinstance(values, list) or not values or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            raise ValueError("Repair plan omits required " + field)
    return {
        "file": module.file_path,
        "root_cause": result["root_cause"][:800],
        "change_strategy": result["change_strategy"][:1000],
        "invariants": result["invariants"][:12],
        "regression_tests": result["regression_tests"][:12],
    }


def _repair_host_action_scoped(
    source: str, path: str, issues: list[dict[str, Any]],
    plan: dict[str, Any], router: Any,
) -> str:
    """Ask the small model for ONE bounded anchored edit, never a whole file.

    It is only called for generated gameplay, never infrastructure. Actual
    analyzers and independent re-review still decide whether to retain it.
    """
    anchor = str(issues[0].get("quote", ""))
    offset = source.find(anchor)
    if offset < 0:
        raise ValueError("Host patch anchor no longer appears in reviewed source")
    start = max(0, offset - 1300)
    end = min(len(source), offset + max(200, len(anchor)) + 1300)
    result = router.complete_json(
        prompt=(
            "Patch exactly ONE local Luau behavior defect. Return two short "
            "JSON strings 'before' and 'after' (literal source fragments); "
            "DO NOT return a whole script, disable validation, or remove "
            "other mechanics. 'before' must match the supplied source window "
            "verbatim and exactly once in the complete original source. "
            "'after' must implement the missing effect, preserving authority "
            "and persistent state. A second pass will run compiler, static "
            "contracts, and independent behavioral review.\n"
            + json.dumps({
                "file": path, "issue": issues[:2],
                "root_cause": plan["root_cause"],
                "change_strategy": plan["change_strategy"],
                "source_window": source[start:end],
            }, ensure_ascii=False)
        ),
        role="coder", temperature=0, max_tokens=1800,
        json_schema={
            "type": "object",
            "properties": {
                "before": {"type": "string", "maxLength": 1200},
                "after": {"type": "string", "maxLength": 2200},
            },
            "required": ["before", "after"],
            "additionalProperties": False,
        },
    )
    if not isinstance(result, dict):
        raise ValueError("Host patch has invalid JSON")
    before, after = result.get("before"), result.get("after")
    if (not isinstance(before, str) or not isinstance(after, str)
            or len(before) < 8 or len(before) > 1200
            or len(after) > 2200 or before == after
            or source.count(before) != 1
            or before not in source[start:end]):
        raise ValueError("Host patch must change one unique small source hunk")
    revised = source.replace(before, after, 1)
    if len(revised) < len(source) * 0.85:
        raise ValueError("Host patch removed too much existing source")
    return revised


def run_source_repair_cycle(
    proposal: Any,
    root: Path,
    router: Any,
    initial_review: dict[str, Any],
    *,
    verify: Callable[[], dict[str, Any]],
    review_again: Callable[[], dict[str, Any]],
    max_rounds: int = 3,
    agent_factory: Callable[..., Any] = RobloxCodeRepairAgent,
    allow_host_gameplay_repairs: bool = False,
) -> dict[str, Any]:
    """Retry until clean review or a bounded, explained failure.

    'verify' must execute actual available static/OSS checks and return
    {passed:bool,...}; 'review_again' must inspect the changed disk sources.
    Model-only reassurance is not a passing validation.
    """
    root = Path(root)
    max_rounds = max(1, min(5, int(max_rounds)))
    report = {
        "schema": SCHEMA, "passed": False, "status": "not_run",
        "attempts": [], "initial_review": initial_review,
        "final_review": initial_review, "changed_files": [],
        "reason": "", "scope": "static_and_offline_only_no_roblox_studio",
    }
    if initial_review.get("status") != "issues_found":
        report["status"] = ("not_applicable" if initial_review.get(
            "status") == "not_run" else "failed")
        report["reason"] = "No confirmed blocking findings eligible for repair"
        return report
    modules = {m.file_path: m for m in proposal.modules}
    # Ownership comes from the real codegen routing, not the dyn_ prefix.
    # Host-generated gameplay also uses dyn_* identifiers.
    try:
        strategy_by_id = {
            row["module_id"]: row["strategy"]
            for row in generation_scope(proposal)["modules"]
        }
    except (AttributeError, KeyError, TypeError):
        # Lightweight source-repair unit fixtures omit planning metadata.
        # Production plans provide the full routing graph.
        strategy_by_id = {}
    attempted_patches: set[tuple[str, str]] = set()
    changed: set[str] = set()
    current = initial_review
    for round_number in range(1, max_rounds + 1):
        findings = _blocking(current)
        if not findings:
            report.update(status="passed", passed=True, final_review=current,
                          reason="No remaining source-grounded blocking findings")
            break
        by_file: dict[str, list[dict[str, Any]]] = {}
        for item in findings:
            by_file.setdefault(str(item.get("file")), []).append(item)
        step: dict[str, Any] = {
            "round": round_number, "findings": findings,
            "plans": [], "edits": [], "validation": None,
            "review": None, "status": "started",
        }
        report["attempts"].append(step)
        selected = []
        for file_path in sorted(by_file):
            module = modules.get(file_path)
            if module is None:
                step["status"] = "blocked"
                report["reason"] = "Review referenced unknown module: " + file_path
                break
            # First-party infrastructure remains immutable. For an actual
            # generated gameplay action, a fresh, source-quoted whole-requirement
            # review can authorize a *per-build* correction. Verification and
            # re-review still gate publication; no Python template is modified.
            is_host = host_source_must_regenerate(
                module, strategy_by_id.get(module.module_id, ""))
            behavior_gap = bool(by_file[file_path]) and all(
                finding.get("evidence") == "requirement_effect_review_source_quote"
                for finding in by_file[file_path]
            )
            allowed_host_action = (
                allow_host_gameplay_repairs and behavior_gap
                and module.module_id.startswith("dyn_")
                and module.module_id not in HOST_OWNED_IDS
                and module.file_path.startswith(("src/server/", "src/client/"))
            )
            if (not module.module_id.startswith("dyn_")
                    or module.module_id in HOST_OWNED_IDS
                    or (is_host and not allowed_host_action)):
                step["status"] = "blocked"
                report["reason"] = (
                    "First-party host template needs generator-level repair: " + file_path)
                break
            selected.append(module)
        if step["status"] == "blocked":
            report["status"] = "blocked"
            break
        originals: dict[str, str] = {}
        candidates: dict[str, str] = {}
        try:
            for module in selected:
                path = root / module.file_path
                if not path.is_file():
                    raise ValueError("Missing source file: " + module.file_path)
                original = path.read_text(encoding="utf-8")
                originals[module.file_path] = original
                expected_hash = current.get("source_sha256", {}).get(module.file_path)
                if expected_hash != _hash(original):
                    raise ValueError("Source changed since AI review: " + module.file_path)
            agent = agent_factory(router=router)
            for module in selected:
                issues = by_file[module.file_path]
                previous_failures = [
                    {"round": prev["round"], "plans": prev["plans"],
                     "reason": prev.get("reason", ""), "validation": prev.get("validation")}
                    for prev in report["attempts"][:-1] if prev.get("status") == "reverted"
                ]
                plan = _plan_change(module, issues, router, proposal, previous_failures)
                step["plans"].append(plan)
                diagnostic = (
                    "Code review found concrete defects in existing source. "
                    "Repair only the specified module, preserve requested behavior. "
                    "Do not disable checks. Correct the root cause, not only the "
                    "line quoted as evidence. Repair plan and observations:\n"
                    + json.dumps({"plan": plan, "findings": issues},
                                 ensure_ascii=False)[:6000]
                )
                original = originals[module.file_path]
                is_host = host_source_must_regenerate(
                    module, strategy_by_id.get(module.module_id, ""))
                candidate = (
                    _repair_host_action_scoped(
                        original, module.file_path, issues, plan, router)
                    if is_host and allow_host_gameplay_repairs
                    else agent.repair(
                        module, proposal, existing_code=original,
                        diagnostics=diagnostic, attempts=2)
                )
                if not isinstance(candidate, str) or candidate == original or not candidate.strip():
                    raise ValueError("Repair produced no substantive source change")
                fingerprint = (module.file_path, _hash(candidate))
                if fingerprint in attempted_patches:
                    raise ValueError("Same unsuccessful candidate repeated; stop retrying")
                attempted_patches.add(fingerprint)
                candidates[module.file_path] = candidate
                step["edits"].append({
                    "file": module.file_path, "before_sha256": _hash(original),
                    "after_sha256": _hash(candidate),
                })
            # Edits to host-generated action code are current-build overrides
            # only. The next build regenerates the host original and repeats
            # this independent gate instead of trusting a stale saved patch.
            # Apply all candidates transactionally. Failed verification/review
            # restores the exact original bytes and the in-memory module code.
            for module in selected:
                value = candidates[module.file_path]
                (root / module.file_path).write_text(value, encoding="utf-8")
                module.code = value
            validation = verify()
            step["validation"] = validation
            if not isinstance(validation, dict) or validation.get("passed") is not True:
                raise ValueError("Source validation failed after patch; revert required")
            newer = review_again()
            step["review"] = newer
            if newer.get("status") not in ("issues_found", "reviewed_no_blockers") or not newer.get("fully_covered"):
                raise ValueError("Fresh AI source review incomplete; revert required")
            if newer.get("status") == "reviewed_no_blockers":
                step["status"] = "passed"
                current = newer
                changed.update(candidates)
                report.update(passed=True, status="passed", final_review=newer,
                              reason="Defects corrected; deterministic checks and fresh AI review passed")
                break
            # Evidence remained or changed; keep patch ONLY if exact blocking
            # count decreases. Otherwise rollback and request a different plan.
            if len(_blocking(newer)) >= len(findings):
                raise ValueError("Blocking source defects did not decrease; revert required")
            current = newer
            changed.update(candidates)
            step["status"] = "improved_needs_next_round"
            report["final_review"] = newer
        except Exception as exc:
            for module in selected:
                if module.file_path in originals:
                    (root / module.file_path).write_text(
                        originals[module.file_path], encoding="utf-8")
                    module.code = originals[module.file_path]
            step["status"] = "reverted"
            step["reason"] = type(exc).__name__ + ": " + str(exc)[:500]
            report["reason"] = step["reason"]
            # A failed patch does not end the process. Ask for a new root-cause
            # plan using the previous failure evidence on the next attempt.
            # A repeated identical candidate is a terminal no-progress signal.
            if "Same unsuccessful candidate repeated" in step["reason"]:
                report["status"] = "blocked"
                break
            report["status"] = "retrying"
    else:
        report["status"] = "exhausted"
        last_failure = report["reason"]
        report["reason"] = (
            "Review still contains blocking defects after maximum repair rounds"
            + ("; last failed attempt: " + last_failure if last_failure else "")
        )
    report["changed_files"] = sorted(changed)
    return report
