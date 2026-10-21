"""Source-owned mode/planet navigation, not free-form model UI.

A mode setup client cannot invent action names absent from its server ABI.
The model supplies *only* an optional finite planet catalog; this adapter
owns validated mode-state lookup, selection and UI. No model Luau or fake
resource/coin deductions. Launch and combat remain their separate owners.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .host_catalog_purchase import _ID
from .spec import ModuleKind

_SCHEMA={"type":"object","properties":{"planets":{"type":"array","items":{
    "type":"object","properties":{"id":{"type":"string"},"label":{"type":"string"}},
    "required":["id","label"]}}},"required":["planets"]}

def eligible_mode_navigation(module:Any,proposal:Any)->tuple[str,str,str]|None:
    if (not getattr(module,"module_id","").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT)):
        return None
    owner_name=(module.name if module.kind==ModuleKind.SERVER_MODULE
                else module.name.removesuffix("Client")+"Server")
    owner=next((x for x in getattr(proposal,"modules",())
                if x.kind==ModuleKind.SERVER_MODULE and x.name==owner_name),None)
    client=next((x for x in getattr(proposal,"modules",())
                 if x.kind==ModuleKind.CLIENT_SCRIPT
                 and x.name==owner_name.removesuffix("Server")+"Client"),None)
    if owner is None or client is None:return None
    desc=owner.description.casefold()
    client_desc=client.description.casefold()
    mode=re.search(r"\bdedicated\s+([a-z][a-z0-9-]{1,24})[- ]mode\s+state\b",desc)
    if (not mode or not re.search(r"\bvalidat\w*\b",desc)
        or not re.search(r"\bplanet\s+selection\b",desc)
        or not re.search(r"\bprogression\b",desc)
        or not re.search(r"\bmode\s+transition\b",desc)
        or not re.search(r"\bmode\s+state\b",client_desc)
        or not re.search(r"\bplanet\s+selection\b",client_desc)
        or not re.search(r"\bprogression\s+feedback\b",client_desc)):
        return None
    design=proposal.game_design.get("dynamic_design") or {}
    routes=[(key,value) for key,value in (design.get("host_actions") or {}).items()
            if isinstance(value,dict) and value.get("service")==owner_name]
    if len(routes)!=1:return None
    remote,route=routes[0]
    max_args=route.get("max_args")
    if (route.get("kind")!="RemoteFunction"
        or (design.get("remotes") or {}).get(remote)!="RemoteFunction"
        or (max_args is not None and (type(max_args) is not int or max_args<2))):
        return None
    for x in (owner,client):
        linked=(design.get("module_remotes") or {}).get(x.module_id)
        if linked is not None and remote not in linked:return None
    if module.kind==ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):return None
    else:
        if module.name!=client.name or not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):return None
    return owner_name,remote,mode.group(1).replace("-"," ").title()+" Mode"

def _validate(value:Any)->list[dict[str,str]]:
    raw=value.get("planets") if isinstance(value,dict) else None
    if not isinstance(raw,list) or not 2<=len(raw)<=5:
        raise ValueError("MODE_PLANET_CATALOG_REQUIRES_2_TO_5_ENTRIES")
    clean,ids=[],set()
    for row in raw:
        if not isinstance(row,dict):raise ValueError("MODE_PLANET_INVALID_ENTRY")
        pid,label=row.get("id"),row.get("label")
        if (not isinstance(pid,str) or not _ID.fullmatch(pid)
            or pid.casefold() in ids or not isinstance(label,str)
            or not 1<=len(label.strip())<=60):
            raise ValueError("MODE_PLANET_INVALID_ENTRY")
        ids.add(pid.casefold())
        clean.append({"id":pid,"label":label.strip()})
    return clean

def _read(proposal:Any,owner:str,router:Any)->list[dict[str,str]]:
    cache=proposal.game_design.setdefault("_host_mode_planet_catalog",{})
    if owner in cache:return _validate({"planets":cache[owner]})
    if router is None or not hasattr(router,"complete_json"):
        raise ValueError("MODE_PLANET_CATALOG_UNAVAILABLE")
    desc=next(m.description for m in proposal.modules if m.name==owner)
    prompt=("Return ONLY JSON {planets:[{id,label}]} with 2-5 distinct planets. "
            "Stable ASCII IDs and concise player-facing labels. These are "
            "actual selectable planet regions; the host creates their world "
            "representations and enforces all state transitions. No Lua code, "
            "no Remote names, no prices, rewards, combat, or colonization "
            "permissions. Authored requirement: "+desc[:850])
    last=""
    for _ in range(2):
        try:
            data=router.complete_json(prompt+("\nFix invalid catalog: "+last if last else ""),
                role="planner",temperature=0,max_tokens=550,json_schema=_SCHEMA)
            result=_validate(data)
            cache[owner]=result
            return result
        except Exception as exc:last=str(exc)[:170]
    raise ValueError("MODE_PLANET_CATALOG_EXHAUSTED: "+last)

def try_mode_navigation(module:Any,proposal:Any,router:Any=None)->str|None:
    matched=eligible_mode_navigation(module,proposal)
    if matched is None:return None
    owner,remote,mode=matched
    planets=_read(proposal,owner,router)
    if module.kind==ModuleKind.CLIENT_SCRIPT:
        rows=",\n".join("{id="+json.dumps(p["id"])+",label="+json.dumps(p["label"],ensure_ascii=False)+"}"
                       for p in planets)
        return (_CLIENT.replace("__REMOTE__",json.dumps(remote))
                .replace("__MODE__",json.dumps(mode))
                .replace("__PLANETS__",rows))
    rows=",\n".join("["+json.dumps(p["id"])+"]={label="+json.dumps(p["label"],ensure_ascii=False)
                    +",order="+str(i+1)+"}" for i,p in enumerate(planets))
    return _SERVER.replace("__MODE__",json.dumps(mode)).replace("__PLANETS__",rows)

_SERVER=r'''--!strict
-- Navigation never fabricates unlocks: the actual launch service sets inSpace.
local Players=game:GetService("Players")
local Service={}
local MODE=__MODE__
local PLANETS={__PLANETS__}
local function deny(reason) return {success=false,reason=reason} end
local function modeState(player,services)
    local manager=services.PlayerDataManager
    if type(manager)~="table" or type(manager.GetState)~="function" then return nil end
    local mode=manager.GetState(player,"RMMGameMode")
    local travel=manager.GetState(player,"RMMTravelProgress")
    local selection=manager.GetState(player,"RMMPlanetSelection")
    if type(mode)~="table" or type(travel)~="table" or type(selection)~="table" then return nil end
    return mode,travel,selection
end
local function status(player,services)
    local mode,travel,selection=modeState(player,services)
    if not mode then return deny("profile_loading") end
    local launched=travel.inSpace==true
    local active=launched and mode.activeMode==MODE
    local chosen=selection.planetId
    if type(chosen)~="string" or PLANETS[chosen]==nil then chosen=nil end
    player:SetAttribute("RMMInSpace",launched)
    player:SetAttribute("RMMActiveGameMode",mode.activeMode)
    player:SetAttribute("RMMSelectedPlanet",chosen)
    return {success=true,action="status",mode=mode.activeMode,
        inSpace=launched,active=active,planet=chosen}
end
function Service.start(services)
    assert(type(services)=="table"
        and type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function"
        and type(services.PlayerDataManager.OnReady)=="function",
        "Space setup needs real server-owned profile")
    -- Planet navigation is a real selectable catalog, not invented UI IDs.
    local root=workspace:FindFirstChild("RMMSelectablePlanets")
    if root==nil then
        root=Instance.new("Folder")
        root.Name="RMMSelectablePlanets"
        root.Parent=workspace
    end
    assert(root:IsA("Folder"),"Planet region name occupied")
    for id,entry in pairs(PLANETS) do
        local part=root:FindFirstChild(id)
        if not part then
            part=Instance.new("Part")
            part.Name=id
            part.Shape=Enum.PartType.Ball
            part.Anchored=true
            part.Size=Vector3.new(36,36,36)
            part.Position=Vector3.new(entry.order*140,800,0)
            part:SetAttribute("RMMPlanetId",id)
            part:SetAttribute("RMMPlanetName",entry.label)
            part.Parent=root
        end
        assert(part:IsA("BasePart") and part:GetAttribute("RMMPlanetId")==id,
            "Planet ID occupied by incompatible object")
    end
    services.PlayerDataManager.OnReady(function(player)
        status(player,services)
    end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players then return deny("invalid_player") end
    local n=select("#",...)
    if n==1 then
        local action=...
        if action=="status" then return status(player,services) end
        return deny("invalid_action")
    end
    if n~=2 then return deny("invalid_arity") end
    local action,planetId=...
    if action~="select" or type(planetId)~="string" or
        PLANETS[planetId]==nil then return deny("invalid_planet") end
    local mode,travel,selection=modeState(player,services)
    if not mode then return deny("profile_loading") end
    if travel.inSpace~=true or mode.activeMode~=MODE then
        return deny("launch_required")
    end
    local world=workspace:FindFirstChild("RMMSelectablePlanets")
    local target=world and world:FindFirstChild(planetId)
    if not target or not target:IsA("BasePart")
        or target:GetAttribute("RMMPlanetId")~=planetId then
        return deny("planet_not_available")
    end
    if selection.planetId==planetId then return deny("already_selected") end
    selection.planetId=planetId
    player:SetAttribute("RMMSelectedPlanet",planetId)
    return {success=true,action="select",planet=planetId,
        label=PLANETS[planetId].label,inSpace=true}
end
return Service
'''
_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remote=ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
if not remote:IsA("RemoteFunction") then error("Mode remote type mismatch") end
local gui=Instance.new("ScreenGui")
gui.Name="RMMModeNavigation"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local panel=Instance.new("Frame")
panel.Size=UDim2.fromOffset(260,290)
panel.Position=UDim2.new(1,-280,0,130)
panel.Parent=gui
local layout=Instance.new("UIListLayout")
layout.Parent=panel
local feedback=Instance.new("TextLabel")
feedback.Size=UDim2.new(1,0,0,60)
feedback.Text=__MODE__.." | Launch required for planet navigation"
feedback.TextWrapped=true
feedback.Parent=panel
local busy=false
local function request(action,id)
    if busy then return end
    busy=true
    local ok,result=pcall(function()
        if id==nil then return remote:InvokeServer(action) end
        return remote:InvokeServer(action,id)
    end)
    busy=false
    if not ok or type(result)~="table" then
        feedback.Text="Mode state unavailable"
        return
    end
    if result.success~=true then
        feedback.Text="Rejected: "..tostring(result.reason or "unknown")
        return
    end
    if action=="status" then
        feedback.Text="In space: "..tostring(result.inSpace)..
            " | Selected planet: "..tostring(result.planet or "none")
    else
        feedback.Text="Selected planet: "..tostring(result.label)
    end
end
local statusButton=Instance.new("TextButton")
statusButton.Size=UDim2.new(1,0,0,38)
statusButton.Text="Refresh mode and progression"
statusButton.Parent=panel
statusButton.Activated:Connect(function()request("status",nil)end)
local planets={__PLANETS__}
for _,planet in planets do
    local button=Instance.new("TextButton")
    button.Name=planet.id
    button.Text="Select "..planet.label
    button.Size=UDim2.new(1,0,0,36)
    button.Parent=panel
    button.Activated:Connect(function()request("select",planet.id)end)
end
task.defer(function()request("status",nil)end)
'''