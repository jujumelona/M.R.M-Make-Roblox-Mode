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


_STATE_VERB = re.compile(
    r"\b(?:increase|decrease|credit|debit|grant|deduct|award|subtract|"
    r"add|remove|persist|attach|change|update|mutate|set|produce|consume|"
    r"transfer|spawn|destroy|acquire|gain|earn|build|launch|travel|"
    r"arrive|extract|mark|place|reduce)(?:s|d|ed)?\b|"
    r"증가|감소|지급|저장|적립|차감|장착|연결|이동|획득|소모|"
    r"변경|발사|적용|생성|파괴|거래",
    re.I,
)


def _independent_effect_clauses(statement: str) -> list[str]:
    """Unbundle promised changes; a debit cannot certify an unrelated credit.

    The input is ordinary natural-language state-change prose, not a fixed
    game-feature vocabulary. A conjunction splits only when BOTH sides
    assert real effects. Noun groups ('damage, rate, and capacity are
    updated') stay together because the left half has no state verb.
    """
    sentences = re.split(r";\s*|(?<=\.)\s+(?=[A-Z가-힣])", statement)
    separated: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip().rstrip(".;")
        if len(sentence) < 12:
            continue
        pieces = re.split(r"(?i),?\s+\band\b\s+|,\s*그리고\s+|\s+그리고\s+", sentence)
        if len(pieces) > 1 and all(
            len(piece.strip()) >= 12 and _STATE_VERB.search(piece)
            for piece in pieces
        ):
            separated.extend(piece.strip() for piece in pieces)
        else:
            separated.append(sentence)
    return separated


