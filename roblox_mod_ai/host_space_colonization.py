"""Host-owned alias for an already verified, physically realized space colony.

The generic bounded coder must never create a second colonization state.
"""
from __future__ import annotations
import json
import re
from .host_space_actions import render_host_space_action
from .spec import ModuleKind

def eligible_colony_alias(module, proposal):
    if not module.module_id.startswith("dyn_") or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client")+"Server"
    if not re.fullmatch(r"SpaceColonization[A-Za-z0-9_]*Server",server):return None
    request=str(getattr(proposal,"requested_prompt","") or "")
    if not re.search(r"식민지|coloniz|colony",request,re.I) or not re.search(r"우주|행성|space|planet",request,re.I):return None
    if module.kind==ModuleKind.SERVER_MODULE and not module.file_path.startswith("src/server/"):return None
    if module.kind==ModuleKind.CLIENT_SCRIPT and not module.file_path.endswith(".client.luau"):return None
    d=proposal.game_design.get("dynamic_design") or {}
    if sum(m.name==server and m.kind==ModuleKind.SERVER_MODULE for m in proposal.modules)!=1:return None
    routes=[(k,v) for k,v in (d.get("host_actions") or {}).items() if isinstance(v,dict) and v.get("service")==server]
    if len(routes)!=1:return None
    remote,route=routes[0]
    if route.get("kind")!="RemoteFunction" or route.get("max_args")==0 or (d.get("remotes") or {}).get(remote)!="RemoteFunction":return None
    spec=(d.get("host_typed_actions") or {}).get(remote)
    if not isinstance(spec,dict) or spec.get("transport_only") is not True:return None
    c=spec.get("contract") or {}
    if [(f.get("id"),f.get("type")) for f in c.get("inputs",[])]!=[("selection","text"),("quantity","integer")] or c.get("target")!={"kind":"none"}:return None
    if spec.get("server")!=server or spec.get("client")!=server.removesuffix("Server")+"Client":return None
    if (d.get("module_remotes") or {}).get(module.module_id)!=[remote]:return None
    # Source-verified MarkPlanetColonized implements RMMPlanetProgress plus a
    # persisted physical colony. A name match alone is NOT authorization.
    canonical=[m for m in proposal.modules if m.kind==ModuleKind.SERVER_MODULE
               and m.name.startswith("MarkPlanetColonized") and m.name.endswith("Server")
               and render_host_space_action(m,proposal) is not None]
    if len(canonical)!=1:return None
    return remote,canonical[0].name

def render_colony_alias(module,proposal):
    spec=eligible_colony_alias(module,proposal)
    if spec is None:return None
    remote,canonical=spec
    code=_SERVER if module.kind==ModuleKind.SERVER_MODULE else _CLIENT
    return code.replace("__CANONICAL__",json.dumps(canonical)).replace("__REMOTE__",json.dumps(remote))

_SERVER=r'''--!strict
local Players=game:GetService("Players")
local Service={}
local canonicalName=__CANONICAL__
function Service.start(services)
    assert(type(services.PlayerDataManager)=="table" and type(services.PlayerDataManager.GetState)=="function","Colony alias requires persistence")
    local owner=services[canonicalName]
    assert(type(owner)=="table" and type(owner.handleAction)=="function","Colony alias requires real colony service")
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player") or player.Parent~=Players or select("#",...)~=1 then
        return {success=false,reason="invalid_player"} end
    local args=(...)
    if typeof(args)~="table" or args.selection~="colony" or type(args.quantity)~="number" or args.quantity~=1 then
        return {success=false,reason="invalid_colony_action"} end
    for k in pairs(args) do
        if k~="selection" and k~="quantity" then return {success=false,reason="extra_colony_input"} end
    end
    local owner=services[canonicalName]
    if type(owner)~="table" or type(owner.handleAction)~="function" then
        return {success=false,reason="colony_owner_unavailable"} end
    -- Delegate ALL ownership, proximity, arrival, combat and saved settlement
    -- checks to the existing canonical server; never mint a duplicate colony.
    return owner.handleAction(player,services,{selection="planet",quantity=1})
end
return Service
'''

_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remote=ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
assert(remote:IsA("RemoteFunction"),"Colony action route unavailable")
local gui=Instance.new("ScreenGui")
gui.Name="RMMColonyAlias"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local button=Instance.new("TextButton")
button.Name="BuildColony"
button.Size=UDim2.fromOffset(210,42)
button.Position=UDim2.new(1,-230,0,540)
button.Text="Establish orbit colony"
button.Parent=gui
local status=Instance.new("TextLabel")
status.Size=UDim2.fromOffset(210,38)
status.Position=UDim2.new(1,-230,0,587)
status.Text=""
status.Parent=gui
local busy=false
button.Activated:Connect(function()
    if busy then return end
    busy=true
    local ok,result=pcall(function()
        return remote:InvokeServer({selection="colony",quantity=1})
    end)
    busy=false
    status.Text=ok and type(result)=="table" and
        (result.success and "Colony established" or tostring(result.reason))
        or "Colony request failed"
end)
'''