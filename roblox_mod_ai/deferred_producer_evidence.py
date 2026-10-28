"""Static ownership evidence for deferred model-authored gameplay actions.

A typed input Remote is not a state producer. The earlier codegen gate
accepted any assignment in the routed action, including assignments to
temporary scratch tables. Require at least one code mutation connected to
a server-owned player or world root. This is necessary evidence, not proof
of runtime correctness, persistence, or target existence.
"""
from __future__ import annotations

import re

from .dynamic_wiring import _without_comments, _mask_strings
from .gameplay_source_evidence import authored_action_body, has_gameplay_mutation

_LOCAL_BINDING = re.compile(r"\blocal\s+([A-Za-z_]\w*)\s*=\s*([^\n]+)")
_STATE_READER = re.compile(
    r"\bservices\s*\.\s*PlayerDataManager\s*\.\s*GetState\s*"
    r"\(\s*player\s*,", re.I,
)
_PLAYER_STATE = re.compile(
    r"\bplayer\b\s*(?:\.\s*(?:leaderstats|Character|Backpack|PlayerGui)\b"
    r"|:\s*FindFirstChild\s*\(|:\s*WaitForChild\s*\()", re.I,
)
_WORLD_READER = re.compile(
    r"\b(?:workspace|Workspace|actionTarget|targetPart)\b\s*(?:\.|:|\[)", re.I,
)
_NEW_INSTANCE = re.compile(r"\bInstance\s*\.\s*new\s*\(", re.I)
_WRITE_OPERATOR = r"(?:\+=|-=|(?<![=<>])=(?!=))"
_STATE_METHOD = r"(?:SetAttribute|PivotTo|TakeDamage|Destroy|ApplyImpulse|Teleport|SetPrimaryPartCFrame|LoadCharacter)"
_TEMPORARY_STATE = re.compile(
    r"\blocal\s+(?:player|actionTarget|targetPart|workspace)\s*=", re.I,
)


def _target_has_write(body: str, root: str) -> bool:
    needle = re.escape(root)
    member = re.compile(
        r"\b" + needle + r"\b(?:\s*\.\s*[A-Za-z_]\w*"
        r"|\s*\[[^\]\n]+\])+\s*" + _WRITE_OPERATOR,
        re.I,
    )
    call = re.compile(
        r"\b" + needle + r"\s*:\s*" + _STATE_METHOD + r"\s*\(", re.I,
    )
    insertion = re.compile(
        r"\btable\s*\.\s*(?:insert|remove)\s*\(\s*" + needle
        + r"\b(?:\s*[.\[].*?)?\s*,", re.I,
    )
    return bool(member.search(body) or call.search(body) or insertion.search(body))


def has_authoritative_producer_write(code: str) -> bool:
    """Detect a necessary direct effect on authenticated state or a real target."""
    if not isinstance(code, str) or not has_gameplay_mutation(
            code, routed_action=True):
        return False
    raw = _without_comments(authored_action_body(code))
    executable = _mask_strings(raw)
    if _TEMPORARY_STATE.search(executable):
        return False
    if any(_target_has_write(executable, root)
           for root in ("player", "actionTarget", "targetPart", "workspace")):
        return True

    trusted: set[str] = set()
    new_objects: set[str] = set()
    for _ in range(3):
        changed = False
        for match in _LOCAL_BINDING.finditer(executable):
            var, rhs = match.group(1), match.group(2)
            if var not in trusted and (
                _STATE_READER.search(rhs) or _PLAYER_STATE.search(rhs) or
                _WORLD_READER.search(rhs) or
                any(re.search(r"\b" + re.escape(owner) +
                              r"\b\s*(?:[.\[]|$)", rhs)
                    for owner in trusted)
            ):
                trusted.add(var)
                changed = True
            if _NEW_INSTANCE.search(rhs):
                new_objects.add(var)
        if not changed:
            break

    if any(_target_has_write(executable, var) for var in trusted):
        return True

    # A locally created object is a physical state producer only if its
    # Parent is a verified world/player container. Local tables never qualify.
    for var in new_objects:
        dest = re.search(
            r"\b" + re.escape(var) + r"\s*\.\s*Parent\s*=\s*"
            r"([A-Za-z_]\w*)\b", executable, re.I,
        )
        if dest and (dest.group(1).lower() in ("workspace", "player")
                     or dest.group(1) in trusted):
            return True
    return False
