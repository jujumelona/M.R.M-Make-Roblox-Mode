"""Source-grounded, action-by-action audit after *all* game modules exist.

A green parser or one valid mutation in a server module cannot prove a
multi-part gameplay requirement. This pass checks every independently
promised authoritative effect against the *assembled* generated server code,
including consumers in other modules. No Roblox Studio claim is made.

The user request is the authority. The AI-authored plan supplies candidate
observable effects to test, not permission to introduce new requirements.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "rmm/whole-requirement-completion-audit-v1"
MAX_SOURCE_CHARS = 72000
MAX_OBLIGATIONS = 16
MAX_REQUIREMENTS = 24


def _obligations(requirement: dict[str, Any]) -> list[dict[str, str]]:
    steps = requirement.get("ai_implementation_steps") or {}
    changes = (steps.get("server_state_changes") or []) if isinstance(steps, dict) else []
    if not isinstance(changes, list):
        changes = []
    statements = [row.strip() for row in changes
                  if isinstance(row, str) and len(row.strip()) >= 12]
    if not statements:
        expected = str(requirement.get("expected_outcome") or "")
        statements = [part.strip() for part in re.split(
            r"(?<=[.;])\s+(?=[A-Z가-힣])", expected,
        ) if len(part.strip()) >= 12]
    if not statements:
        return []
    result = []
    seen = set()
    for sentence in statements:
        # Distinct effects such as a debit AND a persistent upgrade must not
        # disappear behind one positive code quote for the whole requirement.
        key = re.sub(r"\s+", " ", sentence).casefold()
        if key not in seen:
            seen.add(key)
            result.append({"id": f"effect-{len(result)+1:02d}",
                           "behavior": sentence[:900]})
    return result


def _real_source_quote(root: Path, path: str, quote: str) -> int:
    if not isinstance(quote, str) or not 6 <= len(quote) <= 320:
        return 0
    source = (root / path).read_text(encoding="utf-8")
    if quote not in source:
        return 0
    # A claim based solely on a Luau comment is not executable evidence.
    before = source[:source.index(quote)]
    first_line = before.count("\n") + 1
    evidence_line = source.splitlines()[first_line - 1].lstrip()
    if evidence_line.startswith("--"):
        return 0
    return first_line


def audit_whole_requirement_completion(
    proposal: Any, root: Path, router: Any,
) -> dict[str, Any]:
    """Check independent gameplay effects AFTER all executable files exist.

    Returns blocking source-anchored findings directly usable by the existing
    transactional per-file repair / re-review cycle. Unknown or malformed
    model output fails closed, rather than being called a complete game.
    """
    root = Path(root)
    report: dict[str, Any] = {
        "schema": SCHEMA, "executed": False, "fully_covered": False,
        "status": "failed", "reason": "", "checks": [], "findings": [],
    }
    requirements = ((proposal.game_design.get("detailed_implementation_plan") or {})
                    .get("required_functions") or [])
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= MAX_REQUIREMENTS:
        report["reason"] = "No bounded original requirement ledger"
        return report
    by_name = {m.name: m.file_path for m in proposal.modules}
    known_paths = {m.file_path for m in proposal.modules}
    for req in requirements:
        if not isinstance(req, dict):
            report["reason"] = "Invalid requirement entry"
            return report
        req_id = str(req.get("id") or "")
        original = str(req.get("original_request") or req.get("source") or "")
        if not req_id or not original:
            report["reason"] = "Missing original source requirement"
            return report
        obligations = _obligations(req)
        if not 1 <= len(obligations) <= MAX_OBLIGATIONS:
            report["reason"] = req_id + ": no bounded independent effect obligations"
            return report
        owners = req.get("owner_files") or [
            by_name[name] for name in req.get("owner_modules", ())
            if name in by_name
        ]
        if not isinstance(owners, list):
            report["reason"] = req_id + ": invalid owner file roster"
            return report
        server_paths = sorted({
            path for path in owners
            if isinstance(path, str) and path.startswith("src/server/")
        })
        if not server_paths or any(path not in known_paths
                                   or not (root / path).is_file()
                                   for path in server_paths):
            report["reason"] = req_id + ": missing complete source ownership"
            return report
        actual_sources = {
            path: (root / path).read_text(encoding="utf-8")
            for path in server_paths
        }
        if sum(len(src) for src in actual_sources.values()) > MAX_SOURCE_CHARS:
            report["reason"] = (
                req_id + ": complete server effect sources exceed reviewer budget; "
                "do not claim coverage from excerpts"
            )
            return report
        prompt = (
            "Post-generation, end-to-end SOURCE audit of an assembled Roblox "
            "experience. The game is already generated. The exact ORIGINAL "
            "USER REQUEST is the authority. The listed candidate effects "
            "are commitments from the implementation plan, NOT permission "
            "to invent extra user requirements. Check EACH effect by its "
            "stable id independently. An upgrade level alone is NOT proof "
            "of a performance effect; a damageable object alone is NOT "
            "proof of combat against an actively hostile opponent. A Remote "
            "or UI click alone is NOT proof of the server-side game action. "
            "Read the COMPLETE ACTUAL server source of ALL owners together "
            "and follow producer-consumer state keys across them. Return one "
            "check per candidate id with verdict implemented, missing, or "
            "out_of_scope (only if NOT requested by the original user). "
            "For implemented and missing give EXACT non-comment Luau quote "
            "and precise owner file. Missing quotes should show the defective "
            "substitute or incomplete action, so a scoped repair can be "
            "applied. For out_of_scope cite why it is not requested; "
            "never use that verdict to evade a genuine user requirement. "
            "Also list any missing ORIGINAL requested player-observable "
            "actions OMITTED FROM THE PLAN in extra_missing. Every extra "
            "missing action must have a real owner and exact defective-source "
            "quote. Do NOT claim runtime/Studio verification. Return ONLY "
            "the contracted JSON.\n"
            + json.dumps({
                "requirement_id": req_id,
                "original_user_request": original[:2400],
                "candidate_effects": obligations,
                "complete_server_sources": actual_sources,
            }, ensure_ascii=False)
        )
        report["executed"] = True
        try:
            result = router.complete_json(
                prompt=prompt, role="analyzer", temperature=0,
                max_tokens=2500,
                json_schema={
                    "type": "object",
                    "properties": {
                        "checks": {
                            "type": "array", "minItems": 1, "maxItems": MAX_OBLIGATIONS,
                            "items": {"type": "object", "properties": {
                                "id": {"type": "string"},
                                "verdict": {"type": "string", "enum": [
                                    "implemented", "missing", "out_of_scope",
                                ]},
                                "file": {"type": "string"},
                                "quote": {"type": "string"},
                                "issue": {"type": "string"},
                                "repair": {"type": "string"},
                            }, "required": [
                                "id", "verdict", "file", "quote", "issue", "repair",
                            ], "additionalProperties": False},
                        },
                        "extra_missing": {"type": "array", "maxItems": 12,
                                          "items": {"type": "object", "properties": {
                                              "behavior": {"type": "string"},
                                              "file": {"type": "string"},
                                              "quote": {"type": "string"},
                                              "issue": {"type": "string"},
                                              "repair": {"type": "string"},
                                          }, "required": [
                                              "behavior", "file", "quote",
                                              "issue", "repair",
                                          ], "additionalProperties": False}},
                    },
                    "required": ["checks", "extra_missing"],
                    "additionalProperties": False,
                },
            )
        except Exception as exc:
            report["reason"] = req_id + ": audit unavailable: " + (
                type(exc).__name__ + ": " + str(exc))[:300]
            return report
        if not isinstance(result, dict):
            report["reason"] = req_id + ": invalid completed-action audit JSON"
            return report
        checks = result.get("checks")
        extras = result.get("extra_missing")
        expected_ids = {row["id"] for row in obligations}
        if (not isinstance(checks, list)
                or len(checks) != len(expected_ids)
                or {row.get("id") for row in checks
                    if isinstance(row, dict)} != expected_ids
                or not isinstance(extras, list) or len(extras) > 12):
            report["reason"] = req_id + ": incomplete or duplicate independent effect checks"
            return report
        for entry in checks + extras:
            if not isinstance(entry, dict):
                report["reason"] = req_id + ": malformed effect evidence"
                return report
            verdict = entry.get("verdict", "missing")
            if verdict not in ("implemented", "missing", "out_of_scope"):
                report["reason"] = req_id + ": invalid effect verdict"
                return report
            file_path = entry.get("file")
            if verdict == "out_of_scope":
                if (not isinstance(entry.get("issue"), str)
                        or len(entry["issue"].strip()) < 12):
                    report["reason"] = req_id + ": unreasoned scope exclusion"
                    return report
                report["checks"].append({
                    "requirement_id": req_id, **entry, "scope": "plan_only",
                })
                continue
            if not isinstance(file_path, str) or file_path not in server_paths:
                report["reason"] = req_id + ": effect cites unauthorized server"
                return report
            line = _real_source_quote(root, file_path, entry.get("quote"))
            if not line:
                report["reason"] = req_id + ": ungrounded effect quote in " + file_path
                return report
            evidence = {"requirement_id": req_id, **entry, "line": line}
            report["checks"].append(evidence)
            if verdict == "missing":
                issue = str(entry.get("issue") or "")
                repair = str(entry.get("repair") or "")
                if len(issue.strip()) < 8 or len(repair.strip()) < 8:
                    report["reason"] = req_id + ": missing defect or repair instructions"
                    return report
                report["findings"].append({
                    "file": file_path, "line": line,
                    "quote": entry["quote"][:180], "severity": "blocking",
                    "requirement_id": req_id,
                    "issue": req_id + ": " + issue[:300],
                    "repair": repair[:350],
                    "behavior": entry.get("behavior") or next(
                        (o["behavior"] for o in obligations
                         if o["id"] == entry.get("id")), ""
                    ),
                    "evidence": "requirement_effect_review_source_quote",
                })
    report["fully_covered"] = True
    report["status"] = "issues_found" if report["findings"] else "reviewed_no_blockers"
    report["reason"] = (
        "Individual original-request effects are missing in generated sources"
        if report["findings"] else
        "All independently listed effects source-reviewed; Studio NOT executed"
    )
    return report
