"""Independent requirement-to-effect review of the generated Luau sources.

A source parser can prove API names and RemoteFunction wiring yet miss the
requested *effect* (e.g. upgrading a displayed rank instead of ship thrust).
This review uses the original user wording AND expected observable outcome
after materialization. All model evidence must point into actual generated
files. It never claims Roblox Studio execution.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "rmm/requirement-effect-review-v1"
MAX_OWNER_CONTEXT = 24000
MAX_REQUIREMENTS = 24


def _excerpt(text: str, budget: int) -> str:
    """A bounded view; short sources remain complete."""
    if len(text) <= budget:
        return text
    head = budget // 2
    tail = budget - head - 40
    return text[:head] + "\n...[SOURCE EXCERPT OMITTED]...\n" + text[-tail:]


def _locate(source: str, quote: str) -> int:
    if not quote or len(quote) < 6 or quote not in source:
        return 0
    return source[:source.index(quote)].count("\n") + 1


def review_requirement_effects(proposal: Any, root: Path, router: Any) -> dict[str, Any]:
    """Inspect every explicitly owned requirement; block ungrounded passes.

    'missing' is a model finding, *not* proven absence. It becomes eligible
    for a targeted verified repair, and re-review must inspect the new bytes.
    'uncertain' or invalid evidence fails closed rather than fabricating success.
    """
    report: dict[str, Any] = {
        "schema": SCHEMA, "scope": "source_semantics_no_roblox_engine",
        "status": "failed", "executed": False, "fully_covered": False,
        "reason": "", "requirements": [], "findings": [], "source_sha256": {},
    }
    detail = (getattr(proposal, "game_design", {}) or {}).get(
        "detailed_implementation_plan") or {}
    reqs = detail.get("required_functions") or []
    if not isinstance(reqs, list) or not reqs or len(reqs) > MAX_REQUIREMENTS:
        report["reason"] = "Missing or oversized original requirement contract"
        return report
    modules = {m.file_path: m for m in proposal.modules}
    by_name = {m.name: m.file_path for m in proposal.modules}
    root = Path(root)
    for m in proposal.modules:
        path = root / m.file_path
        if not path.is_file():
            report["reason"] = "Missing source: " + m.file_path
            return report
        source = path.read_text(encoding="utf-8")
        report["source_sha256"][m.file_path] = hashlib.sha256(
            source.encode("utf-8")).hexdigest()

    for req in reqs:
        if not isinstance(req, dict) or not isinstance(req.get("id"), str):
            report["reason"] = "Invalid original requirement entry"
            return report
        req_id = req["id"]
        original = req.get("original_request") or req.get("source")
        outcome = req.get("expected_outcome")
        if not isinstance(original, str) or not original.strip():
            report["reason"] = req_id + ": missing exact user source"
            return report
        if not isinstance(outcome, str) or not outcome.strip():
            report["reason"] = req_id + ": no observable outcome to check"
            return report
        files = req.get("owner_files") or [
            by_name[name] for name in req.get("owner_modules", [])
            if name in by_name
        ]
        files = sorted(set(files))
        if not files or any(path not in modules for path in files):
            report["reason"] = req_id + ": missing actual source owners"
            return report
        # Budget is divided across owners, never filled solely by the first.
        each = max(1000, MAX_OWNER_CONTEXT // len(files))
        samples: list[dict[str, str]] = []
        for file_path in files:
            source = (root / file_path).read_text(encoding="utf-8")
            samples.append({
                "file": file_path,
                "source": _excerpt(source, each),
                "truncated": len(source) > each,
            })
        prompt = (
            "Independent Roblox Luau BEHAVIOR review. Compare the EXACT "
            "original request and each clause of the observable outcome with "
            "the provided owner sources. Inspect actual server-side state "
            "mutations and downstream usage. A rank counter/attribute alone "
            "does NOT prove physical thrust/speed/capacity; a stationary "
            "health Part alone does NOT prove NPC AI; names/GUI/remotes do "
            "NOT prove working mechanics. Never claim Studio playtesting. "
            "Return JSON only: verdict ('implemented', 'missing', 'uncertain'), "
            "file (one of provided paths), quote (EXACT verbatim substring of "
            "that file), issue (specific unfulfilled outcome, or 'none'), "
            "repair (concrete change needed, or 'none'). "
            "To say implemented you must have inspected ALL outcome clauses, "
            "and provide one actual effect-bearing source quote; do not "
            "treat a trivial return/constant as effect evidence. "
            "Say missing ONLY with an actual quoted limited behavior. "
            "If excerpts omit needed code, say uncertain.\n" +
            json.dumps({
                "requirement_id": req_id,
                "original_request": original[:2200],
                "expected_outcome": outcome[:4600],
                "owner_sources": samples,
            }, ensure_ascii=False)
        )
        report["executed"] = True
        try:
            result = router.complete_json(
                prompt=prompt, role="analyzer", temperature=0, max_tokens=1100,
            )
        except Exception as exc:
            report["reason"] = req_id + ": model review failed: " + (
                type(exc).__name__ + ": " + str(exc))[:350]
            return report
        if not isinstance(result, dict):
            report["reason"] = req_id + ": invalid model output"
            return report
        verdict = result.get("verdict")
        path = result.get("file")
        quote = result.get("quote")
        if verdict not in ("implemented", "missing", "uncertain"):
            report["reason"] = req_id + ": invalid verdict"
            return report
        if verdict == "uncertain":
            report["requirements"].append({
                "id": req_id, "verdict": verdict, "issue": str(result.get("issue", ""))[:350],
            })
            report["reason"] = req_id + ": effect cannot be verified from owner sources"
            return report
        if path not in files or not isinstance(quote, str):
            report["reason"] = req_id + ": unknown evidence owner"
            return report
        source = (root / path).read_text(encoding="utf-8")
        line = _locate(source, quote)
        if not line:
            report["reason"] = req_id + ": missing or fabricated source evidence"
            return report
        # A claim based only on a truncated excerpt cannot establish absence
        # across the full module; it still needs an actual source location.
        record = {
            "id": req_id, "verdict": verdict, "file": path, "line": line,
            "quote": quote[:180], "issue": str(result.get("issue", ""))[:350],
        }
        report["requirements"].append(record)
        if verdict == "missing":
            issue = str(result.get("issue", "")).strip()
            repair = str(result.get("repair", "")).strip()
            if len(issue) < 8 or len(repair) < 8:
                report["reason"] = req_id + ": missing concrete defect and repair"
                return report
            report["findings"].append({
                "file": path, "line": line, "quote": quote[:180],
                "severity": "blocking", "requirement_id": req_id,
                "issue": req_id + ": " + issue[:300],
                "repair": repair[:350],
                "evidence": "requirement_effect_review_source_quote",
            })
    report["fully_covered"] = True
    report["status"] = ("issues_found" if report["findings"]
                        else "reviewed_no_blockers")
    report["reason"] = (
        "Requirement-level source behavior gaps detected; corrections required"
        if report["findings"] else
        "Every requirement reviewed with source citations; NOT engine verification"
    )
    return report
