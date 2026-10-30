"""Evidence-led review -> root cause -> change plan -> patch -> checks -> re-review.

No Roblox Studio execution. Every edit is scoped to model-authored sources,
is reverted if validation regresses, and the full history is persisted.
"""
from __future__ import annotations

import difflib
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
    """Plan a real edit; never require redundant small-model root-cause prose.

    Requirement-effect findings already contain a source-quoted observation,
    a requested behavioral correction and source ownership. Asking another
    small model to restate that information as a long JSON plan caused three
    identical zero-edit failures. Preserve the findings instead.
    """
    grounded = bool(issues) and all(
        row.get("evidence") == "requirement_effect_review_source_quote"
        and row.get("quote") and row.get("issue") and row.get("repair")
        for row in issues
    )
    if grounded:
        return {
            "file": module.file_path,
            "root_cause": "; ".join(
                str(row["issue"]).strip() for row in issues
            )[:1200],
            "change_strategy": "; ".join(
                str(row["repair"]).strip() for row in issues
            )[:1600],
            "invariants": [
                "Preserve all unrelated source-owned game behavior",
                "Keep server authority and saved player state consistent",
                "Never remove security checks or unrelated actions",
            ],
            "regression_tests": [
                "Re-run actual offline source analyzers and ABI checks",
                "Independently re-review the new source against the same requirement",
            ],
            "plan_origin": "grounded_requirement_effect_findings",
        }
    # For older model-authored diagnostics without a complete source-grounded
    # repair recommendation, retain the existing planner and strict checks.
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


def _apply_scoped_hunks(
    source: str, edits: list[dict[str, str]], windows: list[str],
) -> str:
    """Apply several independent anchored edits against ONE reviewed file.

    Every anchor belongs to the original file and one of the evidence windows.
    Detect overlap, duplicate anchors and whitespace-only substitutions before
    writing. The outer repair cycle performs all real analyzer and reviewer
    checks transactionally and rolls back on failure.
    """
    if not 1 <= len(edits) <= 4:
        raise ValueError("Host patch requires one to four source hunks")
    resolved: list[tuple[int, int, str]] = []
    for item in edits:
        if not isinstance(item, dict):
            raise ValueError("Host patch hunk is not a JSON object")
        before, after = item.get("before"), item.get("after")
        if (not isinstance(before, str) or not isinstance(after, str)
                or len(before) < 8 or len(before) > 1500
                or not after.strip() or len(after) > 3500
                or before.strip() == after.strip()
                or source.count(before) != 1
                or not any(before in window for window in windows)):
            raise ValueError("Host patch must change unique, source-grounded hunks")
        offset = source.find(before)
        resolved.append((offset, offset + len(before), after))
    resolved.sort()
    for index in range(1, len(resolved)):
        if resolved[index][0] < resolved[index - 1][1]:
            raise ValueError("Overlapping host patch hunks")
    result = source
    for beginning, ending, after in reversed(resolved):
        result = result[:beginning] + after + result[ending:]
    if len(result) < len(source) * 0.85:
        raise ValueError("Host patch removed too much existing source")
    return result