def _obligations(requirement: dict[str, Any]) -> list[dict[str, str]]:
    # Deployed proposals store effects at the TOP LEVEL of each required
    # function, while some planners also include a nested implementation
    # plan. Prefer the concrete persisted state-change contract over a
    # broader one-line expected-outcome summary.
    direct = requirement.get("server_state_changes") or []
    steps = requirement.get("ai_implementation_steps") or {}
    nested = (steps.get("server_state_changes") or []) if isinstance(steps, dict) else []
    changes = direct if isinstance(direct, list) and direct else nested
    if not isinstance(changes, list):
        changes = []
    statements = [row.strip() for row in changes
                  if isinstance(row, str) and len(row.strip()) >= 12]
    if not statements:
        expected = str(requirement.get("expected_outcome") or "")
        statements = [expected] if len(expected.strip()) >= 12 else []
    if not statements:
        return []
    result = []
    seen = set()
    for sentence in statements:
        for part in _independent_effect_clauses(sentence):
            key = re.sub(r"\s+", " ", part).casefold()
            if key not in seen:
                seen.add(key)
                result.append({"id": f"effect-{len(result)+1:02d}",
                               "behavior": part[:900]})
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
            ) if len(obligations) <= 3 else {}
            if len(obligations) > 3:
                # Prevent an overlong multi-effect output on local small models.
                # Host-owned IDs are bound to individual result objects below.
                report.setdefault("recovery", []).append({
                    "requirement_id": req_id, "stage": "batch_skipped",
                    "reason": "More than three independent effects",
                    "effect_count": len(obligations),
                })
        except ValueError as exc:
            # Small local models can truncate an all-effects JSON response.
            # This is a transport/output failure, never proof of implementation.
            result = {}
            report.setdefault("recovery", []).append({
                "requirement_id": req_id, "stage": "batch_output",
                "error": (type(exc).__name__ + ": " + str(exc))[:300],
            })
        except Exception as exc:
            report["reason"] = req_id + ": audit unavailable: " + (
                type(exc).__name__ + ": " + str(exc))[:300]
            return report
        if not isinstance(result, dict):
            result = {}
        checks = result.get("checks")
        extras = result.get("extra_missing")
        expected_ids = {row["id"] for row in obligations}
        supplied = checks if isinstance(checks, list) else []
        occurrences: dict[str, list[dict[str, Any]]] = {
            effect_id: [] for effect_id in expected_ids
        }
        unexpected = []
        for entry in supplied:
            if not isinstance(entry, dict):
                unexpected.append("<malformed>")
                continue
            effect_id = entry.get("id")
            if isinstance(effect_id, str) and effect_id in occurrences:
                occurrences[effect_id].append(entry)
            else:
                unexpected.append(str(effect_id)[:80])
        # Only unambiguously identified answers can be reused. The host owns
        # the obligation IDs; no model answer may silently replace an effect.
        recover_ids = [
            row["id"] for row in obligations
            if len(occurrences[row["id"]]) != 1
        ]
        if recover_ids or unexpected:
            report.setdefault("recovery", []).append({
                "requirement_id": req_id, "stage": "batch_cardinality",
                "expected": [o["id"] for o in obligations],
                "missing_or_duplicate": recover_ids,
                "unexpected": unexpected[:20],
                "received_count": len(supplied),
            })
        for effect in obligations:
            effect_id = effect["id"]
            if effect_id not in recover_ids:
                continue
            # Crucially, this response does NOT ask the small model to copy an
            # effect ID or generate an N-element array. The host attaches the
            # canonical ID to precisely one reviewed obligation.
            single_prompt = (
                "Audit exactly ONE promised Roblox gameplay state change. "
                "SOURCE ONLY; do not claim Roblox Studio execution. "
                "Original user request is authoritative. Check the candidate "
                "effect against complete server owners and producer/consumer "
                "state keys. A UI/Remote alone cannot prove a server mutation. "
                "Return exactly one JSON object with verdict implemented, "
                "missing or out_of_scope; file; an EXACT non-comment source "
                "quote; issue; repair. If missing, quote the defective "
                "substitute or incomplete action and provide a concrete fix. "
                "Only use out_of_scope if clearly NOT requested by user. "
                "Do not emit lists or effect IDs.\\n"
                + json.dumps({
                    "original_user_request": original[:2400],
                    "candidate_effect": effect["behavior"],
                    "complete_server_sources": actual_sources,
                }, ensure_ascii=False)
            )
            single_schema = {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": [
                        "implemented", "missing", "out_of_scope",
                    ]},
                    "file": {"type": "string"},
                    "quote": {"type": "string"},
                    "issue": {"type": "string"},
                    "repair": {"type": "string"},
                },
                "required": ["verdict", "file", "quote", "issue", "repair"],
                "additionalProperties": False,
            }
            try:
                one = router.complete_json(
                    prompt=single_prompt, role="analyzer", temperature=0,
                    max_tokens=640, json_schema=single_schema,
                )
            except Exception as exc:
                report.setdefault("recovery", []).append({
                    "requirement_id": req_id, "effect_id": effect_id,
                    "stage": "single_effect", "status": "failed",
                    "error": (type(exc).__name__ + ": " + str(exc))[:250],
                })
                report["reason"] = (
                    req_id + ": incomplete independent effect checks; "
                    + effect_id + " could not be reviewed"
                )
                return report
            if (not isinstance(one, dict)
                    or one.get("verdict") not in (
                        "implemented", "missing", "out_of_scope")
                    or not all(isinstance(one.get(k), str) for k in (
                        "file", "quote", "issue", "repair"))):
                report["reason"] = (
                    req_id + ": incomplete independent effect checks; "
                    + effect_id + " returned invalid single-effect evidence"
                )
                return report
            occurrences[effect_id] = [{"id": effect_id, **one}]
            report.setdefault("recovery", []).append({
                "requirement_id": req_id, "effect_id": effect_id,
                "stage": "single_effect", "status": "recovered",
            })
        checks = [
            occurrences[o["id"]][0] for o in obligations
            if len(occurrences[o["id"]]) == 1
        ]
        if len(checks) != len(obligations):
            report["reason"] = (
                req_id + ": incomplete independent effect checks after recovery"
            )
            return report
        if not isinstance(extras, list) or recover_ids or unexpected:
            # An incomplete batch cannot attest to original-request coverage
            # merely by returning extra_missing: []. Audit omissions anew.
            retained_extras = extras if isinstance(extras, list) else []
            try:
                extra_result = router.complete_json(
                    prompt=(
                        "Find original user-requested gameplay state changes "
                        "OMITTED FROM the candidate list, not defects already "
                        "covered by it. Read ALL server owners; source only. "
                        "Every extra_missing item must include behavior, exact "
                        "server file, exact non-comment defective quote, "
                        "issue and concrete repair. Return ONLY "
                        "{extra_missing:[...]}; [] when none.\\n"
                        + json.dumps({
                            "original_user_request": original[:2400],
                            "candidate_effects": obligations,
                            "complete_server_sources": actual_sources,
                        }, ensure_ascii=False)
                    ),
                    role="analyzer", temperature=0, max_tokens=1100,
                    json_schema={
                        "type": "object",
                        "properties": {"extra_missing": {
                            "type": "array", "maxItems": 12,
                            "items": {"type": "object", "properties": {
                                "behavior": {"type": "string"},
                                "file": {"type": "string"},
                                "quote": {"type": "string"},
                                "issue": {"type": "string"},
                                "repair": {"type": "string"},
                            }, "required": [
                                "behavior", "file", "quote", "issue", "repair",
                            ], "additionalProperties": False},
                        }},
                        "required": ["extra_missing"],
                        "additionalProperties": False,
                    },
                )
                fresh_extras = extra_result.get("extra_missing") if isinstance(
                    extra_result, dict) else None
                if isinstance(fresh_extras, list):
                    extras = list(retained_extras)
                    existing = {(e.get("file"), e.get("quote"), e.get("behavior"))
                                for e in extras if isinstance(e, dict)}
                    for entry in fresh_extras:
                        if not isinstance(entry, dict):
                            extras = None
                            break
                        key = (entry.get("file"), entry.get("quote"),
                               entry.get("behavior"))
                        if key not in existing:
                            extras.append(entry)
                            existing.add(key)
                else:
                    extras = None
            except Exception as exc:
                report.setdefault("recovery", []).append({
                    "requirement_id": req_id, "stage": "omitted_effects",
                    "status": "failed",
                    "error": (type(exc).__name__ + ": " + str(exc))[:250],
                })
                extras = None
        if not isinstance(extras, list) or len(extras) > 12:
            report["reason"] = (
                req_id + ": incomplete original-request omitted-effect audit"
            )
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
