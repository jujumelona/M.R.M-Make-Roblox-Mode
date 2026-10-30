"""Diagnostic-directed repair for any host-routed Luau action.

The compiler owns the real module shell, service ABI and world manifest.  An
LLM may repair its BODY, but must not invent source authority or weaken a
validator.  This module converts observed errors into a bounded, *generic*
repair task, independent of the user's game genre and object names.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


def _error_codes(attempt: dict[str, Any]) -> tuple[str, ...]:
    raw = " ".join(str(x) for x in attempt.get("diagnostics", []))
    return tuple(sorted(set(re.findall(
        r"\b(?:WORLD_[A-Z_]+|DEPENDENCY_[A-Z_]+|"
        r"TYPED_[A-Z_]+|SELENE_[A-Z_]+|"
        r"ROBLOX_[A-Z_]+|SCOPED_[A-Z_]+|"
        r"AUTHORITY_[A-Z_]+|MODEL_[A-Z_]+|"
        r"[A-Z_]+_MISSING)\b", raw
    ))))


def attempt_fingerprint(body: str) -> str:
    """Exact model output identity; never treat a changed semantic body as equal."""
    return hashlib.sha256((body or "").strip().encode("utf-8")).hexdigest()


def scoped_action_retry_prompt(attempts: list[dict[str, Any]]) -> str:
    """Build repairs from *all actual attempts*, not a truncated final suffix.

    The former caller concatenated 1,100 characters of errors, then silently
    sliced the entire message to its last 650 characters.  This removed the
    first (often decisive) type/ABI error and made three retries identical.
    """
    if not attempts:
        return ""
    last = attempts[-1]
    history = attempts[-3:]
    previous = str(last.get("candidate") or "")
    raw_errors = [
        str(err) for row in history for err in row.get("diagnostics", [])
    ]
    codes = sorted(set(code for row in history for code in _error_codes(row)))
    hashes = [attempt_fingerprint(str(row.get("candidate") or ""))
              for row in history if str(row.get("candidate") or "").strip()]
    unchanged = len(hashes) > 1 and len(set(hashes)) == 1
    same_failure = (len(history) > 1 and
                    len(set(_error_codes(row) for row in history)) == 1)

    rules = [
        "REPAIR THIS ONE ACTION BODY, preserving its original intended effect.",
        "Do not rewrite the host function, create a new Remote, or discard the gameplay.",
        "Resolve observed diagnostics using only the real injected service API, "
        "the materialized world manifest and the declared typed input schema.",
        "Never manufacture ownership, price, saved state, item or world actor "
        "merely to satisfy a validator. No placeholder return-true path.",
    ]
    if any(code.startswith("WORLD_") for code in codes):
        rules.append(
            "WORLD REPAIR: inspect the EXACT authorized name and Roblox class "
            "in the world ABI above. A Part is not a Model. If a necessary actor "
            "is absent, do not substitute an unrelated Part; that is an upstream "
            "architecture dependency, not a typo."
        )
    if any(code.startswith("DEPENDENCY_") for code in codes):
        rules.append(
            "SERVICE REPAIR: use only exported methods from the inspected peer ABI. "
            "Do not create imagined services, and do not call another handler's "
            "Remote ingress as a shared transaction."
        )
    if any(code.startswith("SELENE_") for code in codes):
        rules.append(
            "SCOPE REPAIR: define each local before use, use the authenticated "
            "player argument, and obtain mutable state through the proven "
            "PlayerDataManager.GetState interface when required."
        )
    if any(code.startswith("TYPED_") for code in codes):
        rules.append(
            "INPUT REPAIR: access only named, already validated fields and "
            "implement every declared effect; never use positional indexes "
            "with a typed action payload."
        )
    if unchanged or same_failure:
        rules.append(
            "REPEATED FAILURE: do NOT repeat the previous construction. "
            "Re-derive the body from four executable steps: verify actual "
            "prerequisites, read authoritative inputs/state, execute the "
            "requested mutation, then return success only after mutation. "
            "Use a different valid control flow, NOT different variable names."
        )
    return (
        "\n\nDIAGNOSTIC-DIRECTED RECOVERY (the preceding code was rejected):\n"
        + "\n".join("- " + rule for rule in rules)
        + "\nObserved error categories: " + (", ".join(codes) or "(uncategorized)")
        + "\nEXACT VALIDATOR ERRORS (chronological):\n"
        + "\n".join(f"- {item[:950]}" for item in raw_errors[-6:])
        + "\nLAST REJECTED BODY (diagnostic context, not authorized code):\n"
        + previous[:2400]
        + "\nReturn ONLY corrected executable BODY statements.\n"
    )
