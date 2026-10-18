"""Detect pathological code repetition DURING streamed llama.cpp inference.

Two actual failure modes:
* hundreds of consecutive identical assignment lines
* SpaceModeManager repeatedly restarts its entire module declaration block

A repeated code body is *not* an appropriate prompt example for the repair AI.
"""
from __future__ import annotations

from collections import deque
import re


class RepeatedCodeOutput(RuntimeError):
    def __init__(self, repeated_line: str, count: int, partial: str):
        self.repeated_line = repeated_line
        self.count = count
        self.partial_output = partial
        super().__init__(
            f"Model stuck repeating generated Luau {count} times: "
            + repeated_line[:180])


class LiveCodeRepetitionGuard:
    def __init__(self, max_consecutive: int = 8):
        self.max_consecutive = max_consecutive
        self._pending = ""
        self._previous = ""
        self._count = 0
        self._partial = ""
        self._structural_seen: dict[str, int] = {}
        self._recent: deque[str] = deque(maxlen=6)
        self._sequence_seen: dict[tuple[str, ...], int] = {}

    def feed(self, chunk: str) -> None:
        self._pending += chunk
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            # Preserve ONLY emitted source up to the first bad line.
            # A non-streaming inspect() may feed the full 20KB at once.
            self._partial += line + "\n"
            stripped = line.strip()
            if stripped and len(stripped) >= 12 and stripped == self._previous:
                self._count += 1
            else:
                self._count = 1 if stripped else 0
            self._previous = stripped
            if self._count >= self.max_consecutive:
                raise RepeatedCodeOutput(stripped, self._count, self._partial)
            if not stripped:
                continue

            # A model can repeat its *entire module* without adjacent
            # duplicate lines. Repeated top-level function/type declarations
            # must never be accepted as useful gameplay.
            marker = re.match(
                r"^(?:local\s+function\s+[A-Za-z_]\w*|"
                r"(?:export\s+)?type\s+[A-Za-z_]\w*|"
                r"local\s+[A-Za-z_]\w*\s*=\s*game:GetService\(|"
                r"--\[\[\s*.+?\s*\]\]--)$",
                stripped,
            )
            if marker and not line[:1].isspace():
                key = marker.group(0)
                n = self._structural_seen.get(key, 0) + 1
                self._structural_seen[key] = n
                if n >= 3:
                    raise RepeatedCodeOutput(
                        "redeclared top-level " + key, n, self._partial)

            # Periodically repeating function bodies may not have identical
            # names. Require THREE occurrences of a substantial six-line
            # sequence to avoid flagging legitimate small shared idioms.
            normalized = " ".join(stripped.split())
            self._recent.append(normalized)
            if len(self._recent) == 6:
                signature = tuple(self._recent)
                if sum(map(len, signature)) >= 110:
                    n = self._sequence_seen.get(signature, 0) + 1
                    self._sequence_seen[signature] = n
                    if n >= 3:
                        raise RepeatedCodeOutput(
                            "repeated code block " +
                            " / ".join(signature[:2])[:120],
                            n, self._partial)

    @classmethod
    def inspect(cls, full_code: str) -> None:
        guard = cls()
        guard.feed(full_code + "\n")
