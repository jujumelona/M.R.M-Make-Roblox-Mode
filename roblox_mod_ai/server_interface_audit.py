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


def dependency_api_errors(module: Any, proposal: RobloxProposal, code: str) -> list[str]:
    """Check known generated service APIs, including simple local aliases.

    This uses saved peer exports, not a guessed Roblox API catalogue. Bootstrap
    owns initialization, and gameplay must not replace another service's API.
    """
    # Include the current service as well. A generated action must not refer
    # to services.Self.catalog or services.Self.crew unless that field is
    # actually initialized by the host/module, not merely hallucinated by 9B.
    peers = {m.name: m for m in getattr(proposal, "modules", [])
             if m.file_path.startswith("src/server/")
             and m.file_path.endswith(".luau")
             and not m.file_path.endswith(".server.luau")}
    if not peers:
        return []
    raw = _without_comments(code)
    masked = _mask_strings(raw)
    errors = []
    for match in re.finditer(r"\bgame\s*:\s*GetService\s*\(\s*(['\"])(" + _NAME + r")\1\s*\)", raw):
        target = match.group(2)
        if target in peers and masked[match.start():match.start() + 4] == "game":
            errors.append("DEPENDENCY_API: " + target +
                          " is a generated ModuleScript, not an engine service; "
                          "use the injected services." + target + " API")
    receivers = {root + "." + name: name
                 for root in ("services", "_services") for name in peers}
    for alias, target in re.findall(
            r"\blocal\s+(" + _NAME + r")\s*=\s*_?services\s*\.\s*(" + _NAME + r")\b(?!\s*[.:\[(])", masked):
        if target in peers:
            # Ambiguous/shadowed aliases need a real typechecker. Do not
            # infer that every same-name local is this dependency.
            writes = re.findall(r"(?<![\w.:])" + re.escape(alias) + r"\s*=(?!=)", masked)
            shadowed = any(re.search(r"(?:^|,)\s*" + re.escape(alias) + r"\s*(?=:|,|$)", params)
                           for params in re.findall(r"\bfunction[^()]*\(([^)]*)\)", masked))
            if len(writes) == 1 and not shadowed:
                receivers[alias] = target
    for receiver, target in receivers.items():
        expression = r"(?<![\w.:])" + r"\s*\.\s*".join(map(re.escape, receiver.split(".")))
        # While generating, module.code is still empty. The candidate code
        # argument is the authoritative self-service export to inspect.
        target_code = code if target == module.name else peers[target].code
        table, exports = exported_methods(target_code) if target_code else (None, {})
        exported = exports if table else None
        available = set(exported) if exported is not None else None
        declared_fields: set[str] = set()
        if target_code and table:
            target_source = _mask_strings(_without_comments(target_code))
            declared_fields = set(re.findall(
                r"\b" + re.escape(table) +
                r"\s*\.\s*(" + _NAME + r")\s*=(?!=)",
                target_source,
            ))
        for match in re.finditer(expression + r"\s*([.:])\s*(" + _NAME + r")\b", masked):
            prefix, suffix = masked[:match.start()].rstrip(), masked[match.end():]
            if prefix.endswith((".", ":")):
                continue
            separator, method = match.group(1), match.group(2)
            if re.search(r"\bfunction\s*$", prefix) or re.match(r"\s*=\s*function\b", suffix):
                errors.append("DEPENDENCY_API: gameplay must not replace methods on " + target)
                continue
            if not re.match(r"\s*\(", suffix):
                # Readable state and catalogs are part of the service ABI,
                # just like callable methods. A service table exported with
                # only handleAction does NOT magically expose .crew/.catalog.
                # If a peer has not yet been generated, defer this check.
                if (available is not None and method not in available
                        and method not in declared_fields):
                    errors.append(
                        "DEPENDENCY_STATE_FIELD_UNDECLARED: " + target +
                        "." + method + " has no exported method or initialized "
                        "field; actual exports: " +
                        (", ".join(sorted(available | declared_fields)) or "(none)")
                    )
                continue
            if method == "handleAction" and target != module.name:
                # The gateway owns authenticated Remote dispatch. Calling a
                # peer's handler is NOT a reusable transaction API: it may
                # double-spend resources, bypass that peer's validated typed
                # args or spoof a client action. A model must implement its
                # own effect against approved state, not forward to a random
                # sibling action handler.
                errors.append(
                    "DEPENDENCY_ACTION_DISPATCH_FORBIDDEN: " + target +
                    ".handleAction is a host-routed ingress, not a callable "
                    "cross-gameplay service API"
                )
            elif method == "start":
                errors.append("DEPENDENCY_API: only the host bootstrap may call " + target + ".start(services)")
            elif available is not None and method not in available:
                errors.append("DEPENDENCY_API: " + target + "." + method +
                              " is not exported; actual methods: " + ", ".join(sorted(available - {"start"})))
            elif (separator == ":" and exported is not None
                  and method in exported
                  and exported[method]["separator"] == "."
                  and not re.match(r"self\b", exported[method]["params"])):
                errors.append("DEPENDENCY_API: " + target + "." + method +
                              " is exported as a dot function without self; "
                              "calling it with ':' silently shifts every argument")
    return sorted(set(errors))


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
        for index, error in enumerate(dependency_api_errors(caller, proposal, caller.code)):
            checks.append({"id": "service.dependencyApi." + caller.name + "." + str(index),
                           "passed": False, "detail": error})
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
