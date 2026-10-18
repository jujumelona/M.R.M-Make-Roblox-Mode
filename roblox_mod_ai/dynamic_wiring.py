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
_LOOKUP = re.compile(r'\b(?:WaitForChild|FindFirstChild)\s*\(\s*["\']([^"\']+)["\']\s*\)')
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
        valid=any(e["client"] and e["server"] for e in endpoints.values())
        checks.append({"id":"wiring."+name,"passed":bool(valid),
                       "detail":{"endpoints":endpoints,"scope":"static_source_only"}})
    return {"passed":all(c["passed"] for c in checks),"checks":checks,
            "scope":"static_remote_wiring_not_gameplay_execution"}
