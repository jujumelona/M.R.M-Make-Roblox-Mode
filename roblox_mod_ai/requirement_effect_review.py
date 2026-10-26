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
from pathlib import Path
from typing import Any

SCHEMA = "rmm/requirement-effect-review-v1"
MAX_SINGLE_SOURCE_CHARS = 16000
MAX_REQUIREMENTS = 24


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
        # A requirement may own several independent gameplay systems. Read
        # each SERVER owner in full and judge its specific promised behavior,
        # instead of asking a 9B model to infer six systems from head/tail
        # fragments. A missing part of any system blocks that requirement.
        servers = [path for path in files if path.startswith("src/server/")]
        if not servers:
            report["reason"] = req_id + ": no authoritative server source owner"
            return report
        for file_path in servers:
            source = (root / file_path).read_text(encoding="utf-8")
            if len(source) > MAX_SINGLE_SOURCE_CHARS:
                report["reason"] = (
                    req_id + ": full source exceeds reviewer context for " + file_path
                )
                return report
            module = modules[file_path]
            responsibility = str(getattr(module, "description", "") or "")
            # A written implementation responsibility is a promise, not code
            # evidence. The reviewer must inspect the entire actual Luau file.
            prompt = (
                "Independently audit ONE complete Roblox Luau server source. "
                "Check whether the OWNED BEHAVIOR below actually mutates the "
                "real server-owned state described, and whether that state is "
                "read by downstream gameplay where required. A rank counter "
                "or attribute alone does not implement speed, thrust, capacity "
                "or weapon damage. A static target alone is not NPC combat AI. "
                "A broker-only sale is not a player-to-player transfer. "
                "Do not assume missing code exists in other files. "
                "Do not require this ONE file to implement unrelated clauses "
                "owned by other modules. Reply 'implemented' only if THIS "
                "module's complete declared responsibility is implemented by "
                "real source effects. Reply 'missing' with a real code quote "
                "if an essential promised effect is absent or substituted. "
                "Reply 'uncertain' only for dependencies that genuinely cannot "
                "be decided from this full source. Never claim Studio testing. "
                "Return ONLY JSON: verdict, file, quote, issue, repair. "
                "For implemented/missing, quote an EXACT substring of the file "
                "showing the relevant effect or its inadequate substitute.\n"
                + json.dumps({
                    "requirement_id": req_id,
                    "original_request": original[:2200],
                    "expected_outcome": outcome[:4600],
                    "module": module.name,
                    "file": file_path,
                    "owned_behavior": responsibility[:1800],
                    "entire_source": source,
                }, ensure_ascii=False)
            )
            report["executed"] = True
            try:
                result = router.complete_json(
                    prompt=prompt, role="analyzer", temperature=0,
                    max_tokens=1100,
                    json_schema={
                        "type": "object",
                        "properties": {
                            "verdict": {"type": "string", "enum": [
                                "implemented", "missing", "uncertain"]},
                            "file": {"type": "string", "maxLength": 240},
                            "quote": {"type": "string", "maxLength": 260},
                            "issue": {"type": "string", "maxLength": 350},
                            "repair": {"type": "string", "maxLength": 350},
                        },
                        "required": ["verdict", "file", "quote", "issue", "repair"],
                        "additionalProperties": False,
                    },
                )
            except Exception as exc:
                report["reason"] = req_id + "/" + file_path + ": model review failed: " + (
                    type(exc).__name__ + ": " + str(exc))[:350]
                return report
            if not isinstance(result, dict):
                report["reason"] = req_id + "/" + file_path + ": invalid model output"
                return report
            verdict = result.get("verdict")
            path = result.get("file")
            quote = result.get("quote")
            if verdict not in ("implemented", "missing", "uncertain"):
                report["reason"] = req_id + "/" + file_path + ": invalid verdict"
                return report
            if verdict == "uncertain":
                report["requirements"].append({
                    "id": req_id, "file": file_path, "verdict": verdict,
                    "issue": str(result.get("issue", ""))[:350],
                })
                report["reason"] = (
                    req_id + "/" + file_path +
                    ": unresolved source dependency; no automatic pass"
                )
                return report
            if path != file_path or not isinstance(quote, str):
                report["reason"] = req_id + ": unknown source-evidence owner"
                return report
            line = _locate(source, quote)
            if not line:
                report["reason"] = req_id + ": missing or fabricated source evidence"
                return report
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