def _repair_host_action_scoped(
    source: str, path: str, issues: list[dict[str, Any]],
    plan: dict[str, Any], router: Any,
) -> str:
    """Repair a gameplay *behavior*, not an arbitrary single nearby line.

    Real effects may need several edits (input guard, authoritative mutation,
    persistence/feedback). Limit edits to the reviewed file and independent,
    source-grounded windows. Never let the model replace security scaffolding
    or unrelated modules. Actual validators and re-review decide acceptance.
    """
    windows: list[str] = []
    for issue in issues[:4]:
        quote = str(issue.get("quote", ""))
        offset = source.find(quote)
        if offset < 0:
            raise ValueError("Host patch anchor no longer appears in reviewed source")
        beginning = max(0, offset - 1750)
        end = min(len(source), offset + max(200, len(quote)) + 1750)
        window = source[beginning:end]
        if window not in windows:
            windows.append(window)
    # Full short modules allow a missing producer and its consumer to be
    # patched together, even if they are far apart in the same file.
    if len(source) <= 9000:
        windows = [source]
    result = router.complete_json(
        prompt=(
            "Patch exactly ONE generated Roblox Luau module to repair its "
            "Roblox Luau gameplay module. Return an ordered set of 1 to 4 "
            "independent, unique 'before'/'after' source hunks as 'edits'. "
            "A cross-function correction may require several hunks (e.g. "
            "validate input, mutate persistent server state, and send gameplay "
            "feedback). Do not return a whole script, rename a feature, "
            "disable guards, or rewrite unrelated actions. Every 'before' must "
            "occur EXACTLY ONCE in the original on-disk module and inside a "
            "provided source window. Every 'after' must implement meaningful "
            "runtime behavior with server authority. Validators and a NEW "
            "independent full source-effect review must pass after applying "
            "ALL changes transactionally. If a single hunk suffices, legacy "
            "top-level before/after fields are also accepted.\n"
            + json.dumps({
                "file": path, "issues": issues[:4],
                "root_cause": plan["root_cause"],
                "change_strategy": plan["change_strategy"],
                "source_windows": windows,
            }, ensure_ascii=False)[:23000]
        ),
        role="coder", temperature=0, max_tokens=3500,
        json_schema={
            "type": "object",
            "properties": {
                "edits": {"type": "array", "minItems": 1, "maxItems": 4,
                          "items": {"type": "object", "properties": {
                              "before": {"type": "string", "maxLength": 1500},
                              "after": {"type": "string", "maxLength": 3500},
                          }, "required": ["before", "after"],
                              "additionalProperties": False}},
                "before": {"type": "string", "maxLength": 1500},
                "after": {"type": "string", "maxLength": 3500},
            },
            "additionalProperties": False,
        },
    )
    if not isinstance(result, dict):
        raise ValueError("Host patch has invalid JSON")
    edits = result.get("edits")
    if not isinstance(edits, list):
        edits = [{"before": result.get("before"),
                  "after": result.get("after")}]
    return _apply_scoped_hunks(source, edits, windows)


