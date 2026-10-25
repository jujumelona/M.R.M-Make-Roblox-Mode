"""Fail-closed, bounded second-pass review of generated Luau.

Each requested source line is reviewed using a small model response contract.
An output-length failure causes a smaller source scope, never a passed review
or whole-file model rewrite. The report records exact successful line ranges.
No review status is evidence of Roblox Studio runtime behavior.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "rmm/source-review-v1"
REVIEW_POLICY = "host-provenance-adjudication-v2"


def _policy_fingerprint() -> dict[str, Any]:
    """Record the actual installed validator bytes, not an asserted git HEAD.

    A Colab notebook may be running an older imported Python package even
    after repository sync. Hashing imported files lets a failure ZIP prove
    which source-review implementation really executed.
    """
    files = ("source_review.py", "source_finding_adjudication.py",
             "source_repair_cycle.py")
    package_dir = Path(__file__).resolve().parent
    hashes: dict[str, str] = {}
    for filename in files:
        path = package_dir / filename
        try:
            hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            hashes[filename] = "unavailable"
    return {"policy": REVIEW_POLICY, "source_sha256": hashes}

MAX_CHUNK_CHARS = 2800
MAX_MODEL_CALLS = 512
FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array", "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "quote": {"type": "string", "maxLength": 160},
                    "severity": {"type": "string", "enum": ["blocking", "advisory"]},
                    "issue": {"type": "string", "maxLength": 240},
                    "repair": {"type": "string", "maxLength": 240},
                },
                "required": ["line", "quote", "severity", "issue", "repair"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["findings"], "additionalProperties": False,
}


def _configured() -> bool:
    choice = os.environ.get("RMM_ENABLE_AI_SOURCE_REVIEW", "auto").lower()
    if choice == "0" or (choice == "auto" and
                         os.environ.get("RMM_ENABLE_MODEL_GENERATION") == "0"):
        return False
    return choice == "1" or bool(
        os.environ.get("ROBLOX_LLAMA_SERVER_URL") or
        os.environ.get("RMM_MODEL_BASE_URL"))


def _is_output_failure(exc: BaseException) -> bool:
    """Only reduce scope for output/JSON failures, not server or code errors."""
    if not isinstance(exc, ValueError):
        return False
    reason = str(exc).lower()
    return (isinstance(exc, json.JSONDecodeError)
            or "finish_reason=length" in reason
            or "completion truncated" in reason
            or "unterminated" in reason)


def _initial_ranges(lines: list[str], max_lines: int):
    """Partition by both physical lines and prompt character budget."""
    cursor = 0
    while cursor < len(lines):
        end = cursor
        characters = 0
        while end < len(lines) and end - cursor < max_lines:
            size = len(lines[end]) + len(str(end + 1)) + 3
            if end > cursor and characters + size > MAX_CHUNK_CHARS:
                break
            characters += size
            end += 1
        yield cursor, end
        cursor = end


def _split_at_text_midpoint(lines: list[str], start: int, end: int) -> int:
    """Prefer similarly sized sub-prompts even with uneven Luau line length."""
    total = sum(len(lines[i]) + 1 for i in range(start, end))
    target = total / 2
    acc = 0
    for i in range(start, end - 1):
        acc += len(lines[i]) + 1
        if acc >= target:
            return i + 1
    return start + (end - start) // 2


def review_generated_sources(
    proposal: Any, root: Path, router: Any, *,
    max_lines_per_chunk: int = 170,
) -> dict[str, Any]:
    root = Path(root)
    report: dict[str, Any] = {
        "schema": SCHEMA, "scope": "static_ai_reinspection_no_roblox_engine",
        "executed": False, "status": "not_run", "reason": "",
        "reviewed": [], "findings": [], "source_sha256": {},
        "fully_covered": False, "model_calls": 0, "scoped_retries": [],
        "review_code_provenance": _policy_fingerprint(),
    }
    if not _configured():
        report["reason"] = "AI reviewer unavailable/disabled; no model review claimed"
        return report

    detail = proposal.game_design.get("detailed_implementation_plan") or {}
    if not detail.get("required_functions"):
        report.update(status="failed", reason="No detailed requirement plan to review")
        return report
    contexts = {m["name"]: m for m in detail.get("implementation_modules", [])}
    max_lines_per_chunk = max(1, min(300, max_lines_per_chunk))
    actual_lines: dict[str, int] = {}

    try:
        for module in proposal.modules:
            path = root / module.file_path
            if not path.is_file():
                raise ValueError("Missing generated file: " + module.file_path)
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            if not lines:
                raise ValueError("Empty module source: " + module.file_path)
            actual_lines[module.file_path] = len(lines)
            report["source_sha256"][module.file_path] = hashlib.sha256(
                source.encode("utf-8")).hexdigest()

            plan = contexts.get(module.name, {})
            req_ids = set(plan.get("requirements", []))
            reqs = [
                (item.get("id"), item.get("expected_outcome")
                 or item.get("original_request"))
                for item in detail.get("required_functions", [])
                if item.get("id") in req_ids
            ]
            # Do not resend a 5 KB planning appendix for every 40 lines.
            context = json.dumps({
                "module": module.name,
                "responsibility": plan.get("responsibility", ""),
                "requirements": reqs[:4],
            }, ensure_ascii=False, default=str)[:1000]

            def examine(start: int, end: int, *, single_retry: bool = False) -> None:
                if report["model_calls"] >= MAX_MODEL_CALLS:
                    raise RuntimeError("AI_REVIEW_CALL_BUDGET_EXHAUSTED")
                numbered = "\n".join(
                    f"{i + 1}: {lines[i]}" for i in range(start, end))
                prompt = (
                    "Review this exact Roblox Luau snippet against its owned game "
                    "requirements. Check server authority, invalid inputs, state "
                    "effects, lifecycle, client/server interface and API usage. "
                    "Do not infer bugs from code outside this snippet. Report at "
                    "most 2 source-quoted concrete issues, or findings:[]. "
                    "Blocking requires a verbatim quote FROM THE SPECIFIED LINE; "
                    "uncertain defects are advisory. Return only JSON "
                    "{findings:[{line,quote,severity,issue,repair}]}; short values. "
                    "No engine/runtime verification claims.\n"
                    "Context: " + context + "\n"
                    "Luau lines:\n" + numbered
                )
                report["model_calls"] += 1
                report["executed"] = True
                try:
                    result = router.complete_json(
                        prompt=prompt, role="analyzer", temperature=0,
                        max_tokens=2200 if single_retry else 1300,
                        json_schema=FINDINGS_SCHEMA,
                    )
                except ValueError as exc:
                    if not _is_output_failure(exc):
                        raise
                    if end - start > 1:
                        middle = _split_at_text_midpoint(lines, start, end)
                        report["scoped_retries"].append({
                            "file": module.file_path, "from_line": start + 1,
                            "to_line": end, "reason": str(exc)[:180],
                            "split_at": middle,
                        })
                        examine(start, middle)
                        examine(middle, end)
                        return
                    if not single_retry:
                        report["scoped_retries"].append({
                            "file": module.file_path, "from_line": start + 1,
                            "to_line": end, "reason": str(exc)[:180],
                            "retry_max_tokens": 2200,
                        })
                        examine(start, end, single_retry=True)
                        return
                    raise ValueError(
                        f"AI_REVIEW_UNRECOVERABLE_OUTPUT: {module.file_path}:"
                        f"{start + 1}-{end}: {exc}") from exc
                if not isinstance(result, dict) or not isinstance(
                    result.get("findings"), list):
                    raise ValueError(
                        f"AI_REVIEW_INVALID_RESPONSE: {module.file_path}:{start + 1}-{end}")
                for finding in result["findings"][:2]:
                    if not isinstance(finding, dict):
                        continue
                    line = finding.get("line")
                    quote = finding.get("quote")
                    issue = finding.get("issue")
                    if type(line) is not int or not (start < line <= end):
                        continue
                    if not isinstance(quote, str) or not quote.strip():
                        continue
                    if quote.strip() not in lines[line - 1]:
                        continue  # Cannot block based on hallucinated evidence.
                    if not isinstance(issue, str) or not issue.strip():
                        continue
                    report["findings"].append({
                        "file": module.file_path, "line": line,
                        "quote": quote.strip()[:180],
                        "severity": ("blocking" if finding.get("severity") == "blocking"
                                     else "advisory"),
                        "issue": issue.strip()[:350],
                        "repair": str(finding.get("repair", ""))[:350],
                        "evidence": "source_line_quote_matched",
                    })
                report["reviewed"].append({
                    "file": module.file_path, "from_line": start + 1,
                    "to_line": end,
                })

            for start, end in _initial_ranges(lines, max_lines_per_chunk):
                examine(start, end)

        # Every line must be covered exactly once. File-hash presence alone
        # previously declared full coverage even if ranges had gaps.
        coverage = {path: [0] * count for path, count in actual_lines.items()}
        for record in report["reviewed"]:
            slots = coverage[record["file"]]
            for index in range(record["from_line"] - 1, record["to_line"]):
                slots[index] += 1
        report["fully_covered"] = bool(coverage) and all(
            all(count == 1 for count in values) for values in coverage.values())
        if not report["fully_covered"]:
            raise ValueError("AI_REVIEW_SOURCE_COVERAGE_INCOMPLETE")
        blocking = any(x["severity"] == "blocking" for x in report["findings"])
        report["status"] = "issues_found" if blocking else "reviewed_no_blockers"
        report["reason"] = (
            "Blocking source-grounded AI findings need generator/code repair"
            if blocking else
            "Full source line review completed; no Roblox runtime verification"
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            RecursionError) as exc:
        report["status"] = "failed"
        report["fully_covered"] = False
        report["reason"] = type(exc).__name__ + ": " + str(exc)[:500]
    if report["fully_covered"] and report["status"] in (
            "issues_found", "reviewed_no_blockers"):
        from .source_finding_adjudication import adjudicate_source_findings
        return adjudicate_source_findings(proposal, report)
    return report
