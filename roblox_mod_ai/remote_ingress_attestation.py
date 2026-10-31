"""Verify every declaratively routed game Remote has one real server ingress.

The host compiler owns RMMServerBootstrap. This source-only check verifies
that each planned Remote has its actual kind, named authoritative service,
bounded argument ingress and live handler invocation. It is NOT a Roblox
Studio or Cloud engine test and does not imply a gameplay effect executed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def verify_remote_ingress(proposal: Any, source_root: Path) -> dict:
    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design") or {}
    failures: list[str] = []
    checked: list[dict] = []
    if not isinstance(design, dict):
        return {"passed": False, "checked": [], "failures": ["invalid_dynamic_design"],
                "scope": "server_ingress_source_not_studio"}
    routes = design.get("host_actions", {})
    declared = design.get("remotes", {})
    if not isinstance(routes, dict) or not isinstance(declared, dict):
        return {"passed": False, "checked": [], "failures": ["invalid_remote_roster"],
                "scope": "server_ingress_source_not_studio"}
    if not routes:
        return {"passed": True, "checked": [], "failures": [],
                "status": "not_applicable", "declared_route_count": 0,
                "scope": "server_ingress_source_not_studio"}
    root = Path(source_root)
    bootstrap = root / "src/server/RMMServerBootstrap.server.luau"
    if not bootstrap.is_file():
        return {"passed": False, "checked": [], "failures": ["missing_server_bootstrap"],
                "status": "failed", "declared_route_count": len(routes),
                "scope": "server_ingress_source_not_studio"}
    try:
        source = bootstrap.read_text(encoding="utf-8")
    except (UnicodeError, OSError):
        return {"passed": False, "checked": [], "failures": ["unreadable_server_bootstrap"],
                "status": "failed", "declared_route_count": len(routes),
                "scope": "server_ingress_source_not_studio"}
    # The host emits one top-level do..end block per Remote; nested "end"s
    # are indented, so do not confuse them with the actual block boundary.
    blocks = re.findall(r"(?ms)^do\s*\n(.*?)^end\s*$", source)
    modules = list(getattr(proposal, "modules", ()) or ())
    module_by_name = {getattr(m, "name", None): m for m in modules}
    for remote, route in sorted(routes.items(), key=lambda kv: str(kv[0])):
        issue: list[str] = []
        if not isinstance(remote, str) or not isinstance(route, dict):
            failures.append("malformed_route:" + str(remote)[:80])
            continue
        service_name = route.get("service")
        kind = route.get("kind")
        cap = route.get("max_args")
        if not isinstance(service_name, str) or not isinstance(cap, int) or not 0 <= cap <= 16:
            issue.append("invalid_owner_or_arg_limit")
        if kind not in ("RemoteFunction", "RemoteEvent") or declared.get(remote) != kind:
            issue.append("wrong_declared_remote_class")
        if [m.name for m in modules if isinstance(getattr(m, "name", None), str)].count(service_name) != 1:
            issue.append("missing_or_ambiguous_service")
        # Quote as pure data to prevent a route name manipulating a regex.
        candidates = [block for block in blocks
            if re.search(r'\bremote\s*=\s*remotes:WaitForChild\(\s*["\']'
                         + re.escape(remote) + r'["\']\s*,', block)]
        if len(candidates) != 1:
            issue.append("missing_or_duplicated_ingress")
        elif not issue:
            block = candidates[0]
            if not re.search(r'remote:IsA\(\s*["\']' + re.escape(kind)
                             + r'["\']\s*\)', block):
                issue.append("unverified_runtime_remote_class")
            if not re.search(r'local\s+service\s*=\s*services\[\s*["\']'
                             + re.escape(service_name) + r'["\']\s*\]', block):
                issue.append("wrong_server_owner_binding")
            if not re.search(r'if\s+not\s+safeWireArgs\(\s*\.\.\.\s*\)', block):
                issue.append("missing_wire_validation")
            if not re.search(r'select\(\s*["\']#["\']\s*,\s*\.\.\.\s*\)\s*>\s*'
                             + str(cap) + r'\b', block):
                issue.append("missing_argument_cap")
            call = r'service\.handleAction\(\s*player\s*,\s*services\s*,\s*\.\.\.\s*\)'
            if kind == "RemoteFunction":
                if not re.search(r'remote\.OnServerInvoke\s*=\s*function\(\s*player\s*,\s*\.\.\.\s*\)', block):
                    issue.append("missing_server_invocation")
                if not re.search(r'return\s+' + call, block):
                    issue.append("missing_server_handler")
            elif kind == "RemoteEvent":
                if not re.search(r'remote\.OnServerEvent:Connect\(\s*function\(\s*player\s*,\s*\.\.\.\s*\)', block):
                    issue.append("missing_server_event")
                if not re.search(call, block):
                    issue.append("missing_server_handler")
            module = module_by_name.get(service_name)
            module_path = getattr(module, "file_path", "") if module is not None else ""
            if not isinstance(module_path, str) or not module_path.startswith("src/server/"):
                issue.append("invalid_server_module_path")
            else:
                path = root / module_path
                if not path.is_file():
                    issue.append("server_module_missing_from_disk")
                elif not re.search(r'function\s+Service\.handleAction\s*\(', path.read_text(encoding="utf-8")):
                    issue.append("server_action_handler_missing")
        if issue:
            failures.extend(f"{remote}:{reason}" for reason in issue)
        checked.append({"remote": remote, "service": service_name, "kind": kind,
                        "source_verified": not issue, "issues": issue})
    return {"schema": "rmm/server-remote-ingress-v1", "executed": True,
            "passed": not failures, "checked": checked, "failures": failures,
            "status": "failed" if failures else "verified",
            "declared_route_count": len(routes),
            "scope": "server_ingress_source_not_studio"}
