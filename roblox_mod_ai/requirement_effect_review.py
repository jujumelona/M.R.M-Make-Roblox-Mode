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
import re
from pathlib import Path

from .source_upgrade_contract import attest_paid_upgrade
from typing import Any

SCHEMA = "rmm/requirement-effect-review-v1"
MAX_SINGLE_SOURCE_CHARS = 16000
MAX_REQUIREMENTS = 24


def _locate(source: str, quote: str) -> int:
    if not quote or len(quote) < 6 or quote not in source:
        return 0
    return source[:source.index(quote)].count("\n") + 1


def _recover_source_line(
    source: str, path: str, requirement_id: str, reported: dict[str, Any],
    router: Any,
) -> tuple[int, str] | None:
    """Recover a real Luau evidence line; NEVER trust invented free-form quotes.

    The first model's claim can be useful without its invented citation. A
    second bounded request identifies an exact PHYSICAL source line, and the
    host—not the LLM—extracts the actual bytes. This is source-grounding only,
    not proof that the model's semantic judgement is true.
    """
    lines = source.splitlines()
    numbered = "\n".join(
        f"{index}: {line}" for index, line in enumerate(lines, start=1)
    )
    response = router.complete_json(
        prompt=(
            "The previous analysis cited a string that is NOT present "
            "verbatim in the complete source. Find ONE relevant PHYSICAL "
            "source line numbered below which directly demonstrates the "
            "stated defect or actual implementation effect. "
            "Respond with JSON {line: integer, explanation: string}. "
            "Do NOT invent source or a line. If no suitable concrete line "
            "exists, use line 0. An invented citation will be rejected.\n"
            + json.dumps({
                "requirement_id": requirement_id,
                "file": path,
                "verdict": reported.get("verdict"),
                "issue": str(reported.get("issue", ""))[:350],
                "old_invalid_quote": str(reported.get("quote", ""))[:260],
                "numbered_complete_source": numbered,
            }, ensure_ascii=False)
        ),
        role="analyzer", temperature=0, max_tokens=450,
        json_schema={
            "type": "object",
            "properties": {
                "line": {"type": "integer"},
                "explanation": {"type": "string", "maxLength": 250},
            },
            "required": ["line", "explanation"],
            "additionalProperties": False,
        },
    )
    if not isinstance(response, dict):
        return None
    line_number = response.get("line")
    if type(line_number) is not int or not 1 <= line_number <= len(lines):
        return None
    actual = lines[line_number - 1].strip()
    if (len(actual) < 8 or actual.startswith(("--", "--[", "*"))
            or actual in ("end", "else", "return false", "return nil")):
        return None
    return line_number, actual[:180]


