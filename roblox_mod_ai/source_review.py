"""Second-pass small-model review of actual generated Luau against detailed plan.

A review is *not* runtime evidence. Findings must quote real source lines before
blocking or proposing targeted repair; absent/unavailable model is NOT RUN.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

SCHEMA = "rmm/source-review-v1"


def _configured() -> bool:
    choice = os.environ.get("RMM_ENABLE_AI_SOURCE_REVIEW", "auto").lower()
    if choice == "0":
        return False
    return choice == "1" or bool(
        os.environ.get("ROBLOX_LLAMA_SERVER_URL") or
        os.environ.get("RMM_MODEL_BASE_URL"))


def review_generated_sources(
    proposal: Any, root: Path, router: Any, *,
    max_lines_per_chunk: int = 170,
) -> dict[str, Any]:
    """Review all authored module files, split by exact source line ranges."""
    root = Path(root)
    report: dict[str, Any] = {
        "schema": SCHEMA, "scope": "static_ai_reinspection_no_roblox_engine",
        "executed": False, "status": "not_run",
        "reason": "", "reviewed": [], "findings": [],
        "source_sha256": {}, "fully_covered": False,
    }
    if not _configured():
        report["reason"] = "AI reviewer unavailable/disabled; no model review claimed"
        return report
    detail = proposal.game_design.get("detailed_implementation_plan") or {}
    if not detail.get("required_functions"):
        report["status"] = "failed"
        report["reason"] = "No detailed requirement plan to review"
        return report
    contexts = {m["name"]: m for m in detail.get("implementation_modules", [])}
    max_lines_per_chunk = max(40, min(300, max_lines_per_chunk))
    try:
        for module in proposal.modules:
            path = root / module.file_path
            if not path.is_file():
                report["status"] = "failed"
                report["reason"] = "Missing generated file: " + module.file_path
                return report
            source = path.read_text(encoding="utf-8")
            report["source_sha256"][module.file_path] = hashlib.sha256(
                source.encode("utf-8")).hexdigest()
            lines = source.splitlines()
            if not lines:
                report["status"] = "failed"
                report["reason"] = "Empty module source: " + module.file_path
                return report
            plan = contexts.get(module.name, {})
            reqs = [item for item in detail.get("required_functions", [])
                    if item["id"] in plan.get("requirements", [])]
            ai_steps = {rid: item for rid, item in (
                detail.get("ai_planning", {}).get("requirements") or {}).items()
                if rid in plan.get("requirements", [])}
            for start in range(0, len(lines), max_lines_per_chunk):
                end = min(len(lines), start + max_lines_per_chunk)
                numbered = "\n".join(
                    f"{i + 1}: {lines[i]}" for i in range(start, end))
                prompt = (
                    "Independently review real generated Roblox Luau against its "
                    "PRE-APPROVED detailed plan. No Studio is available; do not "
                    "claim runtime testing. Inspect state changes, server authority, "
                    "client response, incorrect Roblox APIs, missing branches, "
                    "bad lifecycle races, and expected outcomes. Be skeptical, "
                    "but never invent a missing behavior that could exist in another "
                    "chunk. Return JSON object {findings:[{line:int,quote:string,"
                    "severity:'blocking'|'advisory',issue:string,repair:string}]}. "
                    "Only blocking for a CONCRETE defect proven by a verbatim "
                    "quote of a line within the supplied source chunk. If uncertain, "
                    "report advisory. Zero findings is allowed. Keep <=3 findings.\n"
                    "Original request: " + proposal.requested_prompt[:480] + "\n"
                    "Module: " + module.name + "\n"
                    "Module contract: " + str(plan)[:1300] + "\n"
                    "Owned requirements: " + str(reqs)[:1500] + "\n"
                    "Pre-coding detailed steps: " + str(ai_steps)[:1500] + "\n"
                    "Source lines:\n" + numbered
                )
                review = router.complete_json(
                    prompt=prompt, role="analyzer", temperature=0,
                    max_tokens=850,
                )
                report["executed"] = True
                if not isinstance(review, dict) or not isinstance(
                    review.get("findings"), list):
                    raise ValueError("AI source review did not return findings array")
                for finding in review["findings"][:3]:
                    if not isinstance(finding, dict):
                        continue
                    line = finding.get("line")
                    quote = finding.get("quote")
                    issue = finding.get("issue")
                    if not isinstance(line, int) or not (start < line <= end):
                        continue
                    if not isinstance(quote, str) or not quote.strip():
                        continue
                    if quote.strip() not in lines[line - 1]:
                        continue  # No hallucinated evidence may block a build.
                    if not isinstance(issue, str) or not issue.strip():
                        continue
                    severity = ("blocking" if finding.get("severity") == "blocking"
                                else "advisory")
                    report["findings"].append({
                        "file": module.file_path, "line": line,
                        "quote": quote.strip()[:180], "severity": severity,
                        "issue": issue.strip()[:350],
                        "repair": str(finding.get("repair", ""))[:350],
                        "evidence": "source_line_quote_matched",
                    })
                report["reviewed"].append({
                    "file": module.file_path, "from_line": start + 1,
                    "to_line": end,
                })
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        report["status"] = "failed"
        report["reason"] = type(exc).__name__ + ": " + str(exc)[:400]
        return report
    report["fully_covered"] = bool(report["reviewed"]) and len(
        report["source_sha256"]) == len(proposal.modules)
    blocking = [x for x in report["findings"] if x["severity"] == "blocking"]
    report["status"] = "issues_found" if blocking else "reviewed_no_blockers"
    report["reason"] = (
        "Blocking source-grounded AI findings need code repair and re-review"
        if blocking else "AI source inspection completed; not Studio execution proof"
    )
    return report
