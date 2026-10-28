"""Engine API value-contract checks for model-authored Luau.

These checks are codegen-independent and run on saved checkpoints as well.
Roblox Attributes cannot store arbitrary Lua dictionaries, tables, Events
or Instances. table.insert mutates an array but RETURNS NOTHING. A Lua parser
cannot detect these runtime-invalid values.
"""
from __future__ import annotations

import re
from .dynamic_wiring import _without_comments, _mask_strings


_ATTRIBUTE_TABLE_ARG = re.compile(
    r"\bSetAttribute\s*\(\s*(?:'[^'\n]+'|\"[^\"\n]+\")\s*,\s*"
    r"(?:\{|table\s*\.\s*(?:clone|insert|create|pack)\s*\()"
)
_ATTRIBUTE_REMOTE_METHOD = re.compile(
    r"\bGetAttribute\s*\([^()\n]*\)\s*:\s*"
    r"(?:FireServer|FireClient|FireAllClients|InvokeClient|InvokeServer|Connect|Wait)\s*\("
)
_ATTRIBUTE_INSTANCE_COMPARISON = re.compile(
    r"\bGetAttribute\s*\([^()\n]*\)\s*[!=]=\s*player\b(?!\s*(?:\.|\[|:))"
    r"|\bplayer\s*[!=]=\s*[^\n]*\bGetAttribute\s*\("
)
_ATTRIBUTE_SET_INSTANCE = re.compile(
    r"\bSetAttribute\s*\(\s*(?:'[^'\n]+'|\"[^\"\n]+\")\s*,\s*"
    r"(?:player\b(?!\s*(?:\.|\[|:))|player\.Character\b(?!\s*(?:\.|\[|:)))"
)
_TABLE_INSERT_ASSIGNED = re.compile(
    r"\b(?:local\s+[A-Za-z_]\w*\s*=\s*|"
    r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]\n]+\])+\s*=\s*)"
    r"table\s*\.\s*insert\s*\(", re.I
)
_ATTRIBUTE_GET_LOCAL = re.compile(
    r"\blocal\s+([A-Za-z_]\w*)\s*=\s*"
    r"[A-Za-z_]\w*\s*:\s*GetAttribute\s*\([^()\n]*\)"
)
_TABLE_ATTRIBUTE_LOCAL = re.compile(
    r"\blocal\s+([A-Za-z_]\w*)\s*=\s*"
    r"[A-Za-z_]\w*\s*:\s*GetAttribute\s*\([^()\n]*\)\s*or\s*\{\s*\}"
)


def roblox_value_contract_errors(source: str) -> list[str]:
    if not isinstance(source, str) or not source:
        return []
    raw = _without_comments(source)
    masked = _mask_strings(raw)
    errors: list[str] = []
    # Keep literal string arguments for SetAttribute and GetAttribute; never
    # scan comments, and ensure the *call name* is executable after masking.
    for matcher, code, description in (
        (_ATTRIBUTE_TABLE_ARG, "ATTRIBUTE_TABLE_UNSUPPORTED",
         "Roblox Attributes cannot store Lua tables or table.clone results"),
        (_ATTRIBUTE_REMOTE_METHOD, "ATTRIBUTE_NOT_REMOTE",
         "GetAttribute returns a value, never a Roblox RemoteEvent/Signal"),
        (_ATTRIBUTE_INSTANCE_COMPARISON, "ATTRIBUTE_NOT_INSTANCE",
         "GetAttribute cannot return a Player Instance"),
        (_ATTRIBUTE_SET_INSTANCE, "ATTRIBUTE_INSTANCE_UNSUPPORTED",
         "SetAttribute cannot persist a Player or Character Instance; store UserId"),
        (_TABLE_INSERT_ASSIGNED, "TABLE_INSERT_RETURNS_NIL",
         "table.insert mutates its first argument and returns nil"),
    ):
        for match in matcher.finditer(raw):
            lead = re.search(r"(SetAttribute|GetAttribute|table)\b", match.group())
            probe = match.start() + (lead.start() if lead else 0)
            if re.match(r"(?:SetAttribute|GetAttribute|table)\b",
                        masked[probe:]):
                errors.append(code + ": " + description)
                break
    # An attribute may contain a string/numeric owner ID, but it can NEVER
    # contain a Player Instance. Catch the common two-statement variant from
    # failure 30: local owner=part:GetAttribute(...); if owner~=player then.
    for found in _ATTRIBUTE_GET_LOCAL.finditer(raw):
        name = found.group(1)
        if not re.match(r"\blocal\b", masked[found.start():]):
            continue
        later = masked[found.end():]
        if (re.search(r"\b" + re.escape(name) +
                      r"\s*[!=]=\s*player\b(?!\s*(?:\.|\[|:))", later)
                or re.search(r"\bplayer\s*[!=]=\s*" + re.escape(name) +
                             r"\b", later)):
            errors.append(
                "ATTRIBUTE_NOT_INSTANCE: A value from GetAttribute cannot "
                "equal a Player Instance; compare the stored UserId instead"
            )
            break
    # An attribute fetched from an Instance cannot contain a Lua table.
    # A fallback of {} is reasonable for an absent value, but it cannot
    # describe a persisted inventory/assembly array.
    for found in _TABLE_ATTRIBUTE_LOCAL.finditer(raw):
        name = found.group(1)
        if not re.match(r"\blocal\b", masked[found.start():]):
            continue
        if re.search(r"\btable\s*\.\s*(?:insert|clone)\s*\(\s*" +
                     re.escape(name) + r"\b", masked):
            errors.append(
                "ATTRIBUTE_TABLE_ROUNDTRIP: GetAttribute cannot retrieve "
                "a persisted Lua array/dictionary"
            )
            break
    return errors
