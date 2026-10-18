"""Conservative checks for specific invalid Roblox/Luau API calls.

Rules are derived from actual small-model failures, not a supposed complete
Roblox API typechecker. Real Luau parser, Selene, Rojo and Studio verification
remain independent gates. Ignore quoted strings and comments.
"""
from __future__ import annotations

import re

from .dynamic_wiring import _mask_strings, _without_comments

_INVALID_CALLS = (
    (r"\btype\s*\.\s*isnumber\s*\(", "type.isnumber does not exist; use type(x) == 'number'"),
    (r"\btype\s*\.\s*isinteger\s*\(", "type.isinteger does not exist; validate with math.floor(x) == x"),
    (r"\btype\s*\.\s*isstring\s*\(", "type.isstring does not exist; use type(x) == 'string'"),
    (r"\bos\s*\.\s*now\s*\(", "os.now does not exist; use os.time() where timestamps are needed"),
    (r"\bgame\s*:\s*GetServices\s*\(", "game:GetServices is invalid; request one named service using GetService"),
    (r"\bgame\s*[.:]\s*GetPlayers\s*\(", "game does not implement GetPlayers; use Players:GetPlayers()"),
    (r"\bgame\s*\.\s*_PlayerService\b", "game._PlayerService is not a Roblox service"),
)


def invalid_luau_apis(source: str) -> list[str]:
    code = _mask_strings(_without_comments(source))
    return [
        message
        for expression, message in _INVALID_CALLS
        if re.search(expression, code)
    ]
