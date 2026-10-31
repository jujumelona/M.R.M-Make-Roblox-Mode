"""Source-only attestation of a guarded, asynchronous vehicle transit.

A single PivotTo statement does not prove a trip. Verify that the identical
server-owned vehicle is obtained from the builder, authorized, advanced along
a server-selected destination in an active timed coroutine, and that all
seated occupants are tracked until the arrival state is committed.

This cannot prove actual Roblox engine physics or Studio playtests.
Unknown code patterns deliberately remain unverified.
"""
from __future__ import annotations

import re
from typing import Any


def _executable(source: str) -> str:
    # Prevent comments from satisfying mandatory state/ownership checks.
    return "\n".join(line.split("--", 1)[0] for line in source.splitlines())


def attest_async_vehicle_transit(
    effect: str, sources: dict[str, str], modules: list[Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    # The role and effect route candidates; the proof below must establish
    # concrete physical state transitions and occupant preservation.
    if not re.search(
        r"\b(?:vehicle|craft|ship|spaceship|spacecraft|rocket|train|"
        r"aircraft|bus|boat|ferry)\b", effect, re.I,
    ) or not re.search(
        r"\b(?:launch|travel|move|depart|transport|orbit|arriv|"
        r"relocat|flight|voyage)\w*\b", effect, re.I,
    ):
        return None, {"reason": "not_a_vehicle_transit_effect"}
    options: list[tuple[str, list[dict[str, Any]]]] = []
    for path, raw in sorted(sources.items()):
        if not path.startswith("src/server/"):
            continue
        code = _executable(raw)
        action_match = re.search(
            r"(?m)^function\s+Service\.handleAction\s*\(", code,
        )
        if action_match is None:
            continue
        body = code[action_match.start():]
        def has(pattern: str) -> bool:
            return re.search(pattern, body, re.M | re.S) is not None
        # The client can only request an enum action; never a target or
        # movement duration. Any corresponding client-chosen destination
        # fails closed instead of being declared fully verified.
        guards = (
            r"player\.Parent\s*~=\s*Players",
            r'select\(\s*"#"\s*,\s*\.\.\.\s*\)\s*~=\s*1',
            r"(?m)^\s*local\s+(\w+)\s*=\s*services\.\w+\.GetOwnedActor\(\s*player\s*\)",
            r":GetAttribute\(\s*[\"']OwnerUserId[\"']\s*\)\s*~=\s*player\.UserId",
            r"(?m)^\s*local\s+\w+\s*=\s*workspace:FindFirstChild\(\s*\w+\s*\)",
            r"(?m)^\s*local\s+(\w+)\s*=\s*\w+\.CFrame\s*\*",
            r"(?m)^\s*local\s+(\w+)\s*=\s*\w+:GetPivot\(\s*\)",
            r"(?m)^\s*local\s+(\w+)\s*=\s*\w+\.PlayerDataManager\.GetState\(",
            r"(?m)^\s*local\s+\w+\s*=\s*\{\s*\}",
            r":GetDescendants\(\)",
            r'part:IsA\(\s*["\x27]Seat["\x27]\s*\)',
            r'part:IsA\(\s*["\x27]VehicleSeat["\x27]\s*\)',
            r"(?m)^\s*local\s+function\s+occupantsIntact\(\s*\)",
            r"for\s+_,\s*rider\s+in\s+occupiedSeats\s+do",
            r"rider\.seat\.Occupant\s*~=\s*rider\.humanoid",
            r"if\s+#occupiedSeats\s*==\s*0",
            r"task\.spawn\(\s*function\(\s*\)",
            r"while\s+inFlight\[player\]\s*==\s*flightToken",
            r"and\s+seat\.Occupant\s*==\s*humanoid",
            r"rider\.humanoid\.Health\s*<=\s*0",
            r"rider\.humanoid\.Parent\s*==\s*nil",
            r"destination:IsA\(\s*[\\\"']BasePart[\\\"']\s*\)",
            r"and\s+occupantsIntact\(\s*\)\s*do",
            r"math\.clamp\(\s*\(\s*os\.clock\(\s*\)\s*-\s*\w+\s*\)\s*/\s*duration",
            r"if\s+alpha\s*>=\s*1\s+then\s+completed\s*=\s*true",
            r"RunService\.Heartbeat:Wait\(\s*\)",
            r"if\s+inFlight\[player\]\s*~=\s*flightToken",
            r"finalState\s*=\s*completed\s+and",
            r'player:SetAttribute\(\s*["\x27]RMMFlightState["\x27]\s*,\s*finalState',
            r"return\s*\{\s*success\s*=\s*true",
            r"return\s*\{\s*success\s*=\s*false",
        )
        if any(not has(g) for g in guards):
            continue
        vehicle = re.search(
            r"(?m)^\s*local\s+(\w+)\s*=\s*services\.\w+\.GetOwnedActor"
            r"\(\s*player\s*\)", body,
        )
        start = re.search(
            r"(?m)^\s*local\s+(\w+)\s*=\s*"
            + re.escape(vehicle.group(1)) + r":GetPivot\(\s*\)", body,
        ) if vehicle else None
        if not start:
            continue
        pivot_pattern = (
            r"(?m)^\s*" + re.escape(vehicle.group(1))
            + r":PivotTo\(\s*" + re.escape(start.group(1))
            + r":Lerp\(\s*(\w+)\s*,\s*alpha\s*\)\s*\)"
        )
        pivot = re.search(pivot_pattern, body)
        if pivot is None:
            continue
        target = pivot.group(1)
        # The destination must be a server-owned world CFrame, not a client
        # argument or a made-up second vehicle.
        if not re.search(r"(?m)^\s*" + re.escape(target)
                         + r"\s*=\s*(\w+)\s*$", body):
            continue
        assigned = re.search(r"(?m)^\s*" + re.escape(target)
                             + r"\s*=\s*(\w+)\s*$", body)
        server_dest = assigned.group(1)
        if not re.search(
            r"(?m)^\s*local\s+" + re.escape(server_dest)
            + r"\s*=\s*\w+\.CFrame\s*\*", body,
        ):
            continue
        if re.search(r"\b(?:args|payload|clientTarget|clientDestination)\b",
                     body[assigned.start():pivot.start()]):
            continue
        # Preserve *all* occupied seats, not just the pilot, until arrival.
        if not re.search(
            r"(?m)^\s*table\.insert\(\s*occupiedSeats\s*,\s*\{\s*"
            r"seat\s*=\s*part\s*,\s*humanoid\s*=\s*occupant\s*\}\s*\)",
            body,
        ):
            continue
        if not re.search(
            r"(?m)^\s*local\s+occupant\s*=\s*part\.Occupant", body,
        ):
            continue
        if not re.search(
            r"(?m)^\s*local\s+flightToken\s*=\s*\{\s*\}", body,
        ):
            continue
        if not re.search(
            r"inFlight\[player\]\s*=\s*flightToken", body,
        ):
            continue
        # The witness is an actual mutation within the authenticated action,
        # with a verified waypoint, ongoing player/vehicle/seat guards, and an
        # arrival-state update after the movement coroutine.
        # Offsets are in the comment-masked source, whose lines remain in
        # their original order but whose character columns are shorter.
        # Counting newlines in raw using these offsets cites the WRONG line.
        # Whole-requirement completion checks a composite proof contract:
        # 2-6 DISTINCT executable source mutations with exact physical
        # line citations, including the selected primary anchor. An async
        # movement is a multi-stage state transition, not a single pivot.
        # Bind its started -> moved -> arrived writes in execution order.
        launch = re.search(
            r"(?m)^\s*player:SetAttribute\(\s*['\"]RMMFlightState['\"]\s*,"
            r"\s*action\s*==\s*['\"]return['\"]\s+and", body,
        )
        arrived = re.search(
            r"(?m)^\s*player:SetAttribute\(\s*['\"]RMMFlightState['\"]"
            r"\s*,\s*finalState\s*\)", body,
        )
        if not launch or not arrived or not (
            launch.start() < pivot.start() < arrived.start()
        ):
            continue
        raw_lines = raw.splitlines()
        def exact_write(entry: re.Match[str]) -> dict[str, Any] | None:
            offset = action_match.start() + entry.start()
            line_number = code[:offset].count("\n") + 1
            if not 1 <= line_number <= len(raw_lines):
                return None
            quote = raw_lines[line_number - 1].strip()
            if not quote or quote.startswith("--"):
                return None
            return {"line": line_number, "quote": quote}
        started = exact_write(launch)
        moved = exact_write(pivot)
        finished = exact_write(arrived)
        if not all((started, moved, finished)):
            continue
        if ":PivotTo(" not in moved["quote"]:
            continue
        if len({started["line"], moved["line"], finished["line"]}) != 3:
            continue
        options.append((path, [started, moved, finished]))
    if len(options) != 1:
        return None, {
            "status": "unverified",
            "reason": "no_unique_verified_async_vehicle_path",
            "candidate_count": len(options),
        }
    path, lines = options[0]
    return {
        "verdict": "implemented", "file": path,
        # Anchor on the physical vehicle mutation, and include that same
        # exact line among the composite proof citations.
        "line": lines[1]["line"], "quote": lines[1]["quote"],
        "proof_lines": lines, "issue": "none", "repair": "none",
    }, {
        "status": "deterministic_async_source_witness",
        "method": "guarded_occupied_vehicle_timed_world_transition",
        "source_only": True,
        "proof_lines": len(lines),
    }
