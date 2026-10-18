"""Detect repeated generated source while it is still streaming.

An actual MiMo run returned 723 copies of "self.lastColonizeId = nil" in
758 lines, consuming 6000 tokens and 27 minutes across retries.
This guard is only for pathological *consecutive* repeated nonblank code lines.
"""
from __future__ import annotations


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

    def feed(self, chunk: str) -> None:
        self._partial += chunk
        self._pending += chunk
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            stripped = line.strip()
            if stripped and len(stripped) >= 12 and stripped == self._previous:
                self._count += 1
            else:
                self._count = 1 if stripped else 0
            self._previous = stripped
            if self._count >= self.max_consecutive:
                raise RepeatedCodeOutput(stripped, self._count, self._partial)

    @classmethod
    def inspect(cls, full_code: str) -> None:
        guard = cls()
        guard.feed(full_code + "\n")
