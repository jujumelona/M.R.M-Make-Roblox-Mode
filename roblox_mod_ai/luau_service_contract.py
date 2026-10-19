"""Conservative structural checks for the host's callable server service ABI.

The real Luau parser checks grammar. These checks inspect the exported local
service table and the exact entry points the host calls, not arbitrary names
found in comments, strings or unrelated tables. They do not prove gameplay.
"""
from __future__ import annotations

import re
from typing import Any

from .dynamic_wiring import _mask_strings, _without_comments

_NAME = r"[A-Za-z_]\w*"
_RETURN = re.compile(r"\breturn\s+(" + _NAME + r")\s*$")
_LOCAL = re.compile(r"\blocal\s+(" + _NAME + r")(?:\s*:[^=\n]+)?\s*=\s*\{")
_METHOD = re.compile(
    r"\bfunction\s+(?P<table>" + _NAME + r")(?P<separator>[.:])"
    r"(?P<name>" + _NAME + r")\s*\((?P<params>[^)]*)\)|"
    r"\b(?P<assigned_table>" + _NAME + r")\."
    r"(?P<assigned_name>" + _NAME + r")\s*=\s*function\s*\((?P<assigned_params>[^)]*)\)"
)
_EMPTY = re.compile(
    r"\s*(?::\s*(?:\([^\n]*?\)|[A-Za-z_]\w*\??))?\s*"
    r"(?:return\s*(?:(?:true|false|nil|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\{[^()]*\})\s*)?)?end\b"
)


def exported_methods(code: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
    source = _mask_strings(_without_comments(code))
    returned = _RETURN.search(source.strip())
    table = returned.group(1) if returned else None
    declarations = _LOCAL.findall(source)
    if table is None or declarations.count(table) != 1:
        return None, {}
    # Only an unshadowed, immutable binding is a reliable exported table.
    assignments = re.findall(r"(?<![\w.:])" + re.escape(table) + r"(?:\s*:[^=\n]+)?\s*=(?!=)", source)
    if len(assignments) != 1:
        return None, {}
    for params in re.findall(r"\bfunction[^()]*\(([^)]*)\)", source):
        if re.search(r"(?:^|,)\s*" + re.escape(table) + r"\s*(?=:|,|$)", params):
            return None, {}
    methods = {}
    for method in _METHOD.finditer(source):
        owner = method.group("table") or method.group("assigned_table")
        if owner != table:
            continue
        name = method.group("name") or method.group("assigned_name")
        params = method.group("params") if method.group("table") else method.group("assigned_params")
        methods[name] = {
            "params": params.strip(),
            "separator": method.group("separator") or ".",
            "empty": bool(_EMPTY.match(source[method.end():])),
        }
    return table, methods


def _parameter_count(parameters: str) -> int:
    if not parameters.strip():
        return 0
    depth = 0
    count = 1
    for char in parameters:
        if char in "({[<": depth += 1
        elif char in ")}]>": depth = max(0, depth - 1)
        elif char == "," and depth == 0: count += 1
    return count


def service_contract_checks(name: str, code: str, *, require_start: bool,
                            needs_action: bool) -> list[dict[str, Any]]:
    table, methods = exported_methods(code)
    checks = [{"id": "service.export." + name, "passed": table is not None,
               "detail": "Server ModuleScript must return its service table, declared locally"}]
    if require_start:
        start = methods.get("start")
        checks.append({"id": "service.start." + name,
                       "passed": start is not None,
                       "detail": "Server ModuleScript needs an actual exported .start(services) entry point"})
        checks.append({"id": "service.startSignature." + name,
                       "passed": bool(start and start["separator"] == "."
                                      and not re.match(r"self\b", start["params"])
                                      and _parameter_count(start["params"]) <= 1),
                       "detail": "Bootstrap calls Service.start(services) with dot syntax; no implicit self argument"})
        checks.append({"id": "service.implementation." + name,
                       "passed": any(not method["empty"] for method in methods.values()),
                       "detail": "An empty service with only no-op or constant-return functions is not a gameplay implementation"})
    if needs_action:
        action = methods.get("handleAction")
        checks.append({"id": "service.handleAction." + name,
                       "passed": action is not None,
                       "detail": "Host gateway requires exported Service.handleAction(player, services, ...)"})
        checks.append({"id": "service.actionImplementation." + name,
                       "passed": bool(action and not action["empty"] and action["separator"] == "."
                                      and not re.match(r"self\b", action["params"])),
                       "detail": "Host action must perform the requested validation/state change, with player as its first argument"})
    return checks
