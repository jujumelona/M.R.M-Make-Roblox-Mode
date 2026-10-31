"""Prompt-invariant attestation of host-compiled gameplay transactions.

Verifies executable source against the structured contract's deterministic
compiler. It never dispatches by prompt words, item names, or game genre.
This is source validation only, not Studio runtime verification.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .host_atomic_effect import render_atomic_server


def _luau_tokens(source: str) -> tuple[str, ...]:
    """Tokenize Luau while ignoring whitespace and comments (not literals)."""
    result: list[str] = []
    pos = 0
    length = len(source)
    while pos < length:
        ch = source[pos]
        if ch.isspace():
            pos += 1
            continue
        if source.startswith("--", pos):
            opening = re.match(r"--\[(=*)\[", source[pos:])
            if opening:
                close = "]" + opening.group(1) + "]"
                end = source.find(close, pos + opening.end())
                pos = length if end == -1 else end + len(close)
            else:
                end = source.find("\n", pos)
                pos = length if end == -1 else end + 1
            continue
        if ch in ("'", '"'):
            start = pos
            pos += 1
            while pos < length:
                if source[pos] == "\\":
                    pos += 2
                elif source[pos] == ch:
                    pos += 1
                    break
                else:
                    pos += 1
            result.append(source[start:pos])
            continue
        if ch == "[":
            opening = re.match(r"\[(=*)\[", source[pos:])
            if opening:
                close = "]" + opening.group(1) + "]"
                end = source.find(close, pos + opening.end())
                stop = length if end == -1 else end + len(close)
                result.append(source[pos:stop])
                pos = stop
                continue
        word = re.match(r"[A-Za-z_][A-Za-z_0-9]*", source[pos:])
        if word:
            result.append(word.group())
            pos += len(word.group())
            continue
        number = re.match(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", source[pos:])
        if number:
            result.append(number.group())
            pos += len(number.group())
            continue
        op = next((v for v in ("...", "..=", "==", "~=", "<=", ">=",
                              "+=", "-=", "*=", "/=", "//", "..")
                   if source.startswith(v, pos)), None)
        if op:
            result.append(op)
            pos += len(op)
        else:
            result.append(ch)
            pos += 1
    return tuple(result)


def verify_compiled_effect_sources(
    proposal: Any, source_root: Path,
) -> dict[str, Any]:
    """Fail closed if declared executable actions are absent or altered."""
    root = Path(source_root)
    game_design = getattr(proposal, "game_design", {}) or {}
    design = (game_design.get("dynamic_design", {}) or {}
              if isinstance(game_design, dict) else None)
    report: dict[str, Any] = {
        "schema": "rmm/compiled-effect-source-attestation-v1",
        "executed": True, "passed": False, "checked": [],
        "failures": [], "scope": "source_only_not_studio",
    }
    if not isinstance(design, dict):
        report["failures"].append("invalid_dynamic_design")
        return report
    # An explicitly malformed or null roster must NOT turn into an empty
    # roster via 'or {}'. That used to produce a false not_applicable PASS.
    actions = design.get("host_executable_actions", {})
    routes = design.get("host_actions", {})
    if not isinstance(actions, dict) or not isinstance(routes, dict):
        report["failures"].append("invalid_executable_action_roster")
        return report
    modules = list(getattr(proposal, "modules", ()) or ())
    seen_servers: set[str] = set()
    for remote, program in sorted(actions.items(), key=lambda item: str(item[0])):
        if not isinstance(remote, str) or not isinstance(program, dict):
            report["failures"].append("invalid_action_entry")
            continue
        route = routes.get(remote)
        owner = route.get("service") if isinstance(route, dict) else None
        matches = [m for m in modules if m.name == owner]
        if len(matches) != 1:
            report["failures"].append("missing_or_ambiguous_owner:" + remote)
            continue
        module = matches[0]
        path = module.file_path
        if path in seen_servers:
            report["failures"].append("multiple_programs_same_owner:" + path)
            continue
        seen_servers.add(path)
        if (not isinstance(path, str)
                or not path.startswith("src/server/")
                or "\\" in path
                or ".." in Path(path).parts
                or Path(path).is_absolute()
                or not path.endswith(".luau")):
            report["failures"].append("invalid_server_path:" + remote)
            continue
        try:
            expected = render_atomic_server(module, proposal)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            report["failures"].append(
                "invalid_effect_contract:" + remote + ":"
                + type(exc).__name__ + ":" + str(exc)[:180]
            )
            continue
        if not expected:
            report["failures"].append("unsupported_executable_effect:" + remote)
            continue
        file = root / path
        if not file.is_file():
            report["failures"].append("missing_generated_source:" + path)
            continue
        try:
            actual = file.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            report["failures"].append("unreadable_generated_source:" + path)
            continue
        matching = _luau_tokens(expected) == _luau_tokens(actual)
        report["checked"].append({
            "remote": remote, "file": path, "matched": matching,
            "actual_sha256": hashlib.sha256(actual.encode()).hexdigest(),
            "contract_effect_count": (
                len(program.get("changes") or [])
                if program.get("schema") == "rmm/transaction-effect-v1"
                else 1
            ),
        })
        if not matching:
            report["failures"].append("compiled_effect_source_mismatch:" + path)
    report["passed"] = not report["failures"]
    report["declared_action_count"] = len(actions)
    report["status"] = (
        "failed" if report["failures"]
        else "verified" if actions else "not_applicable"
    )
    return report
