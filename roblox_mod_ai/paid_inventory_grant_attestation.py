"""Conservative source attestation of paid physical inventory entitlement.

Generic Roblox protocol, independent of any game/genre/target item name:
an authenticated purchase path must grant a real Tool, debit owned funds,
persist its inventory entitlement, and restore the Tool from saved inventory.

This is a source-only proof. It cannot attest engine execution or DataStore
durability and must fail closed for an unknown generator pattern.
"""
from __future__ import annotations

import re
from typing import Any


def _visible(source: str) -> str:
    # Preserve physical line numbers; comments cannot provide evidence.
    # Quoted inline comment tokens occur in this protocol only in strings;
    # ignoring those strings is sufficient for the host-emitted grammar.
    return "\n".join(
        "" if line.lstrip().startswith("--") else
        re.sub(r"\s+--[^\n]*$", "", line)
        for line in source.splitlines()
    )


def attest_paid_inventory_grant(
    behavior: str, sources: dict[str, str], modules: list[Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not (
        re.search(r"\binventor\w*\b", behavior, re.I)
        and re.search(
            r"\b(?:add|grant|receiv|acquir|purchas|obtain|stor|record|"
            r"deliver|register)\w*\b", behavior, re.I
        )
        and re.search(
            r"\b(?:item|weapon|tool|equipment|upgrade|gear|product|reward)\w*\b",
            behavior, re.I
        )
    ):
        return None, {"reason": "not_a_paid_inventory_grant_effect"}

    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for path, raw in sorted(sources.items()):
        if not path.startswith("src/server/"):
            continue
        code = _visible(raw)
        def has(regex: str, scope: str = code) -> bool:
            return re.search(regex, scope, re.M | re.S) is not None
        declarations = (
            r"(?m)^\s*local\s+TARGET\s*=\s*['\"][^'\"]+['\"]",
            r"(?m)^\s*local\s+OWNED\s*=\s*true\b",
            r"(?m)^\s*local\s+ACQUIRE_FIRST\s*=\s*true\b",
            r"(?m)^\s*local\s+GRANT_TOOL\s*=\s*true\b",
            r"(?m)^\s*local\s+function\s+ensureOwnedTool\(\s*player\s*\)",
            r'Instance\.new\(\s*["\x27]Tool["\x27]\s*\)',
            r"\btool\.Name\s*=\s*TARGET\b",
            r"\btool\.Parent\s*=\s*backpack\b",
            r'local\s+function\s+restoreIfOwned\(\s*\)',
            r"player\.CharacterAdded:Connect\(\s*function\(\s*\)",
            r"task\.defer\(\s*restoreIfOwned\s*\)",
        )
        if not all(has(p) for p in declarations):
            continue

        handler = re.search(
            r"(?m)^function\s+Service\.handleAction\s*\(", code
        )
        if not handler:
            continue
        body = code[handler.start():]
        bindings = re.search(
            r'(?m)^\s*local\s+(?P<inv>\w+)\s*=\s*'
            r'services\.PlayerDataManager\.GetState\(\s*player\s*,'
            r'\s*["\x27]RMMInventory["\x27]\s*\)', body,
        )
        if not bindings:
            continue
        inv = re.escape(bindings.group("inv"))
        if not all(has(p, body) for p in (
            r"player\.Parent\s*~=\s*Players",
            r'select\(\s*["\x27]#["\x27]\s*,\s*\.\.\.\s*\)\s*~=\s*1',
            r"\(\s*\.\.\.\s*\)\s*~=\s*TARGET\b",
            r"\blocal\s+acquiring\s*=\s*OWNED\s+and\s+ACQUIRE_FIRST\s+and\s+not\s+acquired",
            r"coins\.Value\s*<\s*COST",
            r"if\s+acquiring\s+and\s+GRANT_TOOL\s+then",
            r"if\s+not\s+created\s+or\s+not\s+granted\s+then",
            r"return\s*\{\s*success\s*=\s*false\s*,\s*reason\s*=\s*"
            r'["\x27]weapon_grant_failed["\x27]',
            r"\bentitlements\s*=\s*services\.PlayerDataManager\.GetState"
            r"\(\s*player\s*,\s*['\"]RMMTradeEntitlements['\"]\s*\)",
            r"\bif\s+acquiring\s+then",
            r"return\s*\{\s*success\s*=\s*true\s*,\s*acquired\s*=\s*true",
        )):
            continue

        grant = re.search(
            r"(?m)^\s*local\s+created\s*,\s*granted\s*=\s*"
            r"pcall\(\s*ensureOwnedTool\s*,\s*player\s*\)", body,
        )
        debit = re.search(
            r"(?m)^\s*coins\.Value\s*-=\s*COST\b", body,
        )
        owned = re.search(
            r"(?m)^\s*" + inv + r"\.items\s*\[\s*TARGET\s*\]\s*=\s*1\b",
            body,
        )
        entitlement = re.search(
            r"(?m)^\s*entitlements\s*\[\s*script\.Name\s*\.\."
            r'\s*["\x27]/["\x27]\s*\.\.\s*TARGET\s*\]\s*=\s*\{',
            body,
        )
        approved = re.search(
            r"(?m)^\s*return\s*\{\s*success\s*=\s*true\s*,"
            r"\s*acquired\s*=\s*true", body,
        )
        if not all((grant, debit, owned, entitlement, approved)):
            continue
        # Grant happens BEFORE payment and persistent inventory credit.
        if not (grant.start() < debit.start() < owned.start()
                < entitlement.start() < approved.start()):
            continue
        # Reject an action that can yield between the paid state writes.
        if has(r"\b(?:task\.wait|WaitForChild|Heartbeat:Wait)\s*\(",
               body[debit.start():approved.start()]):
            continue
        # Grant failure must return before debit. An unrelated failure
        # message elsewhere is not a guard over the actual pcall.
        refusal = re.search(
            r"if\s+not\s+created\s+or\s+not\s+granted\s+then\s*"
            r"return\s*\{\s*success\s*=\s*false\s*,\s*reason\s*=\s*"
            r'["\x27]weapon_grant_failed["\x27]\s*\}',
            body[grant.end():debit.start()],
        )
        if not refusal:
            continue
        if not has(
            r'(?m)^\s*if\s+' + inv +
            r'\.items\s*==\s*nil\s+then\s+' + inv +
            r'\.items\s*=\s*\{\s*\}\s*end', body[:owned.start()]
        ):
            continue

        # The restored Tool must read the SAME persisted inventory
        # namespace and key; an unconditional cosmetic respawn Tool is not
        # evidence of owned gear or successful purchase.
        restore = code[
            code.find("local function restoreIfOwned()"):
            handler.start()
        ]
        if not all(has(p, restore) for p in (
            r"GetState\(\s*player\s*,\s*['\"]RMMInventory['\"]\s*\)",
            r"\.items\s*\[\s*TARGET\s*\]",
            r"\bensureOwnedTool\(\s*player\s*\)",
        )):
            continue
        tool_parent = re.search(
            r"(?m)^\s*tool\.Parent\s*=\s*backpack\b", code[:handler.start()]
        )
        if not tool_parent:
            continue
        # Explicit source lines, never synthesized or model-quoted.
        original_lines = raw.splitlines()
        def citation(absolute: int) -> dict[str, Any] | None:
            line = code.count("\n", 0, absolute) + 1
            if not 1 <= line <= len(original_lines):
                return None
            quote = original_lines[line - 1].strip()
            if not quote or quote.startswith("--"):
                return None
            return {"line": line, "quote": quote}
        points = [
            citation(tool_parent.start()),
            citation(handler.start() + debit.start()),
            citation(handler.start() + owned.start()),
            citation(handler.start() + entitlement.start()),
        ]
        if not all(points) or len({p["line"] for p in points}) != 4:
            continue
        candidates.append((path, points))

    if len(candidates) != 1:
        return None, {
            "reason": "no_unique_paid_inventory_grant_path",
            "candidate_count": len(candidates), "status": "unverified",
        }
    path, proof = candidates[0]
    return {
        "verdict": "implemented", "file": path,
        "line": proof[2]["line"], "quote": proof[2]["quote"],
        "proof_lines": proof, "issue": "none", "repair": "none",
    }, {
        "status": "deterministic_paid_inventory_grant",
        "method": "predebit_tool_grant_to_saved_inventory_and_respawn",
        "source_only": True, "proof_lines": len(proof),
    }
