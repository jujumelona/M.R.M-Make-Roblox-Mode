"""Static cross-boundary wiring audit for model-generated Roblox gameplay.

Scope is intentionally narrow: direct, locally-bound RemoteEvent/RemoteFunction
bindings. A remote whose code cannot be traced from client to server is NOT
presumed to work. This is source-level E2E wiring, not an engine playtest.
"""
from __future__ import annotations

import re
from typing import Any

from .spec import RobloxProposal

# The remote must be bound to a named local. This rejects an unused literal
# or a mention of a Remote name in a comment as proof of a working connection.
_BINDING = re.compile(
    r'\blocal\s+([A-Za-z_]\w*)\s*(?::[^=\n]+)?=\s*'
    r'[^\n]*?\b(?:WaitForChild|FindFirstChild)\s*\(\s*["\']([^"\']+)["\']\s*\)',
)
_USAGE = {
    "RemoteEvent": (r"\b{v}\.OnServerEvent\s*:\s*Connect\s*\(",
                    r"\b{v}\s*:\s*FireServer\s*\("),
    "RemoteFunction": (r"\b{v}\.OnServerInvoke\s*=",
                       r"\b{v}\s*:\s*InvokeServer\s*\("),
}

def _source_without_comments(source: str) -> str:
    # Preserve quoted strings for WaitForChild("Name") binding. Strip only
    # whole-line comments; inline notes cannot create valid executable calls.
    return "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("--"))

def inspect_dynamic_remote_wiring(proposal: RobloxProposal) -> dict[str, Any]:
    dynamic = proposal.game_design.get("dynamic_design") or {}
    declared = dynamic.get("remotes", {})
    checks = []
    for name, kind in declared.items():
        endpoints = {"server_receiver": [], "client_sender": []}
        patterns = _USAGE.get(kind)
        if patterns is None:
            checks.append({"id":f"wiring.{name}", "passed":False,
                           "detail":"Unsupported dynamic Remote type"})
            continue
        for mod in proposal.modules:
            if not mod.module_id.startswith("dyn_"):
                continue
            source = _source_without_comments(mod.code)
            bound = [var for var,remote in _BINDING.findall(source) if remote == name]
            for variable in bound:
                receiver, sender = (pattern.format(v=re.escape(variable))
                                    for pattern in patterns)
                if (mod.file_path.endswith(".server.luau") and
                        re.search(receiver, source)):
                    endpoints["server_receiver"].append(mod.file_path)
                if (mod.file_path.endswith(".client.luau") and
                        re.search(sender, source)):
                    endpoints["client_sender"].append(mod.file_path)
        valid = bool(endpoints["server_receiver"] and endpoints["client_sender"])
        checks.append({"id":f"wiring.{name}", "passed":valid,
                       "detail":endpoints if valid else
                       {**endpoints,"reason":"Missing bound client sender or server receiver"}})
    return {"passed":all(c["passed"] for c in checks), "checks":checks,
            "scope":"static_remote_wiring_not_gameplay_execution"}
