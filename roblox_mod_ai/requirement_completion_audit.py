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
            # Reject/no-change clauses qualify the preceding server effect.
            if (result and re.match(
                    r"(?i)^(?:rejected|invalid|unauthorized)\s+requests?\b",
                    part)):
                result[-1]["behavior"] = (
                    result[-1]["behavior"] + "; " + part
                )[:900]
                continue
            key = re.sub(r"\s+", " ", part).casefold()
            if key not in seen:
                seen.add(key)
                result.append({"id": f"effect-{len(result)+1:02d}",
                               "behavior": part[:900]})
    return result



def _mask_luau_comments(source: str) -> str:
    """Blank comments without changing physical line positions.

    Handle inline comments and Lua's [=[ long comments, while leaving quoted
    strings and long string literals intact. The masked text has the same
    length/newline offsets as the source, so host line citations stay valid.
    """
    output = list(source)
    index = 0
    limit = len(source)
    while index < limit:
        ch = source[index]
        if ch in ("'", '"'):
            quote = ch
            index += 1
            while index < limit:
                if source[index] == "\\":
                    index += 2
                elif source[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            continue
        if ch == "[":
            opening = re.match(r"\[(=*)\[", source[index:])
            if opening:
                closing = "]" + opening.group(1) + "]"
                end = source.find(closing, index + opening.end())
                index = limit if end < 0 else end + len(closing)
                continue
        if source.startswith("--", index):
            opening = re.match(r"--\[(=*)\[", source[index:])
            if opening:
                closing = "]" + opening.group(1) + "]"
                end = source.find(closing, index + opening.end())
                stop = limit if end < 0 else end + len(closing)
            else:
                end = source.find("\n", index)
                stop = limit if end < 0 else end
            for offset in range(index, stop):
                if source[offset] != "\n":
                    output[offset] = " "
            index = stop
            continue
        index += 1
    return "".join(output)

def _real_source_quote(root: Path, path: str, quote: str) -> int:
    if not isinstance(quote, str) or not 6 <= len(quote) <= 320:
        return 0
    source = (root / path).read_text(encoding="utf-8")
    visible = _mask_luau_comments(source)
    index = visible.find(quote)
    return visible.count("\n", 0, index) + 1 if index >= 0 else 0


def _mask_noncode_luau_strings(source: str) -> str:
    """Hide string literals but retain quoted table keys in assignments.

    A diagnostic string containing currency code is not execution evidence.
    Keep offsets and line numbers unchanged for precise citations.
    """
    output = list(source)
    length = len(source)
    position = 0
    while position < length:
        ch = source[position]
        if ch in ("'", '"'):
            quote = ch
            start = position
            position += 1
            while position < length:
                if source[position] == "\\":
                    position = min(length, position + 2)
                elif source[position] == quote:
                    position += 1
                    break
                else:
                    position += 1
            prev = start - 1
            while prev >= 0 and source[prev].isspace():
                prev -= 1
            after = position
            while after < length and source[after].isspace():
                after += 1
            tail = after + 1
            while tail < length and source[tail].isspace():
                tail += 1
            is_index_key = (
                prev >= 0 and source[prev] == "["
                and after < length and source[after] == "]"
                and bool(re.match(
                    r"(?:\s*\.\s*\w+)*\s*(?:\+=|-=|=(?!=))",
                    source[tail:],
                ))
            )
            if not is_index_key:
                for i in range(start, position):
                    if source[i] != "\n":
                        output[i] = " "
            continue
        if ch == "[":
            opening = re.match(r"\[(=*)\[", source[position:])
            if opening:
                closing = "]" + opening.group(1) + "]"
                stop = source.find(closing, position + opening.end())
                end = length if stop < 0 else stop + len(closing)
                for i in range(position, end):
                    if source[i] != "\n":
                        output[i] = " "
                position = end
                continue
        position += 1
    return "".join(output)

def _source_scopes_for_effect(
    behavior: str, sources: dict[str, str], modules: list[Any],
) -> tuple[list[str], dict[str, str]]:
    """Host-select small, numbered, *real* source scopes; never fabricate code.

    Module responsibility comes from the authored architecture, but the actual
    on-disk file (not the plan) supplies every evidence line. All server owners
    stay in the catalog, while the two likeliest files get full readable
    context. This keeps local-model input bounded regardless of project size.
    """
    stop = {
        "after", "before", "player", "players", "owned", "server", "state",
        "change", "changes", "accepted", "request", "requests", "successful",
        "actual", "world", "real", "valid", "validated", "quantity", "the",
        "then", "their", "which", "with", "from", "into", "nothing", "does",
        "this", "that", "when", "only", "each", "rejected", "persisted",
    }
    terms = {
        w for w in re.findall(r"[a-z]{4,}", behavior.lower())
        if w not in stop
    }
    descriptions = {
        m.file_path: (str(getattr(m, "name", "")) + " "
                      + str(getattr(m, "description", ""))).lower()
        for m in modules if getattr(m, "file_path", None) in sources
    }

    def score(path: str) -> tuple[int, int]:
        description = descriptions.get(path, path.lower())
        name = path.rsplit("/", 1)[-1].lower()
        return (sum(3 for term in terms if term in name)
                + sum(1 for term in terms if term in description),
                -len(sources[path]))

    ranked = sorted(sources, key=lambda path: (score(path), path), reverse=True)
    chosen = ranked  # Each owner gets a bounded window; model sees at most 2 at once.
    # Numbered lines are extracted from actual bytes and checked again on
    # return. The path/id catalog prevents AI-generated filenames.
    numbered = {}
    for path in chosen:
        lines = sources[path].splitlines()
        if len(sources[path]) <= 11000:
            selected = range(len(lines))
        else:
            # Preserve physical line IDs; make windows around original source
            # identifiers and writes, not around model-authored quotes.
            scored = []
            for i, line in enumerate(lines):
                line_lower = line.lower()
                value = sum(1 for term in terms if term in line_lower)
                if re.search(r"(?:\+=|-=|\.[A-Za-z_]+\s*=|SetAttribute|GetState|UpdateAsync)", line):
                    value += 1
                scored.append((value, i))
            centers = [i for value, i in sorted(scored, reverse=True)
                       if value > 0][:45]
            selected = sorted({i for center in centers
                               for i in range(max(0, center - 2),
                                              min(len(lines), center + 3))})
        sample = "\n".join(f"{i + 1}: {lines[i]}" for i in selected)
        numbered[path] = sample[:14000]
    return ranked, numbered


def _normalize_single_effect_answer(
    raw: Any, ranked: list[str], sources: dict[str, str],
    numbered: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Require a real, executable physical line, even for model index output."""
    if not isinstance(raw, dict):
        return None
    verdict = raw.get("verdict")
    if verdict not in ("implemented", "missing", "out_of_scope"):
        return None
    if verdict == "out_of_scope":
        issue = raw.get("issue")
        if not isinstance(issue, str) or len(issue.strip()) < 12:
            return None
        return {"verdict": verdict, "file": "", "quote": "",
                "issue": issue[:350], "repair": ""}
    file_path = raw.get("file")
    if file_path is None:
        file_id = raw.get("file_id")
        if type(file_id) is not int or not 0 <= file_id < min(2, len(ranked)):
            return None
        file_path = ranked[file_id]
    if file_path not in sources:
        return None
    quote = raw.get("quote")
    if not isinstance(quote, str):
        number = raw.get("line")
        lines = sources[file_path].splitlines()
        if type(number) is not int or not 1 <= number <= len(lines):
            return None
        if numbered is not None:
            # The model must cite a line it actually saw; guessing a physical
            # number outside the bounded source window is not evidence.
            visible = set()
            for record in numbered.get(file_path, "").splitlines():
                label = record.partition(":")[0]
                if label.isdigit():
                    visible.add(int(label))
            if number not in visible:
                return None
        quote = lines[number - 1].strip()
        if verdict == "implemented" and not _is_effectful_source_line(
                sources[file_path], number):
            return None
    if (not 6 <= len(quote) <= 320
            or quote.lstrip().startswith("--")
            or quote.strip() in ("end", "else", "return false", "return nil")
            or quote not in sources[file_path]):
        return None
    issue = raw.get("issue", "none")
    repair = raw.get("repair", "none")
    if not isinstance(issue, str) or not isinstance(repair, str):
        return None
    if verdict == "implemented" and not _is_effectful_source_line(
            sources[file_path], _real_source_quote_in_text(
                sources[file_path], quote)):
        return None
    if verdict == "missing" and (len(issue.strip()) < 8
                                  or len(repair.strip()) < 8):
        return None
    return {"verdict": verdict, "file": file_path,
            "quote": quote, "issue": issue, "repair": repair}


_WRITE_TARGETS = re.compile(
    r"(?<!\w)([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]\n]+\])*)"
    r"\s*(?:\+=|-=|(?<![!<>=])=(?!=))"
)


def _distinct_state_writes(line: str) -> int:
    """Count distinct non-local assignments for a shared source line.

    Two promised effects may legitimately be implemented on one physical
    line if it actually writes two independent state targets. Repeated
    writes to one value never certify two different player effects.
    """
    if line.lstrip().startswith("--"):
        return 0
    statements = line.split(";")
    targets: set[str] = set()
    for statement in statements:
        stmt = statement.strip()
        if stmt.startswith(("local ", "for ", "if ", "elseif ")):
            continue
        targets.update(
            m.group(1) for m in _WRITE_TARGETS.finditer(stmt)
            if "." in m.group(1) or "[" in m.group(1)
        )
    return len(targets)


_EFFECTFUL_CALL = re.compile(
    r"(?:[:.])(?:SetAttribute|PivotTo|MoveTo|TakeDamage|Destroy|"
    r"UpdateAsync|SetAsync|Save|Persist|Credit|Debit|Award|"
    r"Grant|Transfer|Attach|Spawn|Insert|Remove|ApplyUpgrade)"
    r"\s*\(", re.I,
)


def _is_effectful_source_line(source: str, line_number: int) -> bool:
    """An executed mutation is required to certify a gameplay state effect.

    Arithmetic assignments to local temporaries, getters, and boolean
    comparisons do NOT prove world/player changes. An executable setter,
    mutator call, or non-local attribute/index assignment can be source
    evidence. It remains a necessary, not sufficient, semantic condition.
    """
    lines = source.splitlines()
    if not 1 <= line_number <= len(lines):
        return False
    line = _mask_noncode_luau_strings(
        _mask_luau_comments(lines[line_number - 1])
    ).strip()
    if not line or line.startswith(("--", "local ", "if ", "elseif ",
                                    "while ", "for ", "return ")):
        return False
    return _distinct_state_writes(line) > 0 or bool(
        _EFFECTFUL_CALL.search(line)
    )


def _real_source_quote_in_text(source: str, quote: str) -> int:
    if not isinstance(quote, str) or not quote:
        return 0
    visible = _mask_luau_comments(source)
    index = visible.find(quote)
    return visible.count("\n", 0, index) + 1 if index >= 0 else 0


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
        # Total generated source size is NOT the small model's context size.
        # Send fixed-size, owner-scoped windows below; do not reject a whole
        # experience merely because all modules together exceed 72 KB.
        if any(len(src) > 2_000_000 for src in actual_sources.values()):
            report["reason"] = req_id + ": unreasonable individual source size"
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
        # A complete batch is not usable when its quote is fabricated.
        # Independently recheck only those IDs rather than failing late.
        bad_batch_evidence_ids = set()
        for effect_id, entries in occurrences.items():
            if len(entries) != 1:
                continue
            entry = entries[0]
            verdict = entry.get("verdict")
            if verdict == "out_of_scope":
                if not isinstance(entry.get("issue"), str) or len(
                        entry["issue"].strip()) < 12:
                    bad_batch_evidence_ids.add(effect_id)
            elif verdict in ("implemented", "missing"):
                file_path = entry.get("file")
                if (not isinstance(file_path, str)
                        or file_path not in actual_sources
                        or not _real_source_quote(
                            root, file_path, entry.get("quote")
                        )):
                    bad_batch_evidence_ids.add(effect_id)
                elif verdict == "implemented" and not _is_effectful_source_line(
                        actual_sources[file_path],
                        _real_source_quote(root, file_path, entry["quote"])):
                    bad_batch_evidence_ids.add(effect_id)
            else:
                bad_batch_evidence_ids.add(effect_id)
        recover_ids = [
            row["id"] for row in obligations
            if len(occurrences[row["id"]]) != 1
            or row["id"] in bad_batch_evidence_ids
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
            ranked, numbered = _source_scopes_for_effect(
                effect["behavior"], actual_sources, proposal.modules,
            )
            # The host, not the model, must examine every owner before a
            # missing-effect verdict can be accepted. One top-2 search could
            # otherwise produce a false missing result when the state writer
            # lives in a lower-ranked server module.
            one = None
            missing_candidates = []
            for scope_start in range(0, len(ranked), 2):
                scope = ranked[scope_start:scope_start + 2]
                scoped_sources = {
                    path: actual_sources[path] for path in scope
                }
                path_ids = {path: i for i, path in enumerate(scope)}
                focused_sources = {
                    str(path_ids[path]): {
                        "path": path, "numbered_actual_source": numbered[path],
                    } for path in scope
                }
                single_prompt = (
                    "Audit exactly ONE Roblox effect. Return compact JSON. "
                    "Only the CURRENT OWNER FILES below are visible. Use "
                    "file_id (0 or 1) and the physical source line number, "
                    "never invent file paths or copy code. Check whether the "
                    "promised state transition is actually implemented. "
                    "Do not accept a UI/Remote alone as proof. Missing means "
                    "the effect is NOT evidenced IN THESE FILES; other owners "
                    "are checked separately by the host. Return issue and "
                    "repair when missing; do not claim Studio execution.\\n"
                    + json.dumps({
                        "effect": effect["behavior"],
                        "original_request": original[:900],
                        "current_owner_sources": focused_sources,
                    }, ensure_ascii=False)
                )
                single_schema = {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": [
                            "implemented", "missing", "out_of_scope",
                        ]},
                        "file_id": {"type": "integer"},
                        "line": {"type": "integer"},
                        "issue": {"type": "string"},
                        "repair": {"type": "string"},
                    },
                    "required": ["verdict", "file_id", "line"],
                    "additionalProperties": False,
                }
                scoped_answer = None
                for attempt in range(2):
                    try:
                        raw = router.complete_json(
                            prompt=(single_prompt if attempt == 0 else
                                    "Recheck ONE effect. Respond with a tiny "
                                    "JSON object verdict/file_id/line and "
                                    "issue/repair if missing. Use only the "
                                    "numbered physical source below.\\n"
                                    + json.dumps({
                                        "effect": effect["behavior"],
                                        "current_owner_sources": focused_sources,
                                    }, ensure_ascii=False)),
                            role="analyzer", temperature=0,
                            max_tokens=420 if attempt == 0 else 650,
                            json_schema=single_schema,
                        )
                    except Exception as exc:
                        raw = None
                        report.setdefault("recovery", []).append({
                            "requirement_id": req_id, "effect_id": effect_id,
                            "stage": "single_effect", "attempt": attempt + 1,
                            "owner_window": scope_start // 2 + 1,
                            "status": "model_error",
                            "error": (
                                type(exc).__name__ + ": " + str(exc)
                            )[:250],
                        })
                    normalized = _normalize_single_effect_answer(
                        raw, scope, scoped_sources,
                        {path: numbered[path] for path in scope},
                    )
                    if normalized is not None:
                        scoped_answer = normalized
                        break
                    report.setdefault("recovery", []).append({
                        "requirement_id": req_id, "effect_id": effect_id,
                        "stage": "single_effect", "attempt": attempt + 1,
                        "owner_window": scope_start // 2 + 1,
                        "status": "invalid_evidence",
                        "response_type": type(raw).__name__,
                        "response_keys": sorted(map(str, raw.keys()))
                                         if isinstance(raw, dict) else [],
                    })
                if scoped_answer is None:
                    evidence_reason = (
                        "ungrounded batch evidence; "
                        if effect_id in bad_batch_evidence_ids else ""
                    )
                    report["reason"] = (
                        req_id + ": incomplete independent effect checks; "
                        + evidence_reason + effect_id
                        + " could not provide grounded evidence in owner window "
                        + str(scope_start // 2 + 1)
                    )
                    return report
                if scoped_answer["verdict"] == "missing":
                    missing_candidates.append(scoped_answer)
                    continue
                one = scoped_answer
                break
            if one is None:
                if len(missing_candidates) != (len(ranked) + 1) // 2:
                    report["reason"] = (
                        req_id + ": owner coverage incomplete for " + effect_id
                    )
                    return report
                one = missing_candidates[0]
            report.setdefault("recovery", []).append({
                "requirement_id": req_id, "effect_id": effect_id,
                "stage": "single_effect", "status": "recovered",
                "owner_windows_checked": (
                    (len(ranked) + 1) // 2 if one["verdict"] == "missing"
                    else (scope_start // 2 + 1)
                ),
            })
            occurrences[effect_id] = [{"id": effect_id, **one}]
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
                        "Find user-requested gameplay ACTIONS omitted from the "
                        "candidate effect list. Do not judge or quote code in "
                        "this step. Original request is authoritative. "
                        "Return only JSON with missing_actions as a list of "
                        "omitted behaviors, or [] when none.\\n"
                        + json.dumps({
                            "original_user_request": original[:2400],
                            "candidate_effects": [
                                item["behavior"] for item in obligations
                            ],
                        }, ensure_ascii=False)
                    ),
                    role="analyzer", temperature=0, max_tokens=1100,
                    json_schema={
                        "type": "object",
                        "properties": {
                            "missing_actions": {
                                "type": "array", "maxItems": 12,
                                "items": {"type": "string"},
                            },
                            "extra_missing": {
                                "type": "array", "maxItems": 12,
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["missing_actions"],
                        "additionalProperties": False,
                    },
                )
                if isinstance(extra_result, dict):
                    if ("missing_actions" not in extra_result
                            and "extra_missing" not in extra_result):
                        report["reason"] = (
                            req_id + ": missing original-request scope review"
                        )
                        return report
                    omissions = extra_result.get("missing_actions", [])
                    if not isinstance(omissions, list) or any(
                            not isinstance(item, str) for item in omissions):
                        omissions = None
                    if omissions:
                        report["unplanned_actions"] = omissions[:12]
                        report["reason"] = (
                            req_id + ": original request omitted by authored "
                            "effect plan: " + "; ".join(omissions[:3])[:400]
                        )
                        return report
                    fresh_extras = extra_result.get("extra_missing")
                    if fresh_extras is None and omissions == []:
                        fresh_extras = []
                else:
                    fresh_extras = None
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
        implemented_evidence: dict[tuple[str, int], set[str]] = {}
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
                # These are planned original-user requirements. The model
                # cannot quietly discard one as out of scope.
                report["reason"] = (
                    req_id + ": plan scope conflict; proposed effect "
                    + str(entry.get("id")) + " rejected as out_of_scope"
                )
                return report
            if not isinstance(file_path, str) or file_path not in server_paths:
                report["reason"] = req_id + ": effect cites unauthorized server"
                return report
            line = _real_source_quote(root, file_path, entry.get("quote"))
            if not line:
                report["reason"] = req_id + ": ungrounded effect quote in " + file_path
                return report
            if verdict == "implemented":
                if not _is_effectful_source_line(actual_sources[file_path], line):
                    report["reason"] = (
                        req_id + ": non-mutating evidence for "
                        + str(entry.get("id")) + " at " + file_path
                    )
                    return report
                # Independent state transitions need independent executable
                # evidence; a single write cannot certify multiple effects.
                key = (file_path, line)
                bound_ids = implemented_evidence.setdefault(key, set())
                bound_ids.add(str(entry.get("id")))
                if len(bound_ids) > 1:
                    actual_line = actual_sources[file_path].splitlines()[line - 1]
                    if _distinct_state_writes(actual_line) < len(bound_ids):
                        report["reason"] = (
                            req_id + ": shared evidence for independent effects: "
                            + ", ".join(sorted(bound_ids))
                            + " in " + file_path + ":" + str(line)
                        )
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
