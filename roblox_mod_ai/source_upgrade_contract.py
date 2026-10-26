"""Source-bound, genre-independent verification for host-authored paid upgrades.

Do not infer effects from game names, English/Korean prompt vocabulary, or
known targets such as Spaceship / owned_weapon / crew_performance_state.

Recognize the EXACT host paid-upgrade ABI, verify persisted debit, then trace
the declared TARGET through a different server consumer into a real state or
world mutation. Unsupported patterns are reviewed normally (fail closed).
This is a narrow static proof, NOT a Studio gameplay test.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _match(pattern: str, code: str) -> re.Match[str] | None:
    return re.search(pattern, code, flags=re.S)


def _ident(text: str, name: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text) is not None


def _executable_lines(source: str) -> list[str]:
    # Disallow convincing-looking Luau comments from becoming effect evidence.
    return [line.split("--", 1)[0].strip() for line in source.splitlines()]


def _effect_consumer(code: str, namespace: str, target: str) -> bool:
    """Small forward data-flow check from persisted rank to observable effect.

    Accept a read of exactly the stored field, followed by arithmetic or a
    conditional that controls a real state write / engine action. No generic
    "rank mentioned anywhere" positive conclusion. Only source-grounded
    effects in the SAME server file qualify.
    """
    lines = _executable_lines(code)
    # Read the same authoritative state namespace as the purchasing owner.
    pattern = (r'\blocal\s+(\w+)\s*=\s*services\.PlayerDataManager\.GetState'
               r'\s*\(\s*player\s*,\s*"' + re.escape(namespace) + r'"\s*\)')
    joined = "\n".join(lines)
    providers = set(re.findall(pattern, joined))
    if not providers:
        return False
    read_pattern = (
        r'\blocal\s+(\w+)\s*=\s*(\w+)\s*(?:\.'
        + re.escape(target) + r'\b|\[\s*"' + re.escape(target)
        + r'"\s*\])'
    )
    variables: set[str] = set()
    read_lines = []
    for i, line in enumerate(lines):
        found = re.search(read_pattern, line)
        if found and found.group(2) in providers:
            variables.add(found.group(1))
            read_lines.append(i)
    if not variables:
        return False

    # Iterate because derived values can be defined in nested blocks. Do not
    # assume a fixed game mechanic, consumer name, rank level, or math formula.
    for _ in range(8):
        added: set[str] = set()
        for i, line in enumerate(lines):
            if i < min(read_lines) or not line:
                continue
            # Direct assignment: 'local duration = formula(rank)' or
            # 'hp = math.max(0, hp - damage)'.
            m = re.match(r'(?:local\s+)?(\w+)\s*=\s*(.+)$', line)
            if m and any(_ident(m.group(2), t) for t in variables):
                added.add(m.group(1))
            # Branch-control dependency: 'if rank >= n then damage += 1'.
            if re.search(r'\bif\b.+\bthen\b', line):
                condition = line.split("then", 1)[0]
                if any(_ident(condition, t) for t in variables):
                    for body_line in lines[i:i + 5]:
                        incr = re.search(
                            r'\b(\w+)\s*(?:\+=|-=|\*=|/=)', body_line
                        )
                        if incr:
                            added.add(incr.group(1))
        if added.issubset(variables):
            break
        variables.update(added)

    # Require a concrete sink whose input actually contains the tainted value.
    # Persisted property mutations and real engine gameplay actions qualify;
    # displaying a player Attribute or returning the rank does NOT.
    for i, line in enumerate(lines):
        if i < min(read_lines) or not line:
            continue
        state = re.search(
            r'\b(?:state|progress|inventory)\s*(?:\.\w+|\[.+?\])\s*=\s*(.+)',
            line,
        )
        if state and any(_ident(state.group(1), t) for t in variables):
            return True
        engine = re.search(
            r':(?:PivotTo|MoveTo|TakeDamage|ApplyImpulse|'
            r'ApplyAngularImpulse|SetAttribute)\s*\((.+)',
            line,
        )
        if engine and not line.lstrip().startswith("--"):
            # SetAttribute is cosmetic/metadata and cannot prove a gameplay
            # effect on its own (the target may simply be UI rank display).
            if ":SetAttribute" in line:
                continue
            if any(_ident(engine.group(1), t) for t in variables):
                return True
        # Physical properties like speed / collision / force are effects.
        property_write = re.search(
            r'\b\w+\.(?:WalkSpeed|JumpPower|AssemblyLinearVelocity|'
            r'VectorVelocity|MaxForce|MaxTorque|Health|'
            r'Damage|Thrust|Speed|Capacity)\s*=\s*(.+)', line,
        )
        if property_write and any(
                _ident(property_write.group(1), t) for t in variables):
            return True
    return False


def _requested_effect_is_more_specific(original: str, consumer: str) -> bool:
    """Conservatively reject an explicit property request absent in the sink.

    This is NOT a game-genre dictionary. Extract any source-level field names
    the user explicitly says 'must change X [and Y]' and require their
    occurrence in executable consumer code. Generic prose is left to review.
    """
    m = re.search(
        r'\bmust\s+(?:actually\s+)?(?:change|modify|increase)\s+'
        r'([A-Za-z_][A-Za-z0-9_]*(?:\s+and\s+[A-Za-z_][A-Za-z0-9_]*)*)',
        original, re.I,
    )
    if not m:
        return False
    fields = re.split(r'\s+and\s+', m.group(1))
    joined = "\n".join(_executable_lines(consumer)).casefold()
    return any(not _ident(joined, field.casefold()) for field in fields)


def attest_paid_upgrade(
    source: str, file_path: str, original: str,
    modules: dict[str, Any], root: Path,
) -> dict[str, Any] | None:
    if not file_path.startswith("src/server/") or not original.strip():
        return None
    # ABI verification, not any small-model-authored string that happens to
    # mention the same key. The host owns the atomic transaction.
    declared = _match(r'\blocal\s+TARGET\s*=\s*"([A-Za-z_]\w*)"', source)
    if not declared:
        return None
    target = declared.group(1)
    wallet_guard = (
        r'local\s+coins\s*=\s*stats\s+and\s+stats:FindFirstChild\("Coins"\)',
        r'coins:IsA\("IntValue"\)',
        r'coins\.Value\s*<\s*COST',
        r'coins\.Value\s*-=\s*COST',
        r'local\s+nextRank\s*=\s*math\.min\s*\(\s*MAX\s*,\s*rank\s*\+\s*STEP\s*\)',
        r'ranks\s*\[\s*TARGET\s*\]\s*=\s*nextRank',
        r'player\.Parent\s*~=\s*Players',
        r'select\s*\(\s*"#"\s*,\s*\.\.\.\s*\)\s*~=\s*1',
        r'function\s+Service\.handleAction\s*\(',
        r'local\s+COST\s*=\s*\d+',
        r'local\s+MAX\s*=\s*\d+',
        r'local\s+STEP\s*=\s*\d+',
    )
    if not all(_match(pattern, source) for pattern in wallet_guard):
        return None
    state = _match(
        r'local\s+ranks\s*=\s*services\.PlayerDataManager\.GetState'
        r'\s*\(\s*player\s*,\s*"([A-Za-z_]\w*)"\s*\)', source,
    )
    if state is None:
        return None
    namespace = state.group(1)
    debit = _match(r'coins\.Value\s*-=\s*COST', source)
    write = _match(r'ranks\s*\[\s*TARGET\s*\]\s*=\s*nextRank', source)
    if not debit or not write or debit.end() >= write.start():
        return None
    critical = source[debit.end():write.start()]
    if any(x in critical for x in (
            "task.wait", ":WaitForChild", "RemoteFunction", "coroutine.yield")):
        return None

    # Find an actual persistence owner by its implementation contract, not
    # by a particular module's file name or game's currency narrative.
    profile_files = []
    for path in modules:
        if not path.startswith("src/server/"):
            continue
        code = (root / path).read_text(encoding="utf-8")
        if all(_match(pattern, code) for pattern in (
            r'coinsVal\.Value\s*=\s*data\.coins',
            r'data\.coins\s*=\s*coins\.Value',
            r'function\s+PlayerDataManager\.GetState\s*\(',
            r'data\.gameState\s*\[\s*namespace\s*\]',
            r'savePlayerData\s*=\s*function',
            r'UpdateAsync\s*\(',
        )):
            profile_files.append(path)
    if len(profile_files) != 1:
        return None

    consumer_paths: list[str] = []
    for path in sorted(modules):
        if path == file_path or path == profile_files[0] or not path.startswith("src/server/"):
            continue
        consumer = (root / path).read_text(encoding="utf-8")
        if (_effect_consumer(consumer, namespace, target)
                and not _requested_effect_is_more_specific(original, consumer)):
            consumer_paths.append(path)
    if len(consumer_paths) != 1:
        # Multiple candidate consumers are ambiguous, not proof that a
        # specific requirement is fulfilled. Emit normal review instead.
        return None
    assert write is not None
    line = source[:write.start()].count("\n") + 1
    return {
        "verdict": "implemented",
        "file": file_path,
        "line": line,
        "quote": source[write.start():write.end()],
        "method": "deterministic_persisted_upgrade_source_contract",
        "scope": "static_source_only_no_roblox_studio",
        "target": target,
        "state_namespace": namespace,
        "coin_persistence_owner": profile_files[0],
        "server_effect_consumer": consumer_paths[0],
    }
