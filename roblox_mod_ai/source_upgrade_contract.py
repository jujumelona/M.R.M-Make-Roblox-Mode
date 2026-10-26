"""Deterministic proof of a narrow cross-module paid-upgrade transaction.

A quoted source line does not prove a 9B reviewer's semantic assertion. This
source contract verifies the COMPLETE producer -> persistent currency/profile
-> gameplay consumer chain for host-authored rank purchases. It does not
certify Roblox engine execution or cover other, unmatched gameplay.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _match(pattern: str, code: str) -> bool:
    return re.search(pattern, code, flags=re.S) is not None


def attest_paid_upgrade(
    source: str, file_path: str, original: str,
    modules: dict[str, Any], root: Path,
) -> dict[str, Any] | None:
    """Verify saved coin debit and observable downstream rank effect.

    Only recognize the known first-party host protocol, NEVER a free-form
    model-generated file with lookalike comments or invented methods. This is
    intentionally fail-closed when generator implementation or source changes.
    """
    if not file_path.startswith("src/server/"):
        return None
    if not all(piece in source for piece in (
        "local TARGET", "local COST", "local STEP", "local MAX",
        'GetState(player, "RMMRankProgress")',
        'GetState(player, "RMMInventory")',
        "Service.handleAction", "ranks[TARGET]", "coins.Value", "nextRank",
    )):
        # Support the minified first-party source before stylua formatting.
        if not all(piece in source for piece in (
            "local TARGET=", "local COST=", "local STEP=", "local MAX=",
            'GetState(player,"RMMRankProgress")',
            'GetState(player,"RMMInventory")',
            "Service.handleAction", "ranks[TARGET]", "coins.Value", "nextRank",
        )):
            return None

    m = re.search(r'\blocal\s+TARGET\s*=\s*"([^"]+)"', source)
    if not m:
        return None
    target = m.group(1)
    user = original.casefold()
    if target == "crew_performance_state":
        if not ("선원" in user or "crew" in user):
            return None
    elif target == "Spaceship":
        if not ("우주선" in user or "spaceship" in user or "ship" in user):
            return None
        # Explicitly promised thrust/speed/capacity are not verified by a
        # voyage-time calculation alone.
        if any(word in user for word in (
            "추력", "속도", "적재량", "thrust", "speed", "capacity",
        )):
            return None
    elif target == "owned_weapon":
        if not ("무기" in user or "weapon" in user):
            return None
    else:
        return None

    # Prove the actual protected purchase path. String literals, comments,
    # mere ranks and player attributes do not qualify.
    if not all(_match(pattern, source) for pattern in (
        r'local\s+coins\s*=\s*stats\s+and\s+stats:FindFirstChild\("Coins"\)',
        r'coins:IsA\("IntValue"\)',
        r'coins\.Value\s*<\s*COST',
        r'coins\.Value\s*-=\s*COST',
        r'local\s+ranks\s*=\s*services\.PlayerDataManager\.GetState'
        r'\s*\(\s*player\s*,\s*"RMMRankProgress"\s*\)',
        r'local\s+nextRank\s*=\s*math\.min\s*\(\s*MAX\s*,\s*rank\s*\+\s*STEP\s*\)',
        r'ranks\s*\[\s*TARGET\s*\]\s*=\s*nextRank',
        r'player\.Parent\s*~=\s*Players',
        r'select\s*\(\s*"#"\s*,\s*\.\.\.\s*\)\s*~=\s*1',
        r'function\s+Service\.handleAction\s*\(',
    )):
        return None
    # This first-party handler must not yield between debit and rank update.
    debit = re.search(r'coins\.Value\s*-=\s*COST', source)
    rank = re.search(r'ranks\s*\[\s*TARGET\s*\]\s*=\s*nextRank', source)
    if not debit or not rank or debit.end() >= rank.start():
        return None
    critical = source[debit.end():rank.start()]
    if any(x in critical for x in ("task.wait", ":WaitForChild", "RemoteFunction", "coroutine.yield")):
        return None

    profile_candidates = [
        path for path in modules
        if path.startswith("src/server/") and "PlayerDataManager" in path
    ]
    if len(profile_candidates) != 1:
        return None
    profile = (root / profile_candidates[0]).read_text(encoding="utf-8")
    if not all(_match(p, profile) for p in (
        r'coinsVal\.Value\s*=\s*data\.coins',
        r'data\.coins\s*=\s*coins\.Value',
        r'function\s+PlayerDataManager\.GetState\s*\(\s*player\s*,\s*namespace\s*\)',
        r'local\s+data\s*=\s*sessionData\s*\[\s*player\.UserId\s*\]',
        r'data\.gameState\s*\[\s*namespace\s*\]',
        r'savePlayerData\s*=\s*function',
        r'UpdateAsync\s*\(',
    )):
        return None

    if target == "crew_performance_state":
        consumer_checks = (
            r'GetState\s*\(\s*player\s*,\s*"RMMRankProgress"\s*\)',
            r'local\s+crew\s*=\s*ranks\.crew_performance_state\s+or\s+0',
            r'if\s+crew\s*>=\s*3\s+then\s+damage\s*\+=\s*1',
            r'state\.alienHp\s*=\s*hp',
            r'hp\s*=\s*math\.max\s*\(\s*0\s*,\s*hp\s*-\s*damage\s*\)',
        )
    elif target == "Spaceship":
        consumer_checks = (
            r'GetState\s*\(\s*player\s*,\s*"RMMRankProgress"\s*\)',
            r'local\s+rank\s*=\s*progress\.Spaceship\s+or\s+0',
            r'local\s+duration\s*=\s*math\.max\s*\(\s*3\s*,\s*7\s*-\s*0\.4\s*\*\s*rank\s*\)',
            r'\/\s*duration',
            r'vehicle:PivotTo\s*\(\s*start:Lerp\s*\(\s*target\s*,\s*alpha\s*\)\s*\)',
        )
    else:
        consumer_checks = (
            r'GetState\s*\(\s*player\s*,\s*"RMMRankProgress"\s*\)',
            r'local\s+weaponRank\s*=\s*ranks\.owned_weapon\s+or\s+0',
            r'if\s+weaponRank\s*>=\s*3\s+then\s+damage\s*\+=\s*1',
            r'hp\s*=\s*math\.max\s*\(\s*0\s*,\s*hp\s*-\s*damage\s*\)',
            r'inv\.items',
        )
    consumer_files = []
    for path in sorted(modules):
        if path == file_path or not path.startswith("src/server/"):
            continue
        code = (root / path).read_text(encoding="utf-8")
        if all(_match(pat, code) for pat in consumer_checks):
            consumer_files.append(path)
    if len(consumer_files) != 1:
        return None

    # Exact positive evidence for the host's own evidence ledger, not an
    # engine-tested claim. Report both ends to make audit reproducible.
    line = source[:rank.start()].count("\n") + 1
    return {
        "verdict": "implemented",
        "file": file_path,
        "line": line,
        "quote": source[rank.start():rank.end()],
        "method": "deterministic_persisted_upgrade_source_contract",
        "scope": "static_source_only_no_roblox_studio",
        "target": target,
        "coin_persistence_owner": profile_candidates[0],
        "server_effect_consumer": consumer_files[0],
    }
