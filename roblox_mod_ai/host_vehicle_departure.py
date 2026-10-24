"""Host-owned departure uses the ACTUAL assembled player Model, not dummy Parts.

Source-linked builder must export GetOwnedActor(player). The destination is
an actual materialized Part with a unique arrival/landing identity.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .spec import ModuleKind
from .host_ordered_assembly import eligible_ordered_assembly

_NAME=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,90}$")

def eligible_departure(m:Any,p:Any)->tuple[str,str,str,str]|None:
    if not m.module_id.startswith("dyn_") or m.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT):return None
    server=m.name if m.kind==ModuleKind.SERVER_MODULE else m.name.removesuffix("Client")+"Server"
    d=p.game_design.get("dynamic_design") or {}
    motion=(d.get("host_world_motion") or {}).get(server)
    if not isinstance(motion,dict) or motion.get("kind")!="vehicle_world_transition":return None
    builder=next((x for x in p.modules if x.module_id==motion.get("builder_module_id")),None)
    if builder is None or not _NAME.fullmatch(builder.name):return None
    if eligible_ordered_assembly(builder,p) is None:return None
    routes=[(k,v) for k,v in (d.get("host_actions") or {}).items()
            if isinstance(v,dict) and v.get("service")==server]
    if len(routes)!=1:return None
    remote,route=routes[0]
    if route.get("kind")!="RemoteFunction" or (d.get("remotes") or {}).get(remote)!="RemoteFunction":return None
    form=((d.get("host_typed_actions") or {}).get(remote) or (d.get("host_launch_contracts") or {}).get(remote))
    if not isinstance(form,dict) or form.get("transport_only") is not True:return None
    if form.get("client")!=server.removesuffix("Server")+"Client":return None
    owner=next((x for x in p.modules if x.name==server),None)
    if owner is None:return None
    refs=(d.get("module_world_objects") or {}).get(owner.module_id) or []
    classes={obj.get("name"):obj.get("class") for obj in d.get("world_objects",[]) if isinstance(obj,dict)}
    arrival=[name for name in refs if isinstance(name,str)
             and re.search(r"arrival|landing",name,re.I)
             and classes.get(name) in {"Part","MeshPart"}]
    if len(arrival)!=1:return None
    if m.kind==ModuleKind.CLIENT_SCRIPT and not m.file_path.endswith(".client.luau"):return None
    if m.kind==ModuleKind.SERVER_MODULE and not m.file_path.startswith("src/server/"):return None
    links=(d.get("module_remotes") or {}).get(m.module_id)
    if links is not None and links!=[remote]:return None
    return server,remote,builder.name,arrival[0]

def render_departure(m:Any,p:Any,router:Any=None)->str|None:
    spec=eligible_departure(m,p)
    if spec is None:return None
    _,remote,builder,arrival=spec
    code=_SERVER if m.kind==ModuleKind.SERVER_MODULE else _CLIENT
    return (code.replace("@BUILDER@",builder)
            .replace("@REMOTE@",json.dumps(remote))
            .replace("@DESTINATION@",json.dumps(arrival)))

_SERVER=r'''--!strict
local Players=game:GetService("Players")
local Service={}
local destinationName=@DESTINATION@
local recent={}
function Service.start(services)
    assert(type(services.@BUILDER@)=="table"
        and type(services.@BUILDER@.GetOwnedActor)=="function")
    Players.PlayerRemoving:Connect(function(player) recent[player]=nil end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players or select("#",...)~=1 or (...)~="launch" then
        return {success=false,reason="invalid_input"} end
    local vehicle=services.@BUILDER@.GetOwnedActor(player)
    if not vehicle or not vehicle:IsA("Model") or vehicle.Parent==nil
        or vehicle:GetAttribute("OwnerUserId")~=player.UserId then
        return {success=false,reason="vehicle_incomplete"} end
    local seat=vehicle:FindFirstChild("PilotSeat")
    local humanoid=player.Character and player.Character:FindFirstChildOfClass("Humanoid")
    if not seat or not seat:IsA("VehicleSeat") or not humanoid
        or seat.Occupant~=humanoid then return {success=false,reason="not_aboard"} end
    local destination=workspace:FindFirstChild(destinationName)
    if not destination or not destination:IsA("BasePart") then
        return {success=false,reason="missing_destination"} end
    local now=os.clock()
    if recent[player] and now-recent[player]<1 then
        return {success=false,reason="cooldown"} end
    recent[player]=now
    vehicle:PivotTo(destination.CFrame * CFrame.new(0,16,0))
    return {success=true,vehicle=vehicle.Name,destination=destinationName}
end
return Service
'''

_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local Storage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local folder=Storage:WaitForChild("Remotes",20)
if not folder then error("Missing Remotes") end
local remote=folder:WaitForChild(@REMOTE@,20)
if not remote or not remote:IsA("RemoteFunction") then error("Bad departure Remote") end
local gui=Instance.new("ScreenGui")
gui.Name="RMMVehicleDeparture"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local button=Instance.new("TextButton")
button.Size=UDim2.fromOffset(250,60)
button.Position=UDim2.new(1,-270,0,350)
button.Text="Launch assembled vehicle"
button.Parent=gui
local info=Instance.new("TextLabel")
info.Size=UDim2.fromOffset(250,48)
info.Position=UDim2.new(1,-270,0,415)
info.Text=""
info.Parent=gui
local busy=false
button.Activated:Connect(function()
    if busy then return end
    busy=true
    local ok,result=pcall(function() return remote:InvokeServer("launch") end)
    if not ok or type(result)~="table" then info.Text="Network error"
    elseif result.success then info.Text="Vehicle arrived"
    else info.Text=tostring(result.reason or "Rejected") end
    busy=false
end)
'''
