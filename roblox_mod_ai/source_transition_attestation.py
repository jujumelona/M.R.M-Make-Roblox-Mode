"""Conservative deterministic attestation of compound authoritative Luau effects.

Genre and prompt independent: recognize server-owned inventory transfers and
persisted profile/world projections through executable state/data flow.
This is source-only proof, never a Roblox Studio or cloud-write attestation.
Unknown contracts remain unverified.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_WORD = re.compile(r"[a-zA-Z]{3,}")
_BINDING = re.compile(
    r"\blocal\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.GetState\s*\(\s*player\s*,\s*([\"'])([^\"']+)\2\s*\)"
)
_WRITE = re.compile(r"^\s*(\w+)\.(\w+)(\[[^\]]+\])?\s*(\+=|-=|=(?!=))\s*(.+)$")
_DONE = re.compile(r"\breturn\s*\{\s*success\s*=\s*true\b")


def _tokens(text: str) -> set[str]:
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    words = set(_WORD.findall(text.lower()))
    return words | {w[:-1] for w in words if w.endswith("s") and len(w) > 4}


def _source_lines(source: str) -> list[str]:
    return ["" if x.lstrip().startswith("--") else x for x in source.splitlines()]


def _handler(source: str) -> tuple[int, list[str]] | None:
    lines = _source_lines(source)
    start = next((i for i, line in enumerate(lines) if re.match(
        r"^function\s+Service\.handleAction\s*\(", line)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if re.fullmatch(
        r"end\s*", lines[i])), None)
    if end is None:
        return None
    return start, lines[start:end + 1]


def _profile_changes(body: list[str]) -> list[tuple[int, str, str, str, str]]:
    bindings = {m.group(1): m.group(3) for line in body
                if (m := _BINDING.search(line))}
    found = []
    for i, line in enumerate(body):
        m = _WRITE.match(line)
        if m and m.group(1) in bindings:
            found.append((i, m.group(1), m.group(2), bindings[m.group(1)], line.strip()))
    return found


def _persist_provider(root: Path, namespace: str, source: str) -> bool:
    """GetState-backed session tables must be included in leased snapshots."""
    if not re.search(r"\b(?:services\.)?PlayerDataManager\b", source):
        return False
    provider = root / "src/server/PlayerDataManager.luau"
    if not provider.is_file() or not provider.resolve().is_relative_to(root.resolve()):
        return False
    data = provider.read_text(encoding="utf-8")
    facts = (
        r"function\s+PlayerDataManager\.GetState\s*\(",
        r"data\.gameState\s*\[\s*namespace\s*\]",
        r"return\s+data\.gameState\s*\[\s*namespace\s*\]",
        r"JSONEncode\s*\(\s*data\s*\)",
        r"UpdateAsync\s*\(\s*key\s*,",
        r"return\s+snapshot\b",
        r"function\s+PlayerDataManager\.OnReady\s*\(",
        r"Players\.PlayerRemoving\s*:\s*Connect\s*\(",
        r"\bsavePlayerData\s*\(\s*player\b",
    )
    return bool(namespace and all(re.search(x, data) for x in facts))


def _attest_transfer(effect: str, source: str, start: int, body: list[str],
                     changes: list[tuple[int, str, str, str, str]]
                     ) -> list[dict[str, Any]] | None:
    """World stock debit + player profile credit with guarded, nonyielding commit."""
    tokens = _tokens(effect)
    if not (tokens & {"increase", "increases", "increased", "credit", "credits",
                       "credited", "gain", "gains", "gained", "increment"}):
        return None
    all_source = "\n".join(_source_lines(source))
    if ("IsDescendantOf(workspace)" not in all_source or ".Magnitude" not in "\n".join(body)
            or not _DONE.search("\n".join(body)) or "GetState" not in "\n".join(body)):
        return None
    for profile_index, profile_var, field, namespace, assignment in changes:
        # The observable can name an inventory/profile, while a generated
        # service writes a concrete resource subtype (e.g. special minerals).
        # Bind the effect to the actual authoritative GetState namespace as
        # well as its field; never require a game-specific field spelling.
        if not ((_tokens(field) | _tokens(namespace)) & tokens):
            continue
        m = re.search(r"=\s*(\w+)\s*\+\s*(\d+)\b", assignment)
        if not m or int(m.group(2)) <= 0:
            continue
        before = "\n".join(body[:profile_index])
        if not re.search(r"\blocal\s+" + re.escape(m.group(1)) +
                         r"\s*=\s*" + re.escape(profile_var) + r"\." +
                         re.escape(field) + r"\b", before):
            continue
        if not re.search(r"\btype\s*\(\s*" + re.escape(m.group(1)) + r"\s*\)", before):
            continue
        for debit_index in range(profile_index):
            debit = body[debit_index]
            debit_match = re.search(r"\b(\w+)\.(\w+)\s*-=\s*\d+\b", debit)
            if not debit_match:
                continue
            stock_var = debit_match.group(1)
            # The depleted stock must originate from a validated world part,
            # never an unrelated or unbound local scratch table.
            stock_origin = re.search(
                r"\blocal\s+" + re.escape(stock_var)
                + r"\s*=\s*(\w+)\s*\(\s*(\w+)\s*\)", before,
            )
            if not stock_origin:
                continue
            reader, part_var = stock_origin.groups()
            reader_match = re.search(
                r"(?ms)^local function\s+" + re.escape(reader)
                + r"\s*\(\s*" + re.escape(part_var)
                + r"\s*\).*?^end\s*$", all_source,
            )
            if (not reader_match
                    or not re.search(r"\breturn\s+\w+\s*\[\s*"
                                     + re.escape(part_var) + r"\s*\]",
                                     reader_match.group())
                    or not re.search(r"\b(?:valid|check|verify)\w*\s*\(\s*"
                                     + re.escape(part_var) + r"\s*\)",
                                     reader_match.group(), re.I)):
                continue
            if not re.search(r"\b" + re.escape(part_var)
                             + r":SetAttribute\s*\(", "\n".join(body[profile_index:])):
                continue
            interval = "\n".join(body[debit_index:profile_index + 1])
            if re.search(r"\b(?:task\.wait|wait|UpdateAsync|SetAsync|InvokeServer)\s*\(", interval):
                continue
            if not re.search(r"\.remaining\s*>\s*0", before):
                continue
            if not re.search(r"\breturn\s+false\b", before):
                continue
            return [
                {"line": start + debit_index + 1, "quote": debit.strip()},
                {"line": start + profile_index + 1, "quote": assignment},
            ]
    return None


def _attest_persisted_projection(effect: str, source: str, root: Path,
                                  start: int, body: list[str],
                                  changes: list[tuple[int, str, str, str, str]]
                                  ) -> list[dict[str, Any]] | None:
    """Player profile mutation, DataStore snapshot, and OnReady world replay."""
    if not re.search(r"\b(?:persist|persistent|persisted|saved|stored|restored)\b", effect, re.I):
        return None
    before_start = "\n".join(_source_lines(source)[:start])
    if ("PlayerDataManager.OnReady" not in before_start
            or not _DONE.search("\n".join(body))):
        return None
    for idx, alias, field, namespace, assignment in changes:
        # A write to some persistent profile is not automatically evidence
        # for an unrelated effect. Tie the claimed object/state to the
        # actual written key or its owning persisted namespace.
        if not ((_tokens(field) | _tokens(namespace)) & _tokens(effect)):
            continue
        if not re.search(r"\[\s*\w+\s*\]", assignment):
            continue
        if not _persist_provider(root, namespace, source):
            continue
        replay = re.search(
            r"(?ms)\bOnReady\s*\(\s*function\s*\(\s*player\s*\)"
            r"(.*?)^\s*end\s*\)", before_start,
        )
        if not replay:
            continue
        replay_body = replay.group(1)
        if not re.search(r"\.GetState\(player,\s*[\"']" + re.escape(namespace)
                         + r"[\"']\)", replay_body):
            continue
        if not re.search(r"\b" + re.escape(alias) + r"\." +
                         re.escape(field) + r"\[\s*\w+\s*\]", replay_body):
            continue
        action_text = "\n".join(body)
        helper_names = set(re.findall(r"\b(\w+)\s*\([^\n]*\)", before_start))
        linked_helpers = [
            name for name in helper_names
            if name not in {"GetState", "OnReady", "FindFirstChild"}
            and re.search(r"\b" + re.escape(name) + r"\s*\(", action_text)
            and re.search(r"\b" + re.escape(name) + r"\s*\(", replay_body)
            and re.search(r"local\s+function\s+" + re.escape(name) + r"\s*\(", before_start)
            and re.search(r"local\s+function\s+" + re.escape(name)
                          + r"\s*\([^)]*\)[\s\S]*?Instance\.new\(", before_start)
        ]
        if not linked_helpers:
            continue
        if not re.search(r"\breturn\s+\{\s*success\s*=\s*false\b", action_text):
            continue
        if re.search(r"\b(?:task\.wait|wait|UpdateAsync|SetAsync)\s*\(",
                     "\n".join(body[max(0, idx - 2):idx + 2])):
            continue
        other = [
            (j, line.strip()) for j, line in enumerate(body[:idx])
            if re.search(r"^\s*\w+\.\w+\s*=\s*\w+\s*[-+]\s*\w+", line)
        ]
        if not other:
            continue
        j, line = other[-1]
        # Bind the persisted record to the actual physical projection.
        # The saved profile write may already prove a separate "attach"
        # requirement; anchor this proof on a *different* executable
        # world-instance mutation to prevent double-counting one line.
        physical = None
        for name in linked_helpers:
            match = re.search(
                r"(?ms)^local function\s+" + re.escape(name)
                + r"\s*\([^)]*\).*?^end\s*$", before_start,
            )
            if not match:
                continue
            for physical_match in re.finditer(
                r"(?m)^\s*\w+\.Parent\s*=\s*\w+\s*$", match.group(),
            ):
                physical = (
                    before_start[:match.start() + physical_match.start()].count("\n") + 1,
                    physical_match.group().strip(),
                )
                break
            if physical:
                break
        if physical is None:
            continue
        physical_line, physical_quote = physical
        return [
            {"line": start + j + 1, "quote": line},
            {"line": start + idx + 1, "quote": assignment},
            {"line": physical_line, "quote": physical_quote},
        ]
    return None


def attest_compound_state_transition(
    effect: str, sources: dict[str, str], modules: list[Any], root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return host-extracted physical source lines, else unverified."""
    original = _tokens(effect)
    generic = {"state", "player", "owned", "server", "world", "valid", "actual",
               "requested", "resulting", "data", "completed", "after", "from"}
    options = []
    for path, source in sorted(sources.items()):
        extracted = _handler(source)
        if extracted is None:
            continue
        start, body = extracted
        changes = _profile_changes(body)
        if not changes:
            continue
        role = next((str(getattr(m, "description", "")) for m in modules
                     if getattr(m, "file_path", None) == path), "")
        # The author-owned role routes evidence; field and state-flow proofs
        # are still mandatory. No game title or prompt-specific branch exists.
        overlap = len((original - generic) & _tokens(path + " " + role))
        # Lexical text is only a routing hint. Requiring two identical
        # English words rejected otherwise proven inventory subtypes and
        # cross-language authoring. Structural state-flow proof below is
        # mandatory regardless of this score.
        if overlap < 1:
            continue
        pair = _attest_transfer(effect, source, start, body, changes)
        method = "world_stock_to_owned_profile"
        if pair is None:
            pair = _attest_persisted_projection(effect, source, root, start, body, changes)
            method = "profile_datastore_to_onready_world_projection"
        if pair:
            options.append((overlap, path, pair, method))
    if len(options) != 1:
        return None, {
            "status": "unverified",
            "reason": "ambiguous_or_unproved_compound_transition",
            "candidate_count": len(options),
        }
    _, path, proof, method = options[0]
    return {
        "verdict": "implemented", "file": path,
        "line": proof[-1]["line"], "quote": proof[-1]["quote"],
        "proof_lines": proof, "issue": "none", "repair": "none",
    }, {
        "status": "deterministic_compound_source_witness",
        "method": method, "source_only": True, "proof_lines": len(proof),
    }
