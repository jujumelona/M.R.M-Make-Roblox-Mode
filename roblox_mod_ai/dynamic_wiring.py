"""Conservative Luau client/server Remote source-wiring audit.

Supports direct local bindings through WaitForChild/FindFirstChild or .RemoteName,
and Roblox bidirectional RemoteEvent/RemoteFunction patterns. No true gameplay
execution is implied by successful static connectivity.
"""
from __future__ import annotations
import re
from typing import Any
from .spec import RobloxProposal

_ASSIGN = re.compile(r'\blocal\s+([A-Za-z_]\w*)\s*(?::[^=\n]+)?=\s*([^\n]+)')
_LOOKUP = re.compile(r'\b(?:WaitForChild|FindFirstChild)\s*\(\s*["']([^"']+)["']\s*(?:,\s*\d+(?:\.\d+)?\s*)?\)')
_MODES = {
    "RemoteEvent": (
        ("client_to_server",
         r"\b{v}\s*:\s*FireServer\s*\(",
         r"\b{v}\.OnServerEvent\s*:\s*Connect\s*\("),
        ("server_to_client",
         r"\b{v}\.OnClientEvent\s*:\s*Connect\s*\(",
         r"\b{v}\s*:\s*(?:FireClient|FireAllClients)\s*\("),
    ),
    "RemoteFunction": (
        ("client_to_server",
         r"\b{v}\s*:\s*InvokeServer\s*\(",
         r"\b{v}\.OnServerInvoke\s*="),
        ("server_to_client",
         r"\b{v}\.OnClientInvoke\s*=",
         r"\b{v}\s*:\s*InvokeClient\s*\("),
    ),
}

def _long_bracket_end(source: str, start: int) -> int | None:
    """End offset for Luau/Lua [=[...]=] literals, if one begins at start."""
    opener = re.match(r"\[(=*)\[", source[start:])
    if opener is None:
        return None
    closing = "]" + opener.group(1) + "]"
    end = source.find(closing, start + len(opener.group()))
    return len(source) if end < 0 else end + len(closing)


def _without_comments(code: str) -> str:
    # Strip Luau end-of-line comments outside quotes; avoid a commented-out
    # FireServer or a URL containing -- giving false positives.
    out=[]
    i=0
    quote=None
    block=False
    while i<len(code):
        c=code[i]
        if block:
            if code.startswith("]]",i):
                block=False
                out.extend("  ")
                i+=2
            else:
                out.append("\n" if c=="\n" else " ")
                i+=1
            continue
        if quote is not None:
            out.append(c)
            if c=="\\" and i+1<len(code):
                out.append(code[i+1])
                i+=2
                continue
            if c==quote: quote=None
            i+=1
            continue
        if c in ("'",'"'):
            quote=c
            out.append(c)
            i+=1
            continue
        if code.startswith("--[", i):
            end = _long_bracket_end(code, i + 2)
            if end is not None:
                out.extend("\n" if char == "\n" else " " for char in code[i:end])
                i = end
                continue
        if c == "[":
            end = _long_bracket_end(code, i)
            if end is not None:
                # Long bracket strings can contain '--' and quotes, but
                # those bytes must not start executable comments.
                out.extend(code[i:end])
                i = end
                continue
        if code.startswith("--[[",i):
            block=True
            out.extend("    ")
            i+=4
            continue
        if code.startswith("--",i):
            end=code.find("\n",i)
            if end<0:
                out.extend(" "*(len(code)-i))
                break
            out.extend(" "*(end-i))
            i=end
            continue
        out.append(c)
        i+=1
    return "".join(out)

def _mask_strings(source: str) -> str:
    # Usage patterns must not match text like print("remote:FireServer()").
    out=[]
    quote=None
    i=0
    while i<len(source):
        c=source[i]
        if quote:
            if c=="\\" and i+1<len(source):
                out.extend("  ")
                i+=2
                continue
            if c==quote: quote=None
            out.append(" ")
        elif c == "[" and (end := _long_bracket_end(source, i)) is not None:
            out.extend("\n" if char == "\n" else " " for char in source[i:end])
            i = end
            continue
        elif c in ("'",'"'):
            quote=c
            out.append(" ")
        else:
            out.append(c)
        i+=1
    return "".join(out)

def _variables(source: str, remote_name: str) -> list[str]:
    found=[]
    for variable, value in _ASSIGN.findall(source):
        lookups=_LOOKUP.findall(value)
        # A chained Remotes:WaitForChild("HatchPet") must use LAST lookup.
        final_lookup=bool(lookups) and lookups[-1]==remote_name
        direct_access=bool(re.search(
            r'\.\s*'+re.escape(remote_name)+r'\b|\[\s*["\']'+
            re.escape(remote_name)+r'["\']\s*\]',value))
        if final_lookup or direct_access:
            found.append(variable)
    return found

def inspect_dynamic_remote_wiring(proposal: RobloxProposal) -> dict[str, Any]:
    dynamic=proposal.game_design.get("dynamic_design") or {}
    checks=[]
    for name,kind in dynamic.get("remotes",{}).items():
        patterns=_MODES.get(kind)
        if patterns is None:
            checks.append({"id":"wiring."+name,"passed":False,
                           "detail":"Unsupported Remote class"})
            continue
        endpoints={"client_to_server":{"client":[],"server":[]},
                   "server_to_client":{"client":[],"server":[]}}
        for module in proposal.modules:
            if not module.module_id.startswith("dyn_"): continue
            filtered=_without_comments(module.code)
            masked=_mask_strings(filtered)
            variables=_variables(filtered,name)
            if not variables: continue
            for direction,client_pattern,server_pattern in patterns:
                for variable in variables:
                    var=re.escape(variable)
                    if (module.file_path.endswith(".client.luau")
                            and re.search(client_pattern.format(v=var),masked)):
                        endpoints[direction]["client"].append(module.file_path)
                    if (module.file_path.startswith("src/server/")
                            and module.file_path.endswith(".luau")
                            and re.search(server_pattern.format(v=var),masked)):
                        endpoints[direction]["server"].append(module.file_path)
        # Semantic architecture owns the transport at the HOST bootstrap.
        # Server feature modules only export gameplay handleAction and must
        # never invent/duplicate OnServerEvent listeners. Verify the gateway
        # source and target before crediting the server endpoint.
        host_actions = dynamic.get("host_actions") or {}
        binding = host_actions.get(name)
        host_ready = False
        if isinstance(binding, dict):
            target = next((
                m for m in proposal.modules if
                m.module_id.startswith("dyn_") and
                m.name == binding.get("service") and
                m.file_path.startswith("src/server/")
            ), None)
            bootstrap = next((
                m for m in proposal.modules
                if m.module_id == "mod_dynamic_server_bootstrap"
            ), None)
            if (target is not None and bootstrap is not None
                    and binding.get("kind") == kind):
                code = _without_comments(bootstrap.code)
                # Each action is generated with a separately scoped do block
                # and named binding; verify both explicit literal references.
                # The host uses a bounded WaitForChild(name, timeout), while
                # older gateways used WaitForChild(name). Both bind the exact
                # same Remote; do not let formatting or the timeout create a
                # false missing-server-endpoint diagnosis.
                lookup = (
                    r'\bremotes\s*:\s*WaitForChild\s*\(\s*'
                    + re.escape('"' + name + '"')
                    + r'\s*(?:,\s*\d+(?:\.\d+)?\s*)?\)'
                )
                gateway_method = ("OnServerEvent" if kind == "RemoteEvent"
                                  else "OnServerInvoke")
                host_ready = (
                    bool(re.search(lookup, code)) and gateway_method in code
                    and 'service.handleAction(player, services, ...)' in code
                    and bool(re.search(
                        r"\bfunction\s+[A-Za-z_]\w*\.handleAction\s*\(",
                        _mask_strings(_without_comments(target.code)),
                    ))
                )
                if host_ready:
                    endpoints["client_to_server"]["server"].append(
                        bootstrap.file_path)
            checks.append({
                "id": "wiring.hostGateway." + name,
                "passed": host_ready,
                "detail": "Host bootstrap must bind the exact declared Remote "
                          "and delegate to this service's exported handler",
            })
        valid=any(e["client"] and e["server"] for e in endpoints.values())
        checks.append({"id":"wiring."+name,"passed":bool(valid),
                       "detail":{"endpoints":endpoints,"scope":"static_source_only"}})
        # A valid endpoint elsewhere does not justify a module's claimed
        # ownership. Check every explicit source-anchored owner independently.
        declared_owners = dynamic.get("module_remotes") or {}
        for module in proposal.modules:
            if not module.module_id.startswith("dyn_"):
                continue
            if name not in declared_owners.get(module.module_id, []):
                continue
            is_client = module.file_path.endswith(".client.luau")
            is_server = module.file_path.startswith("src/server/") and (
                module.file_path.endswith(".luau"))
            required_role = "client" if is_client else "server" if is_server else ""
            owns_endpoint = bool(required_role) and any(
                group[required_role] and module.file_path in group[required_role]
                for group in endpoints.values()
            )
            if (required_role == "server" and isinstance(binding, dict)
                    and binding.get("service") == module.name):
                owns_endpoint = host_ready
            checks.append({
                "id": "wiring.owner." + module.name + "." + name,
                "passed": owns_endpoint,
                "detail": "Declared owner must actually invoke or receive its Remote "
                          + "using a valid " + kind + " method",
            })
        # Even if the proper sender and receiver exist, an additional invalid
        # remote method in another module is still a guaranteed Roblox runtime
        # error (RemoteEvent:InvokeServer, RemoteFunction:FireServer, etc).
        allowed = {
            "RemoteEvent": {
                "client": {"FireServer", "OnClientEvent"},
                "server": {"OnServerEvent", "FireClient", "FireAllClients"},
            },
            "RemoteFunction": {
                "client": {"InvokeServer", "OnClientInvoke"},
                "server": {"OnServerInvoke", "InvokeClient"},
            },
        }
        methods = ("FireServer", "InvokeServer", "FireClient", "FireAllClients",
                   "InvokeClient", "OnServerEvent", "OnClientEvent",
                   "OnServerInvoke", "OnClientInvoke")
        for module in proposal.modules:
            if not module.module_id.startswith("dyn_"):
                continue
            side = ("client" if module.file_path.endswith(".client.luau")
                    else "server" if module.file_path.startswith("src/server/")
                    else "")
            if not side:
                continue
            source = _without_comments(module.code)
            masked = _mask_strings(source)
            variables = _variables(source, name)
            invalid_methods = set()
            for variable in variables:
                var = re.escape(variable)
                for method in methods:
                    delimiter = r"\s*\.\s*" if method.startswith("On") else r"\s*:\s*"
                    pattern = r"\b" + var + delimiter + method + r"\b"
                    if (re.search(pattern, masked) and
                            method not in allowed[kind][side]):
                        invalid_methods.add(method)
            if invalid_methods:
                checks.append({
                    "id": "wiring.method." + module.name + "." + name,
                    "passed": False,
                    "detail": "Invalid " + kind + " methods on " + side +
                              ": " + ", ".join(sorted(invalid_methods)),
                })
    return {"passed":all(c["passed"] for c in checks),"checks":checks,
            "scope":"static_remote_wiring_not_gameplay_execution"}
