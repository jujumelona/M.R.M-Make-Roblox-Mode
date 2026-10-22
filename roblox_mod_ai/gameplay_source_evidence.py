"""Bounded static evidence for gameplay source, not boilerplate.

Never infer that a gameplay action executed merely because a ModuleScript
contains --!strict, an injected service registry assignment, or diagnostic
text saying SetAttribute. This only verifies the presence of a *candidate*
server-side state mutation; it cannot establish full request fidelity or
replace a Roblox Studio playtest.
"""
from __future__ import annotations

import re

from .dynamic_wiring import _mask_strings, _without_comments

_AUTHOR_BODY_START = "-- RMM_GAMEPLAY_BODY_BEGIN"
_AUTHOR_BODY_END = "-- RMM_GAMEPLAY_BODY_END"
_MUTATION = re.compile(
    r"\b(?:TrySpend|Grant|SetAttribute|PivotTo|Teleport|"
    r"TakeDamage|Create|Destroy|AddItem|RemoveItem|SetPrimaryPartCFrame|"
    r"ApplyImpulse|LoadCharacter)\s*\(|"
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]]+\])\s*(?:\+=|-=|=(?!=))",
    re.I,
)
_SERVICE_ACTION = re.compile(r"\bfunction\s+Service\.handleAction\s*\(")
_REGISTRY_WRITER = re.compile(r"\bService\._services\s*=\s*services\b")


def authored_action_body(source: str) -> str:
    """Return exactly the routed action body, not the host scaffolding.

    Old generated Service Modules without sentinels remain readable, but a
    completely missing action cannot pass via Service.start registry writes.
    """
    if _AUTHOR_BODY_START in source or _AUTHOR_BODY_END in source:
        if (source.count(_AUTHOR_BODY_START) != 1
                or source.count(_AUTHOR_BODY_END) != 1):
            return ""
        start = source.index(_AUTHOR_BODY_START) + len(_AUTHOR_BODY_START)
        end = source.index(_AUTHOR_BODY_END)
        return source[start:end] if start < end else ""
    match = _SERVICE_ACTION.search(source)
    if not match:
        return ""
    # Host service templates close their top-level function with an
    # unindented end. Nested Luau statements are indented.
    close = re.search(r"(?m)^end\s*$", source[match.end():])
    if close is None:
        return ""
    return source[match.end():match.end() + close.start()]


def has_gameplay_mutation(source: str, *, routed_action: bool = False) -> bool:
    """Find a possible mutation in real code only, never model prose."""
    if not isinstance(source, str) or not source.strip():
        return False
    owned = authored_action_body(source) if routed_action else source
    if routed_action and not owned:
        return False
    executable = _mask_strings(_without_comments(owned))
    executable = _REGISTRY_WRITER.sub("", executable)
    return bool(_MUTATION.search(executable))


def state_key_used_by_executable_code(body: str, key: str) -> bool:
    """Distinguish a real state-key reference from comments and log strings.

    Dotted properties are executable identifiers; key strings are meaningful
    only when passed as the key argument of a state access/mutation call.
    This is a necessary static source check, not proof the transition occurs.
    """
    if not isinstance(body, str) or not isinstance(key, str):
        return False
    leaf = key.split(".")[-1]
    if not leaf:
        return False
    raw = _without_comments(body)
    executable = _mask_strings(raw)
    # The key must identify a mutated owner/field, not merely appear in
    # an unrelated local variable, guard expression, or right-hand operand.
    for line in executable.splitlines():
        for match in _MUTATION.finditer(line):
            # Only the actual mutated expression can own this key; a
            # similarly named local variable earlier on the SAME line is
            # not a state effect.
            if re.search(r"\b" + re.escape(leaf) + r"\b",
                         match.group(), flags=re.I):
                return True

    # A quoted key is evidence only when it is a literal argument of a
    # state-MUTATING operation. Reading GetState("key") is not writing it.
    selector = re.compile(
        r"\b(?:SetAttribute|SetState|UpdateState)"
        r"\s*\(\s*(['\"])" + re.escape(leaf) + r"\1",
        re.I,
    )
    for match in selector.finditer(raw):
        if re.match(r"\b(?:SetAttribute|SetState|UpdateState)"
                    r"\s*\(", executable[match.start():], re.I):
            return True
    return False
