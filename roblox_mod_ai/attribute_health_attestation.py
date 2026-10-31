"""Conservative source-only proof for server-owned entity health held in Attributes.

Roblox combat entities may be Parts with authoritative numeric health
Attributes; a Humanoid is not a necessary representation. This checker does
not execute Studio and cannot prove hit registration, replication or gameplay.
It proves a connected read/validate/debit/write path plus a health-dependent
server behavior. Unknown shapes are deliberately left for independent review.
"""
from __future__ import annotations

import re
from typing import Any


def attest_attribute_health(source: str, role: str) -> dict[str, Any] | None:
    """Prove a particular server-owned Part's health is reduced by a hit."""
    if not re.search(r"\b(?:health|damage|attack|combat|hit|체력|공격|전투)\b", role, re.I):
        return None
    if not re.search(r"(?m)^function\s+Service\.start\s*\(", source):
        return None
    match = re.search(r"(?m)^function\s+Service\.handleAction\s*\(", source)
    if match is None:
        return None
    prelude = source[:match.start()]
    body = source[match.start():]
    # Any evidence must belong to the real server action rather than a
    # passive health-display loop or an unrelated humanoid being damaged.
    end = re.search(r"(?m)^end\s*\nreturn\s+Service\b", body)
    if end is None:
        return None
    body = body[:end.start()]
    if not re.search(r"\bplayer\.Parent\s*~=\s*Players\b", body):
        return None
    if not re.search(r"\breturn\s*\{\s*success\s*=\s*false\b", body):
        return None
    if not re.search(r"\breturn\s*\{\s*success\s*=\s*true\b", body):
        return None
    for read in re.finditer(
        r"\blocal\s+(\w+)\s*=\s*(\w+):GetAttribute\(\s*([\"'])([^\"']+)\3\s*\)",
        body,
    ):
        hp, target, _, attribute = read.groups()
        if not re.search(
            r"\blocal\s+" + re.escape(target)
            + r"\s*=\s*workspace:FindFirstChild\s*\(", body,
        ):
            continue
        if not re.search(
            r"\b" + re.escape(target) + r":IsA\(\s*[\"']BasePart[\"']\s*\)",
            body,
        ):
            continue
        if not re.search(
            r"\btype\(\s*" + re.escape(hp) + r"\s*\)\s*~=\s*[\"']number[\"']",
            body,
        ):
            continue
        if not re.search(r"\b" + re.escape(hp) + r"\s*<=\s*0", body):
            continue
        if not re.search(
            r"\b(?:root|characterRoot|attackerRoot)\.Position\s*-\s*"
            + re.escape(target) + r"\.Position\)\.Magnitude\s*>\s*\d+",
            body,
        ):
            continue
        compute = re.search(
            r"\blocal\s+(\w+)\s*=\s*math\.max\(\s*0\s*,\s*"
            + re.escape(hp) + r"\s*-\s*(\w+)\s*\)", body[read.end():],
        )
        if compute is None:
            continue
        remaining, damage = compute.groups()
        if not re.search(r"\blocal\s+" + re.escape(damage) + r"\s*=", body):
            continue
        damage_assignment = re.search(
            r"\blocal\s+" + re.escape(damage) + r"\s*=\s*([^\n]+)", body,
        )
        if damage_assignment is None or re.search(
            r"\b(?:args|actionArgs|payload|clientDamage|requestedDamage)\b",
            damage_assignment.group(1),
        ):
            continue
        write = re.search(
            r"\b" + re.escape(target) + r":SetAttribute\(\s*[\"']"
            + re.escape(attribute) + r"[\"']\s*,\s*"
            + re.escape(remaining) + r"\s*\)", body,
        )
        if write is None or write.start() <= read.start() + compute.start():
            continue
        between = body[read.start():write.start()]
        if re.search(r"\b(?:task\.wait|wait|UpdateAsync|SetAsync|InvokeServer|InvokeClient)\s*\(", between):
            continue
        # Require a real server-side consumer of the *same* health key,
        # including death/respawn logic, to exclude a decorative attribute.
        if not (
            re.search(
                r":GetAttribute\(\s*[\"']" + re.escape(attribute)
                + r"[\"']\s*\)", prelude,
            )
            or re.search(
                r"\bif\s+" + re.escape(remaining)
                + r"\s*==\s*0\b", body[write.end():],
            )
        ):
            continue
        # The value must be initialized on the actual source-owned world
        # object before player actions (not only in the action itself).
        if not re.search(
            r":SetAttribute\(\s*[\"']" + re.escape(attribute)
            + r"[\"']\s*,\s*\d+\s*\)", prelude,
        ):
            continue
        line = source[:match.start() + write.start()].count("\n") + 1
        return {
            "line": line,
            "quote": write.group(0),
            "method": "server_owned_attribute_health_transition",
            "scope": "static_source_only_no_roblox_studio",
            "attribute": attribute,
            "target_binding": target,
            "damage_binding": damage,
        }
    return None
