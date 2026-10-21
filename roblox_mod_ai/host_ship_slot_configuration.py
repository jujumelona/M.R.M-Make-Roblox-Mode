"""Server-owned independent ship sections with typed configuration choices.

The model provides only a bounded slot/type/configuration catalog.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .host_catalog_purchase import _ID
from .spec import ModuleKind

SCHEMA = {"type":"object","properties":{"slots":{"type":"array","items":{
    "type":"object","properties":{"id":{"type":"string"},"label":{"type":"string"},
    "types":{"type":"array","items":{"type":"object","properties":{
    "id":{"type":"string"},"label":{"type":"string"},
    "configurations":{"type":"array","items":{"type":"object","properties":{
    "id":{"type":"string"},"performance":{"type":"integer"}},
    "required":["id","performance"]}}},"required":["id","label","configurations"]}}},
    "required":["id","label","types"]}}},"required":["slots"]}

def eligible_ship_slot_configuration(module:Any, proposal:Any)->tuple[str,str]|None:
    if not getattr(module,"module_id","").startswith("dyn_") or module.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT):
        return None
    server=module.name if module.kind==ModuleKind.SERVER_MODULE else module.name.removesuffix("Client")+"Server"
    owner=next((m for m in getattr(proposal,"modules",()) if m.kind==ModuleKind.SERVER_MODULE and m.name==server),None)
    if owner is None:return None
    desc=owner.description.casefold()
    required=(r"\b(?:ship|spaceship|vessel)\s+assembly\b",r"\bsections?\b",r"\bslots?\b",
              r"\bsection\s+types?\b",r"\bconfigur\w*\b",r"\b(?:create|creates|creation|add)\b",
              r"\bremov\w*\b",r"\b(?:owner|owns|owned)\b",r"\b(?:persist|save|record)\w*\b",
              r"\b(?:duplicate|invalid|reject)\w*\b")
    if not all(re.search(p,desc) for p in required):return None
    # Separate host roles own purchases and parent graphs.
    if re.search(r"\b(?:deduct|cost|price|refund|currency|coins?|credits?|spend|resources?)\b|\bparent\s+section\b",desc):return None
    design=getattr(proposal,"game_design",{}).get("dynamic_design") or {}
    routes=[(k,v) for k,v in (design.get("host_actions") or {}).items()
            if isinstance(v,dict) and v.get("service")==server]
    if len(routes)!=1:return None
    remote,binding=routes[0]
    maximum=binding.get("max_args")
    if (binding.get("kind")!="RemoteFunction" or (design.get("remotes") or {}).get(remote)!="RemoteFunction"
            or (maximum is not None and (type(maximum) is not int or maximum<4))):return None
    if module.kind==ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):return None
    else:
        if module.name!=server.removesuffix("Server")+"Client" or not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):return None
        linked=(design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:return None
    return server,remote

def _validate(value:Any)->list[dict[str,Any]]:
    rows=value.get("slots") if isinstance(value,dict) else None
    if not isinstance(rows,list) or not 1<=len(rows)<=8:raise ValueError("SHIP_SLOT_CONFIG_INVALID_SLOTS")
    result,used=[],set()
    for slot in rows:
        if not isinstance(slot,dict):raise ValueError("SHIP_SLOT_CONFIG_INVALID_SLOT")
        sid,label,kinds=slot.get("id"),slot.get("label"),slot.get("types")
        if (not isinstance(sid,str) or not _ID.fullmatch(sid) or sid.casefold() in used
                or not isinstance(label,str) or not 1<=len(label.strip())<=50
                or not isinstance(kinds,list) or not 1<=len(kinds)<=4):
            raise ValueError("SHIP_SLOT_CONFIG_INVALID_SLOT")
        used.add(sid.casefold())
        clean_kinds,seen=[],set()
        for kind in kinds:
            if not isinstance(kind,dict):raise ValueError("SHIP_SLOT_CONFIG_INVALID_TYPE")
            tid,title,configs=kind.get("id"),kind.get("label"),kind.get("configurations")
            if (not isinstance(tid,str) or not _ID.fullmatch(tid) or tid.casefold() in seen
                    or not isinstance(title,str) or not 1<=len(title.strip())<=50
                    or not isinstance(configs,list) or not 1<=len(configs)<=4):
                raise ValueError("SHIP_SLOT_CONFIG_INVALID_TYPE")
            seen.add(tid.casefold())
            selected,seen_cfg=[],set()
            for cfg in configs:
                if (not isinstance(cfg,dict) or not isinstance(cfg.get("id"),str)
                        or not _ID.fullmatch(cfg["id"]) or cfg["id"].casefold() in seen_cfg
                        or type(cfg.get("performance")) is not int or not 0<=cfg["performance"]<=1000):
                    raise ValueError("SHIP_SLOT_CONFIG_INVALID_CONFIGURATION")
                seen_cfg.add(cfg["id"].casefold())
                selected.append({"id":cfg["id"],"performance":cfg["performance"]})
            clean_kinds.append({"id":tid,"label":title.strip(),"configurations":selected})
        result.append({"id":sid,"label":label.strip(),"types":clean_kinds})
    return result

def _read(proposal:Any,owner:str,router:Any)->list[dict[str,Any]]:
    cache=proposal.game_design.setdefault("_host_ship_slot_config",{})
    if owner in cache:return _validate({"slots":cache[owner]})
    if router is None or not hasattr(router,"complete_json"):raise ValueError("SHIP_SLOT_CONFIG_NOT_AUTHORED")
    desc=next(m.description for m in proposal.modules if m.name==owner)
    prompt=("Return ONLY JSON {slots:[{id,label,types:[{id,label,configurations:[{id,performance}]}]}]}. "
            "1-8 independent ship slots, 1-4 allowed section types per slot, 1-4 configurations per type. "
            "Stable ASCII identifiers; integer performance 0-1000 (0 when no effect). "
            "No money, resource grants, Roblox APIs, code or remotes; the host manages all ownership, "
            "persistence, world objects and client UI. Actual contract: "+desc[:1100])
    problem=""
    for _ in range(2):
        try:
            data=router.complete_json(prompt+("\nFix JSON: "+problem if problem else ""),
                                      role="planner",temperature=0,max_tokens=1350,json_schema=SCHEMA)
            rows=_validate(data)
            cache[owner]=rows
            return rows
        except Exception as exc:problem=str(exc)[:200]
    raise ValueError("SHIP_SLOT_CONFIG_CATALOG_EXHAUSTED: "+problem)

def try_ship_slot_configuration(module:Any,proposal:Any,router:Any=None)->str|None:
    claim=eligible_ship_slot_configuration(module,proposal)
    if claim is None:return None
    owner,remote=claim
    slots=_read(proposal,owner,router)
    if module.kind==ModuleKind.CLIENT_SCRIPT:
        lua=",\n".join("{id="+json.dumps(x["id"])+",label="+json.dumps(x["label"],ensure_ascii=False)+
            ",types={"+",".join("{id="+json.dumps(t["id"])+",label="+json.dumps(t["label"],ensure_ascii=False)+
            ",configs={"+",".join(json.dumps(c["id"]) for c in t["configurations"])+"}}" for t in x["types"])+"}}"
            for x in slots)
        return _CLIENT.replace("__REMOTE__",json.dumps(remote)).replace("__SLOTS__",lua)
    lua=",\n".join("["+json.dumps(x["id"])+"]={order="+str(i+1)+",types={"+
        ",".join("["+json.dumps(t["id"])+"]={configs={"+
                 ",".join("["+json.dumps(c["id"])+"]="+str(c["performance"]) for c in t["configurations"])+"}}"
                 for t in x["types"])+"}}" for i,x in enumerate(slots))
    return _SERVER.replace("__SLOTS__",lua)

_SERVER=r'''--!strict
local Players=game:GetService("Players")
local Service={}
local RULES={__SLOTS__}
local ships={}
local usedLots={}
local lots={}
local function reject(reason) return {success=false,reason=reason} end
local function stateFor(player,services)
    local manager=services.PlayerDataManager
    if type(manager)~="table" or type(manager.GetState)~="function" then return nil end
    local profile=manager.GetState(player,"RMMShipSections")
    if type(profile)~="table" then return nil end
    if profile.sections==nil then profile.sections={} end
    if type(profile.sections)~="table" then return nil end
    return profile.sections
end
local function inspect(sections)
    local count,power=0,0
    for slotId,saved in pairs(sections) do
        local rule=RULES[slotId]
        if not rule or type(saved)~="table" or saved.owned~=true
            or type(saved.typeId)~="string" or type(saved.configuration)~="string" then return nil end
        local kind=rule.types[saved.typeId]
        local points=kind and kind.configs[saved.configuration]
        if type(points)~="number" then return nil end
        count+=1
        power+=points
    end
    return {partCount=count,performance=power}
end
local function publish(player,sections)
    local summary=inspect(sections)
    if not summary then return nil end
    player:SetAttribute("RMMShipPerformance",summary.performance)
    player:SetAttribute("RMMShipAssemblyPerformance",summary.performance)
    player:SetAttribute("RMMShipPartCount",summary.partCount)
    return summary
end
local function shipFolder(player)
    local root=workspace:FindFirstChild("RMMPlayerShips")
    if not root then
        root=Instance.new("Folder")
        root.Name="RMMPlayerShips"
        root.Parent=workspace
    end
    if not root:IsA("Folder") then return nil end
    local ship=root:FindFirstChild("RMMShip_"..tostring(player.UserId))
    if ship and not ship:IsA("Model") then return nil end
    if not ship then
        ship=Instance.new("Model")
        ship.Name="RMMShip_"..tostring(player.UserId)
        ship:SetAttribute("OwnerUserId",player.UserId)
        ship.Parent=root
    end
    if ship:GetAttribute("OwnerUserId")~=player.UserId then return nil end
    local folder=ship:FindFirstChild("ConfiguredShipSlots")
    if folder and not folder:IsA("Folder") then return nil end
    if not folder then
        folder=Instance.new("Folder")
        folder.Name="ConfiguredShipSlots"
        folder.Parent=ship
    end
    if lots[player]==nil then
        local lot=0
        while usedLots[lot] do lot+=1 end
        usedLots[lot]=true
        lots[player]=lot
    end
    ships[player]=ship
    return folder,lots[player]
end
local function draw(player,sections)
    local folder,lot=shipFolder(player)
    if not folder or lot==nil then return false end
    for _,child in folder:GetChildren() do
        if child:IsA("BasePart") then child:Destroy() end
    end
    for slotId,saved in pairs(sections) do
        local def=RULES[slotId]
        local part=Instance.new("Part")
        part.Name=slotId
        part.Anchored=true
        part.Size=Vector3.new(5,2,6)
        part.Position=Vector3.new(30+(lot%10)*80+def.order*7,
            7,30+math.floor(lot/10)*80)
        part:SetAttribute("ShipSectionType",saved.typeId)
        part:SetAttribute("ShipSectionConfiguration",saved.configuration)
        part.Parent=folder
    end
    return true
end
function Service.start(services)
    assert(type(services)=="table" and type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function"
        and type(services.PlayerDataManager.OnReady)=="function",
        "Ship slots require authoritative profile")
    services.PlayerDataManager.OnReady(function(player)
        local sections=stateFor(player,services)
        if sections and inspect(sections) then
            draw(player,sections)
            publish(player,sections)
        end
    end)
    Players.PlayerRemoving:Connect(function(player)
        if ships[player] then ships[player]:Destroy();ships[player]=nil end
        local lot=lots[player]
        if lot~=nil then usedLots[lot]=nil;lots[player]=nil end
    end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player") or
        player.Parent~=Players then return reject("invalid_player") end
    local argc=select("#",...)
    if argc~=1 and argc~=4 then return reject("invalid_arity") end
    local action,slotId,typeId,configId=...
    local sections=stateFor(player,services)
    if not sections then return reject("profile_loading") end
    local before=inspect(sections)
    if not before then return reject("invalid_ship_state") end
    if action=="status" and argc==1 then
        return {success=true,partCount=before.partCount,performance=before.performance}
    end
    if argc~=4 or type(action)~="string" or type(slotId)~="string" or
        type(typeId)~="string" or type(configId)~="string" then return reject("invalid_payload") end
    if action~="create" and action~="configure" and action~="remove" then return reject("invalid_action") end
    local slot=RULES[slotId]
    local kind=slot and slot.types[typeId]
    if not kind or type(kind.configs[configId])~="number" then return reject("invalid_selection") end
    local old=sections[slotId]
    if action=="create" and old~=nil then return reject("slot_occupied") end
    if action~="create" and old==nil then return reject("slot_empty") end
    if old and (old.typeId~=typeId or
        (action=="remove" and old.configuration~=configId)) then return reject("wrong_section") end
    if action=="configure" and old.configuration==configId then return reject("already_configured") end
    if not shipFolder(player) then return reject("ship_unavailable") end
    local nextSections=table.clone(sections)
    if action=="remove" then
        nextSections[slotId]=nil
    else
        nextSections[slotId]={owned=true,typeId=typeId,configuration=configId,
            performance=kind.configs[configId]}
    end
    local after=inspect(nextSections)
    if not after then return reject("invalid_result") end
    -- No yield between server validation and profile mutation.
    sections[slotId]=nextSections[slotId]
    draw(player,sections)
    publish(player,sections)
    return {success=true,action=action,slot=slotId,partCount=after.partCount,
        performance=after.performance,configuration=configId}
end
return Service
'''
_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remotes=ReplicatedStorage:WaitForChild("Remotes",20)
if not remotes then error("Missing Remotes") end
local remote=remotes:WaitForChild(__REMOTE__,20)
if not remote or not remote:IsA("RemoteFunction") then error("Ship Remote invalid") end
local gui=Instance.new("ScreenGui")
gui.Name="RMMShipSectionSlots"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local panel=Instance.new("ScrollingFrame")
panel.Size=UDim2.fromOffset(320,320)
panel.Position=UDim2.new(1,-335,0,165)
panel.CanvasSize=UDim2.fromOffset(0,1500)
panel.Parent=gui
local layout=Instance.new("UIListLayout")
layout.Parent=panel
local info=Instance.new("TextLabel")
info.Size=UDim2.new(1,0,0,45)
info.Text="Ship section slots"
info.Parent=panel
local slots={__SLOTS__}
local busy=false
local function send(action,slotId,typeId,configId)
    if busy then return end
    busy=true
    local ok,result=pcall(function()
        return remote:InvokeServer(action,slotId,typeId,configId)
    end)
    busy=false
    if ok and type(result)=="table" and result.success==true then
        info.Text="Sections "..tostring(result.partCount)..
            " / ship power "..tostring(result.performance)
    else
        info.Text="Rejected: "..tostring(
            ok and type(result)=="table" and result.reason or "network")
    end
end
for _,slot in slots do
    for _,kind in slot.types do
        for _,configId in kind.configs do
            for _,action in {"create","configure","remove"} do
                local button=Instance.new("TextButton")
                button.Size=UDim2.new(1,0,0,30)
                button.Text=action.." "..slot.label.." "..kind.label.." / "..configId
                button.Parent=panel
                button.Activated:Connect(function()
                    send(action,slot.id,kind.id,configId)
                end)
            end
        end
    end
end
'''