def _confirm_scoped_progress(
    router: Any, path: str, before: str, after: str,
    previous: list[dict[str, Any]], now: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check that the ORIGINAL defect was fixed, not merely renamed.

    The holistic reviewer can discover new defects in a corrected module;
    its total finding count is not a monotonic measure of progress. Do not
    accept a new defect as a fix by itself: require an independent focused
    review of the precise old issue against the changed source, plus an
    actual source quote selected by the host.
    """
    if before == after or not previous:
        return {"resolved": False, "reason": "No changed source or prior defect"}
    if not all(f.get("evidence") == "requirement_effect_review_source_quote"
               for f in previous):
        return {"resolved": False, "reason": "Insufficient original defect provenance"}
    # The newer reviewer must have inspected this exact changed file.
    # A new holistic report lacking this file is acceptable only when it
    # explicitly claims no blockers anywhere, handled by the caller.
    if not isinstance(now, list):
        return {"resolved": False, "reason": "Missing renewed review"}
    changes = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(), n=3, lineterm=""))
    if not changes or len(changes) > 1600:
        return {"resolved": False, "reason": "No bounded inspectable change"}
    prompt = (
        "Independent narrow source-diff verification. Decide ONLY whether "
        "the original, quoted behavioral defect was concretely addressed "
        "by this patch. Ignore new or unrelated defects (those stay in the "
        "full blocking review). Do not mistake changed variable names, "
        "comments, extra attributes, or copied text for working gameplay. "
        "When the edited code is insufficient to prove the original "
        "effect, return false. Respond JSON with resolved:boolean, "
        "evidence_quote:string (exact source substring from the NEW changed "
        "Luau source), reason:string. Never claim engine execution.\n"
        + json.dumps({
            "file": path,
            "previous_defects": [{
                "issue": row.get("issue"), "repair": row.get("repair"),
                "source_quote": row.get("quote"),
            } for row in previous],
            "fresh_review_remaining": [{
                "issue": row.get("issue"), "quote": row.get("quote"),
            } for row in now],
            "actual_source_diff": "\n".join(changes)[:8500],
        }, ensure_ascii=False)
    )
    try:
        reply = router.complete_json(
            prompt=prompt, role="analyzer", temperature=0, max_tokens=450,
            json_schema={
                "type": "object",
                "properties": {
                    "resolved": {"type": "boolean"},
                    "evidence_quote": {"type": "string", "maxLength": 180},
                    "reason": {"type": "string", "maxLength": 300},
                },
                "required": ["resolved", "evidence_quote", "reason"],
                "additionalProperties": False,
            },
        )
    except Exception as exc:
        return {"resolved": False,
                "reason": "Focused review failed: " + type(exc).__name__}
    if not isinstance(reply, dict) or reply.get("resolved") is not True:
        return {"resolved": False, "reason": str(
            reply.get("reason", "") if isinstance(reply, dict)
            else "Invalid model response")[:300]}
    evidence = reply.get("evidence_quote")
    if (not isinstance(evidence, str) or len(evidence.strip()) < 8
            or evidence not in after or evidence.lstrip().startswith("--")):
        return {"resolved": False, "reason": "Missing actual post-patch source evidence"}
    return {"resolved": True, "evidence_quote": evidence[:180],
            "reason": str(reply.get("reason", ""))[:300]}


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
    # Independently repair one source owner at a time. A source requirement
    # can contain many unrelated actions (e.g. ship, broker, combat). A single
    # ten-file transaction is brittle and three total rounds cannot repair ten
    # distinct files. Keep the configured minimum, with a hard bounded ceiling.
    affected_files = {
        item.get("file") for item in _blocking(initial_review)
        if isinstance(item.get("file"), str)
    }
    max_rounds = max(1, min(30, max(
        int(max_rounds), 2 * len(affected_files)
    )))
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
    failed_file_attempts: dict[str, int] = {}
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
        # Prefer an untried owner. If a patch was reverted, try that owner
        # once more with the new diagnostic, then move on rather than
        # repeatedly spending the entire retry budget on one action.
        candidates_in_order = sorted(
            by_file, key=lambda p: (failed_file_attempts.get(p, 0), p)
        )
        candidates_in_order = [
            path for path in candidates_in_order
            if failed_file_attempts.get(path, 0) < 2
        ]
        if not candidates_in_order:
            # Exhaustion is a status, not a third phantom repair attempt.
            report["attempts"].pop()
            report["status"] = "blocked"
            report["reason"] = (
                "All source owners exhausted bounded local repair attempts; "
                "unresolved behavior remains in reviewed source")
            break
        for file_path in candidates_in_order[:1]:
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
            # The number of defects in the WHOLE project does not
            # necessarily fall when a per-file bug is fixed. A re-review can
            # identify a DIFFERENT defect in that same module. Require an
            # independently evidenced correction of the ORIGINAL bug; keep
            # the newly discovered bug blocking, and continue from there.
            remaining = _blocking(newer)
            if len(remaining) >= len(findings):
                individual_checks = {}
                for module in selected:
                    path = module.file_path
                    individual_checks[path] = _confirm_scoped_progress(
                        router, path, originals[path], candidates[path],
                        by_file[path],
                        [finding for finding in remaining
                         if finding.get("file") == path],
                    )
                step["scoped_progress"] = individual_checks
                if not all(row["resolved"] for row in individual_checks.values()):
                    raise ValueError(
                        "Original defect unproven after patch; revert required: " +
                        json.dumps(individual_checks, ensure_ascii=False)[:350]
                    )
            current = newer
            changed.update(candidates)
            step["status"] = "improved_needs_next_round"
            report["final_review"] = newer
        except Exception as exc:
            for module in selected:
                failed_file_attempts[module.file_path] = (
                    failed_file_attempts.get(module.file_path, 0) + 1
                )
            for module in selected:
                if module.file_path in originals:
                    (root / module.file_path).write_text(
                        originals[module.file_path], encoding="utf-8")
                    module.code = originals[module.file_path]
            step["status"] = "reverted"
            step["reason"] = type(exc).__name__ + ": " + str(exc)[:500]
            report["reason"] = step["reason"]
            # Advance to another owner when this one is exhausted, preserving
            # explicit error evidence. Never silently mark unresolved findings
            # as completed; the final report remains failed if blockers remain.
            if "Same unsuccessful candidate repeated" in step["reason"]:
                for module in selected:
                    failed_file_attempts[module.file_path] = 2
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