def _review_with_bounded_truncation_recovery(
    router: Any, prompt: str, source: str, file_path: str,
    requirement_id: str, original: str, responsibility: str,
    downstream: list[dict[str, str]], schema: dict[str, Any],
    retries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recover from token-budget exhaustion without treating it as a verdict.

    The first pass retains the existing source-level review. If the local 9B
    consumes its response budget, a shorter, numbered-line JSON contract
    replaces verbose free-form quotes. The host selects evidence directly
    from the full source, never by trusting an invented model quotation.
    Only finish_reason=length is recoverable; all other failures remain real.
    """
    try:
        return router.complete_json(
            prompt=prompt, role="analyzer", temperature=0,
            max_tokens=1700, json_schema=schema,
        )
    except ValueError as exc:
        if "finish_reason=length" not in str(exc):
            raise
        retries.append({
            "requirement": requirement_id, "file": file_path,
            "reason": "model_output_truncated", "phase": "full_review",
            "token_budget": 1700,
        })

    lines = source.splitlines()
    numbered = "\n".join(f"{n}: {line}" for n, line in enumerate(lines, 1))
    compact_schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": [
                "implemented", "missing", "uncertain"]},
            "evidence_line": {"type": "integer"},
            "issue": {"type": "string", "maxLength": 200},
            "repair": {"type": "string", "maxLength": 200},
        },
        "required": ["verdict", "evidence_line", "issue", "repair"],
        "additionalProperties": False,
    }
    compact_prompt = (
        "Review exactly ONE Roblox Luau server module against its OWN user "
        "requirement; do not require other modules' responsibilities. "
        "Return ONLY one SHORT JSON object, with verdict, evidence_line "
        "(an EXACT physical line number in the numbered source; 0 only "
        "when uncertain), issue (one sentence), repair (one sentence). "
        "No source quote, no reasoning, no lists, no extra text. "
        "A rank or attribute alone does not prove physical performance. "
        "Do not invent peer-to-peer trading from the word trade. "
        "Evidence must show actual code effect or an inadequate substitute. "
        "No Studio gameplay verification.\n"
        + json.dumps({
            "requirement": original[:1100],
            "owned_behavior": responsibility[:1000],
            "file": file_path,
            "source_lines": numbered,
            "verified_downstream_server_sources": downstream,
        }, ensure_ascii=False)
    )
    # A constrained JSON schema is not a guarantee for small GGUF models.
    # If the enum is missing/invalid, change representation on the next
    # request instead of retrying the same broken schema or aborting the game.
    # Boolean questions are simpler than copying an enum verbatim.
    invalid_reason = ""
    length_failures = 0
    for attempt, budget in enumerate((2600, 4096)):
        simple = attempt > 0
        if simple:
            query = (
                "Assess the EXACT server-owned action below. Return a tiny JSON "
                "object with can_decide (JSON boolean), missing_effect (JSON "
                "boolean), evidence_line (integer), issue (short sentence), "
                "repair (short sentence). No verdict field, no markdown. "
                "If source evidence is insufficient, can_decide=false and "
                "evidence_line=0. When can_decide=true, evidence_line MUST "
                "refer to a real numbered executable source line. "
                "missing_effect=true means the original user's promised action "
                "is not really performed; a mere rank is not a physical effect. "
                "Do not invent requirements such as player-to-player trades "
                "when the original user says only trade. Do not demand other "
                "modules' responsibilities. DO NOT claim Roblox Studio tests. "
                "This is a REFORMULATION because the last output was unusable: "
                + invalid_reason[:200] + "\\n"
                + json.dumps({
                    "original_requirement": original[:900],
                    "owner_behavior": responsibility[:800],
                    "source_lines": numbered,
                    "verified_downstream_server_sources": downstream,
                }, ensure_ascii=False)
            )
            response_schema = {
                "type": "object", "properties": {
                    "can_decide": {"type": "boolean"},
                    "missing_effect": {"type": "boolean"},
                    "evidence_line": {"type": "integer"},
                    "issue": {"type": "string", "maxLength": 160},
                    "repair": {"type": "string", "maxLength": 160},
                },
                "required": ["can_decide", "missing_effect",
                             "evidence_line", "issue", "repair"],
                "additionalProperties": False,
            }
        else:
            query = compact_prompt
            response_schema = compact_schema
        try:
            short = router.complete_json(
                prompt=query, role="analyzer", temperature=0,
                max_tokens=budget, json_schema=response_schema,
            )
        except ValueError as exc:
            if "finish_reason=length" not in str(exc):
                raise
            length_failures += 1
            invalid_reason = "response hit output token ceiling"
            retries.append({
                "requirement": requirement_id, "file": file_path,
                "reason": "model_output_truncated",
                "phase": "boolean_review" if simple else "compact_line_review",
                "token_budget": budget,
            })
            continue
        if not isinstance(short, dict):
            invalid_reason = "model returned a non-object"
            retries.append({
                "requirement": requirement_id, "file": file_path,
                "reason": "invalid_model_result", "phase":
                    "boolean_review" if simple else "compact_line_review",
            })
            continue
        if simple:
            decidable = short.get("can_decide")
            missing_effect = short.get("missing_effect")
            if type(decidable) is not bool or type(missing_effect) is not bool:
                invalid_reason = "model did not return JSON booleans"
                retries.append({
                    "requirement": requirement_id, "file": file_path,
                    "reason": "invalid_boolean_result",
                    "phase": "boolean_review",
                })
                continue
            verdict = (
                "uncertain" if not decidable
                else "missing" if missing_effect else "implemented"
            )
        else:
            verdict = short.get("verdict")
            if verdict not in ("implemented", "missing", "uncertain"):
                # Logging the invalid value helps diagnose actual MiMo output;
                # do not normalize unknown words into 'implemented'.
                invalid_reason = (
                    "enum verdict invalid: " +
                    repr(short.get("verdict"))[:80]
                )
                retries.append({
                    "requirement": requirement_id, "file": file_path,
                    "reason": "invalid_compact_verdict",
                    "phase": "compact_line_review", "token_budget": budget,
                    "returned_verdict": repr(short.get("verdict"))[:80],
                })
                continue
        if verdict == "uncertain":
            return {
                "verdict": verdict, "file": file_path, "quote": "",
                "issue": str(short.get("issue", ""))[:200],
                "repair": str(short.get("repair", ""))[:200],
            }
        number = short.get("evidence_line")
        if type(number) is not int or not (1 <= number <= len(lines)):
            invalid_reason = "nonexistent physical source line"
            retries.append({
                "requirement": requirement_id, "file": file_path,
                "reason": "invalid_evidence_line",
                "phase": "boolean_review" if simple else "compact_line_review",
            })
            continue
        quote = lines[number - 1].strip()
        if (len(quote) < 8 or quote.startswith(("--", "*"))
                or quote in ("end", "else", "return false", "return nil")):
            invalid_reason = "source line is empty, comment or non-evidence"
            retries.append({
                "requirement": requirement_id, "file": file_path,
                "reason": "invalid_evidence_line",
                "phase": "boolean_review" if simple else "compact_line_review",
            })
            continue
        retries.append({
            "requirement": requirement_id, "file": file_path,
            "reason": "recovered_with_host_selected_source_line",
            "phase": "boolean_review" if simple else "compact_line_review",
            "token_budget": budget, "line": number,
        })
        return {
            "verdict": verdict, "file": file_path, "quote": quote[:180],
            "issue": str(short.get("issue", ""))[:200],
            "repair": str(short.get("repair", ""))[:200],
        }
    if length_failures == 2:
        raise ValueError(
            "Model JSON remained truncated after bounded compact-source retries"
        )
    raise ValueError(
        "Compact model review remained invalid after alternate boolean "
        "classification; last_error=" + invalid_reason[:200]
    )


def _downstream_effect_evidence(
    file_path: str, source: str, modules: dict[str, Any], root: Path,
) -> list[dict[str, str]]:
    """On-disk producer-to-consumer state paths, not semantic approval.

    Purchase scripts legitimately save a rank which another server module
    reads into damage or voyage duration. The 9B reviewer must inspect both
    sources before claiming that the rank has no gameplay effect.
    """
    namespaces = set(re.findall(
        r'GetState\s*\(\s*player\s*,\s*"(RMM[A-Za-z0-9_]+)"',
        source,
    ))
    if not namespaces:
        return []
    target_match = re.search(
        r'local\s+TARGET\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"',
        source,
    )
    target = target_match.group(1) if target_match else ""
    hints = {target} if target else set()
    # Some verified producers persist a per-item record (e.g.
    # saved[tool.Name] = {level=...}) instead of a literal TARGET scalar.
    # The consumer must read the SAME persisted namespace before it can
    # provide evidence of a gameplay effect. Never infer an item from the
    # module name or an unrelated shared inventory.
    authored_namespaces: set[str] = set()
    for namespace in namespaces:
        owned = re.search(
            r'\blocal\s+(\w+)\s*=\s*\w+\.GetState\s*\(\s*player\s*,\s*"'
            + re.escape(namespace) + r'"\s*\)', source,
        )
        if owned and re.search(
            r'\b' + re.escape(owned.group(1))
            + r'\s*\[[^\]\n]+\]\s*=(?!=)', source,
        ):
            authored_namespaces.add(namespace)
    if "RMMWeaponProgress" in namespaces:
        hints.update(("weapon.tier", "state.tier"))
    if "RMMShipSections" in namespaces:
        hints.update(("assemblyScore", "RMMShipAssemblyPerformance",
                      "GetOwnedActor"))
    found: list[dict[str, str]] = []
    for other in sorted(modules):
        if other == file_path or not other.startswith("src/server/"):
            continue
        content = (root / other).read_text(encoding="utf-8")
        shared = [ns for ns in namespaces if ns in content]
        if not shared or (target and target not in content):
            continue
        if not target and authored_namespaces:
            shared = [ns for ns in shared if ns in authored_namespaces]
            if not shared:
                continue
        # Inventory is a common shared namespace across unrelated actions.
        # An ownership or GetOwnedActor mention alone does not prove that
        # the specific RMMRankProgress/RMMShipSections record is consumed.
        if target and "RMMRankProgress" in namespaces and (
                "RMMRankProgress" not in shared):
            continue
        if "RMMShipSections" in namespaces and (
                "RMMShipSections" not in shared):
            continue
        if "RMMWeaponProgress" in namespaces and (
                "RMMWeaponProgress" not in shared):
            continue
        if hints and not any(hint and hint in content for hint in hints):
            continue
        if not hints and not authored_namespaces:
            continue
        # The consumer must actually access the producer's namespace via
        # a player-profile GetState call, not merely mention it in comments.
        if not target and not any(
            re.search(r'GetState\s*\(\s*player\s*,\s*"' + re.escape(ns)
                      + r'"\s*\)', content) for ns in shared
        ):
            continue
        lines = content.splitlines()
        indices = [
            i for i, line in enumerate(lines)
            if any(hint and hint in line for hint in hints)
        ]
        if not hints and authored_namespaces:
            indices = [i for i, line in enumerate(lines)
                       if any(ns in line for ns in shared)]
        # Prefer a calculation adjacent to the shared-state read, not a
        # distant GetOwnedActor call at the top of a large launch service.
        if "RMMShipSections" in shared:
            score_lines = [
                i for i, line in enumerate(lines)
                if "assemblyScore" in line or "RMMShipAssemblyPerformance" in line
            ]
            if score_lines:
                indices = score_lines
        if not indices:
            continue
        read_index = next(
            (i for i, line in enumerate(lines)
             if any(ns in line for ns in shared)), indices[0])
        begin = max(0, min(indices[0], read_index) - 5)
        end = min(len(lines), max(indices[0] + 28, read_index + 28))
        if not hints and authored_namespaces:
            # Deliver the real producer-consumer read plus compact relevant
            # state arithmetic and mutation lines. Large generated server
            # handlers often place the actual damage/physics sink 60+ lines
            # after the GetState call; a fixed 28-line excerpt hides it.
            relevant = [i for i, line in enumerate(lines)
                        if i >= read_index and i <= read_index + 140
                        and re.search(
                            r'GetState\s*\(|\.(?:level|damage|remaining|capacity)'
                            r'|\b(?:SetAttribute|PivotTo|TakeDamage|ApplyImpulse)'
                            r'\b|\b(?:damage|interval|ammo|upgradedLevel)\b',
                            line, re.I)]
            selected = sorted(set(
                [i for i in range(max(0, read_index - 2),
                                  min(len(lines), read_index + 8))]
                + relevant
            ))[:100]
            excerpt = "\n".join(f"{i + 1}: {lines[i]}" for i in selected)
        else:
            excerpt = "\n".join(
                f"{i + 1}: {lines[i]}" for i in range(begin, end)
            )
        found.append({
            "file": other,
            "shared_persisted_state": ", ".join(sorted(shared)),
            "source_excerpt": excerpt[:3700],
        })
        if len(found) >= 3:
            break
    return found


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
        "evidence_recovery": [], "model_retries": [], "cross_module_contracts": [],
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
            downstream = _downstream_effect_evidence(
                file_path, source, modules, root,
            )
            # The narrowly verified first-party rank protocol already has
            # deterministic evidence spanning currency persistence and the
            # actual gameplay consumer. Do not hand this proof to a 9B
            # language reviewer which repeatedly described server-owned
            # leaderstats as client-only and requested nonexistent APIs.
            # Any missing link automatically returns None and receives the
            # normal independent model review below.
            attestation = attest_paid_upgrade(
                source, file_path, original, modules, root,
            )
            if attestation is not None:
                report["executed"] = True
                report["requirements"].append({
                    "id": req_id, "verdict": "implemented",
                    "file": file_path, "line": attestation["line"],
                    "quote": attestation["quote"], "issue": "none",
                    "method": attestation["method"],
                    "scope": attestation["scope"],
                })
                report["cross_module_contracts"].append({
                    "requirement_id": req_id, **attestation,
                })
                continue
            # A written implementation responsibility is a promise, not code
            # evidence. The reviewer must inspect the entire actual Luau file.
            prompt = (
                "Independently audit ONE complete Roblox Luau server source. "
                "Check whether the OWNED BEHAVIOR below actually mutates the "
                "real server-owned state described. IMPORTANT: upgrades can "
                "legitimately persist a rank in ONE source and have their real "
                "effects consumed by ANOTHER server source. Independently "
                "inspect the provided on-disk DOWNSTREAM consumer source lines. "
                "A purchased crew rank that modifies combat damage or a ship "
                "rank that modifies actual voyage duration IS a real gameplay "
                "effect; do not demand duplicate physics or inventory state "
                "inside a purchasing module when a real connected consumer "
                "already implements the user-requested effect. However a rank counter "
                "or attribute alone does not implement speed, thrust, capacity "
                "or weapon damage. A static target alone is not NPC combat AI. "
                "Do not invent player-to-player trading from the word "
                "trade: a server broker is legitimate unless the ORIGINAL "
                "USER explicitly requests bilateral exchange. An architecture "
                "description is NOT permission to expand the user request. "
                "PlayerDataManager.GetState in a SERVER module is an "
                "authoritative persistence-backed state, NOT client-local "
                "state. A player attribute can mirror that authoritative "
                "state; that alone is not a defect. A broker trade which "
                "debits earned inventory and credits coins is real trading "
                "unless the original request specifically requires peers. "
                "A weapon module need NOT modify ship thrust; an alien combat "
                "module need NOT perform mineral extraction or colonization "
                "owned by another module. Do not assume absent cross-module "
                "code is required within THIS file. Reply 'implemented' only "
                "if THIS module's source-grounded responsibility is implemented by "
                "real effects, including downstream effects applied by another "
                "SERVER source provided here. The original user requested "
                "modular ship construction, not an obligatory mass/thrust/armor "
                "formula for every section: do not invent unrequested physics. "
                "Reply 'missing' with a real code quote "
                "if an essential promised effect is absent or substituted. "
                "Reply 'uncertain' only for dependencies that genuinely cannot "
                "be decided from this full source. Never claim Studio testing. "
                "Return ONLY JSON: verdict, file, quote, issue, repair. "
                "For implemented/missing, quote an EXACT substring of the file "
                "showing the relevant effect or its inadequate substitute.\n"
                + json.dumps({
                    "requirement_id": req_id,
                    "original_request": original[:2200],
                    "review_scope": "original user wording plus this module's action only; "
                    "AI-expanded implementation plan is NOT an acceptance authority",
                    "module": module.name,
                    "file": file_path,
                    "owned_behavior": responsibility[:1800],
                    "entire_source": source,
                    "downstream_server_consumers": downstream,
                }, ensure_ascii=False)
            )
            report["executed"] = True
            try:
                result = _review_with_bounded_truncation_recovery(
                    router=router, prompt=prompt, source=source,
                    file_path=file_path, requirement_id=req_id,
                    original=original, responsibility=responsibility,
                    downstream=downstream, retries=report["model_retries"],
                    schema={
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
                # Never let a malformed citation terminate gameplay review
                # before trying a bounded, numbered-line source lookup.
                try:
                    recovered = _recover_source_line(
                        source, file_path, req_id, result, router,
                    )
                except Exception as exc:
                    recovered = None
                    report["evidence_recovery"].append({
                        "requirement": req_id, "file": file_path,
                        "status": "failed",
                        "reason": type(exc).__name__ + ": " + str(exc)[:280],
                    })
                if recovered is None:
                    report["reason"] = (
                        req_id + ": source citation not recoverable in " + file_path
                    )
                    return report
                line, quote = recovered
                report["evidence_recovery"].append({
                    "requirement": req_id, "file": file_path,
                    "status": "grounded", "line": line,
                    "note": "Real line recovered; behavior still subject to tests",
                })
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
