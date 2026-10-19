"""Cross-module static contract audit for model-authored server Lua services.

An individual source file can parse yet invoke an invented method on a separate
generated service. This pass joins REAL saved source files at the production
quality gate. It is a static interface check, NOT a Roblox engine playtest.
"""
from __future__ import annotations

import re
from typing import Any

from .spec import RobloxProposal
from .luau_service_contract import service_contract_checks, exported_methods
from .dynamic_wiring import _mask_strings, _without_comments

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_CALL = re.compile(r"\bservices\.(" + _NAME + r")\.(" + _NAME + r")\s*\(")
_BRACKET_CALL = re.compile(r"\bservices\[\s*[\"'](" + _NAME + r")[\"']\s*\]\.(" +
                           _NAME + r")\s*\(")
_EXPORT_FUNCTION = re.compile(
    r"\bfunction\s+(" + _NAME + r")[.:](" + _NAME + r")\s*\(")
_EXPORT_ASSIGN = re.compile(
    r"\b(" + _NAME + r")\.(" + _NAME + r")\s*=\s*function\s*\(")
_RETURN = re.compile(r"\breturn\s+(" + _NAME + r")\s*$")
_LOCAL = re.compile(r"\blocal\s+(" + _NAME + r")\s*=\s*\{")


def inspect_dynamic_server_interfaces(proposal: RobloxProposal) -> dict[str, Any]:
    dynamic = proposal.game_design.get("dynamic_design") or {}
    if not dynamic:
        return {"passed": True, "checks": [], "scope": "not_a_dynamic_game"}

    services = {
        module.name: module
        for module in proposal.modules
        if module.file_path.startswith("src/server/")
        and module.file_path.endswith(".luau")
        and not module.file_path.endswith(".server.luau")
        and (module.module_id.startswith("dyn_") or module.module_id == "mod_player_data")
    }
    checks: list[dict[str, Any]] = []
    exports: dict[str, set[str]] = {}
    for name, module in services.items():
        _, methods = exported_methods(module.code)
        exports[name] = set(methods)
        host_routed = [
            remote for remote, action in
            (dynamic.get("host_actions") or {}).items()
            if isinstance(action, dict) and action.get("service") == name
        ]
        world_routed = [
            object_name for object_name, action in
            (dynamic.get("host_world_actions") or {}).items()
            if isinstance(action, dict) and action.get("service") == name
        ]
        host_routed.extend(world_routed)
        checks.extend(service_contract_checks(
            name, module.code, require_start=module.kind == "server_module",
            needs_action=bool(host_routed)))
        if host_routed:
            source_without_comments = _mask_strings(_without_comments(module.code))
            checks.append({
                "id": "service.hostGatewayNoManualBinding." + name,
                "passed": not bool(re.search(
                    r"\bOnServerEvent\b|\bOnServerInvoke\b",
                    source_without_comments)),
                "detail": "Domain service must not duplicate bootstrap's Remote listeners",
            })

    for caller in proposal.modules:
        if not caller.module_id.startswith("dyn_"):
            continue
        raw_source = _without_comments(caller.code)
        masked = _mask_strings(raw_source)
        for target, method in set([*_CALL.findall(masked),
                                   *_BRACKET_CALL.findall(raw_source)]):
            target_module = services.get(target)
            ok = target_module is not None and method in exports.get(target, ())
            available = (
                "Exported methods on " + target + ": " +
                (", ".join(sorted(exports.get(target, set()))) or "(none)")
                if target_module is not None else
                "Unknown service " + target + "; known services: " +
                ", ".join(sorted(services))
            )
            checks.append({
                "id": "service.call." + caller.name + "." + target + "." + method,
                "passed": ok,
                "detail": ("resolved exported server method" if ok else
                           "missing service or exported method. " + available +
                           ". Repair caller using actual exported API, not an invented symbol."),
            })
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "scope": "cross_module_static_source_not_gameplay_execution",
    }
