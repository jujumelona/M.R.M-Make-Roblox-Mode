"""Generic host ABI contract for *all* bounded model-written Luau actions.

A small coder may describe game logic, but cannot redefine authenticated
identity, invent argument names, or manufacture methods on host modules.
Repairs here are limited to a single obviously incorrect wire-identity
alias. Other violations remain hard failures with exact schema diagnostics.
This is NOT a gameplay implementation or a claim of Roblox runtime success.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .dynamic_wiring import _mask_strings, _without_comments

_HOST_ALIAS = re.compile(
    r"^(?P<indent>[ \t]*)local[ \t]+"
    r"(?P<name>player|services|Player|Services)[ \t]*="
    r"[ \t]*(?:args[ \t]*\[[ \t]*(?P<index>[12])[ \t]*\])"
    r"[ \t]*;?[ \t]*$", re.I,
)
# The host's lua_server_guard explicitly declares 'local args = actionArgs'.
# They are the SAME validated dictionary, not separate positional arrays.
_DOT_FIELD = re.compile(
    r"\b(?:actionArgs|args)[ \t]*\.[ \t]*([A-Za-z_][A-Za-z_0-9]*)"
)
_BRACKET_FIELD = re.compile(
    r"\b(?:actionArgs|args)[ \t]*\[[ \t]*(['\"])([A-Za-z_][A-Za-z_0-9]*)\1[ \t]*\]"
)
_POSITIONAL_INDEX = re.compile(r"\b(?:actionArgs|args)[ \t]*\[[ \t]*\d+[ \t]*\]")
_SHADOW_VALIDATED_ARGS = re.compile(
    r"\blocal[ \t]+(?:args|actionArgs)[ \t]*=", re.I,
)
_UNKNOWN_TYPED_DEPENDENCY = re.compile(
    r"\b(?:services|_services)[ \t]*\.[ \t]*"
    r"([A-Za-z_][A-Za-z_0-9]*)[ \t]*[:.]"
    r"([A-Za-z_][A-Za-z_0-9]*)[ \t]*\("
)


def host_abi_guidance(contract: dict[str, Any] | None,
                      peer_methods: dict[str, list[str]]) -> str:
    """Supply EXACT host-declared input keys & dependency APIs to the coder."""
    inputs = list((contract or {}).get("inputs") or [])
    fields = {f["id"]: f["type"] for f in inputs
              if isinstance(f, dict) and isinstance(f.get("id"), str)}
    return (
        "IMMUTABLE HOST ABI -- NOT OPTIONAL:\n"
        "- player is the authenticated Roblox Player already passed by the host. "
        "services is the injected server service registry. Never create local "
        "player/services or read them from client args.\n"
        "- actionArgs is a host-validated table. EXACT permitted field names "
        "(other names are invalid): " + json.dumps(fields, sort_keys=True) + ".\n"
        "- For a stored player namespace, only call "
        "services.PlayerDataManager.GetState(player, namespace) with DOT "
        "syntax. It returns the SAME mutable server-owned table or nil; "
        "do not create a new one, and never call SetState/SaveState.\n"
        "- Never call game:GetService for a generated game module; "
        "only real Roblox engine services are returned by GetService.\n"
        "- Exported services API (empty lists mean no exported callable "
        "methods): " + json.dumps(peer_methods, sort_keys=True) + ".\n"
        "- Source action rewards/prices may NOT be derived from an "
        "untrusted requested quantity or a client-provided balance.\n"
        "- Use only source-approved world objects, state keys and declared "
        "inputs. If the contract omits a required server-side target or "
        "effect, it is incomplete, not permission to invent it.\n"
    )


def normalize_trusted_player_aliases(body: str) -> str:
    """Correct only a proved spoofed-identity alias, never domain logic.

    The host already checks the real caller and passes player/registry. A line
    'local player = args[1]' is not useful state: it shadows trusted identity
    with untrusted input. Removing that exact assignment retains the already
    scoped trusted variable. Upper-case aliases must bind to the real host
    parameter instead. Any other redefining pattern is intentionally rejected
    by normalize_verified_server_body.
    """
    result: list[str] = []
    for original in body.splitlines(keepends=True):
        line = original.rstrip("\r\n")
        match = _HOST_ALIAS.fullmatch(line)
        if not match:
            result.append(original)
            continue
        name = match.group("name")
        index = int(match.group("index"))
        identity = "player" if name.lower() == "player" else "services"
        expected = 1 if identity == "player" else 2
        if index != expected:
            result.append(original)
            continue
        if name in ("player", "services"):
            # Exact erroneous declaration only: the existing trusted host
            # function parameter becomes visible after removing it.
            continue
        ending = original[len(line):]
        result.append(match.group("indent") +
                      "local " + name + " = " + identity + ending)
    return "".join(result)


def typed_input_abi_errors(body: str,
                           contract: dict[str, Any] | None) -> list[str]:
    """Reject fields not present in the actual compiled transport schema.

    Spellings such as actionArgs.fieldId in a selection/quantity payload
    cannot work at runtime even when the Luau parser accepts them.
    """
    if contract is None:
        return []
    inputs = contract.get("inputs") or []
    valid = {field["id"] for field in inputs
             if isinstance(field, dict) and isinstance(field.get("id"), str)}
    # Strip comments for code-only inspection; keep strings to inspect
    # constant bracket indices after normalizing code comments.
    raw = _without_comments(body)
    masked = _mask_strings(raw)
    accessed = {m.group(1) for m in _DOT_FIELD.finditer(masked)}
    accessed.update(m.group(2) for m in _BRACKET_FIELD.finditer(raw)
                    if re.match(r"(?:actionArgs|args)\b", masked[m.start():]))
    problems = []
    wrong = sorted(accessed - valid)
    if wrong:
        problems.append(
            "TYPED_INPUT_ABI: undeclared validated input fields " +
            ", ".join(wrong) + "; exact allowed inputs: " +
            ", ".join(sorted(valid))
        )
    if _POSITIONAL_INDEX.search(masked):
        problems.append(
            "TYPED_INPUT_ABI: numeric positional index used on named "
            "validated actionArgs/args table"
        )
    if _SHADOW_VALIDATED_ARGS.search(masked):
        problems.append(
            "TYPED_INPUT_ABI: body redefines host-owned validated args"
        )
    return problems


def typed_input_fields_used(body: str, contract: dict[str, Any] | None) -> set[str]:
    """Real field reads through either host alias, ignoring comments/strings."""
    if not isinstance(contract, dict):
        return set()
    valid = {field["id"] for field in contract.get("inputs", [])
             if isinstance(field, dict) and isinstance(field.get("id"), str)}
    raw = _without_comments(body)
    masked = _mask_strings(raw)
    fields = {m.group(1) for m in _DOT_FIELD.finditer(masked)}
    fields.update(m.group(2) for m in _BRACKET_FIELD.finditer(raw)
                  if re.match(r"(?:actionArgs|args)\b", masked[m.start():]))
    return fields & valid



def remove_redundant_state_commit(body: str) -> str:
    """Remove only a provably nonexistent persistence call on a LIVE state ref.

    The host PlayerDataManager.GetState(player, namespace) returns a mutable
    server-owned profile table. Calling SetState is an AI-invented API; the
    in-place mutations already update the real state. This only removes an
    exact standalone call when the SAME local came from the SAME namespace.
    An unrelated service, reassigned local, differently named namespace or
    non-standalone statement is NOT rewritten.
    """
    local_state = re.compile(
        r'^\s*local\s+([A-Za-z_]\w*)\s*=\s*services\s*\.\s*'
        r'PlayerDataManager\s*\.\s*GetState\s*\(\s*player\s*,\s*'
        r'(["\x27])([^"\x27\n]+)\2\s*\)\s*;?\s*$'
    )
    wrong_commit = re.compile(
        r'^\s*services\s*\.\s*PlayerDataManager\s*[.:]\s*'
        r'SetState\s*\(\s*player\s*,\s*(["\x27])([^"\x27\n]+)\1'
        r'\s*,\s*([A-Za-z_]\w*)\s*\)\s*;?\s*$'
    )
    lines = body.splitlines(keepends=True)
    locals_by_name: dict[str, str] = {}
    for line in lines:
        match = local_state.fullmatch(line.strip())
        if match:
            locals_by_name[match.group(1)] = match.group(3)
    result = []
    for line in lines:
        match = wrong_commit.fullmatch(line.strip())
        if not match:
            result.append(line)
            continue
        name = match.group(3)
        namespace = match.group(2)
        # Even a variable originally holding a live reference can be
        # overwritten later; that requires a real proof, not silent removal.
        original_refs = re.findall(
            r'(?<![\w.])' + re.escape(name) + r'\s*=(?!=)', body
        )
        if locals_by_name.get(name) != namespace or len(original_refs) != 1:
            result.append(line)
            continue
        # Preserve exact newline layout of the accepted body. Removing this
        # call is safe only because the authoritative state is mutable.
    return "".join(result)
