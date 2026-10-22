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
