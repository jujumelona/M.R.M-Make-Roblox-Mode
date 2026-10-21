"""Host-owned ship-upgrade/currency launch gate with server-only spatial entry.

The launch rule references actual host-validated ship slots and upgrade levels.
The model only supplies threshold and required level data, no Lua or teleport.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .host_ship_slot_configuration import eligible_ship_slot_configuration, _validate as _valid_ship_slots
from .host_ship_slot_levels import eligible_ship_slot_levels, _validate as _validate_levels
from .spec import ModuleKind

_SCHEMA={"type":"object","properties":{"currencyThreshold":{"type":"integer"},
    "requiredUpgrades":{"type":"array","items":{"type":"object","properties":{
    "slot":{"type":"string"},"minLevel":{"type":"integer"}},
    "required":["slot","minLevel"]}}},
    "required":["currencyThreshold","requiredUpgrades"]}

def eligible_ship_launch_gate(module:Any,proposal:Any)->tuple[str,str,str]|None:
    if not module.module_id.startswith("dyn_") or module.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT):return None
    owner_name=module.name if module.kind==ModuleKind.SERVER_MODULE else module.name.removesuffix("Client")+"Server"
    owner=next((m for m in getattr(proposal,"modules",()) if m.kind==ModuleKind.SERVER_MODULE and m.name==owner_name),None)
    if owner is None:return None
    d=owner.description.casefold()
    requirements=(r"\blaunch\s+gate\b",r"\bcurrency\s+threshold\b",
                  r"\b(?:spaceship|ship)\s+upgrade\b",r"\bspace\s+mode\b",
                  r"\blaunch[- ]eligible\b",r"\bvalidat\w*\b",
                  r"\b(?:saved|persist|record)\w*\b")
    if not all(re.search(p,d) for p in requirements):return None
    builders=[m for m in proposal.modules if m.kind==ModuleKind.SERVER_MODULE and
              m.name!=owner_name and eligible_ship_slot_configuration(m,proposal) is not None]
    upgrades=[m for m in proposal.modules if m.kind==ModuleKind.SERVER_MODULE and
              m.name!=owner_name and eligible_ship_slot_levels(m,proposal) is not None]
    if len(builders)!=1 or len(upgrades)!=1:return None
    design=proposal.game_design.get("dynamic_design") or {}
    routes=[(name,entry) for name,entry in (design.get("host_actions") or {}).items()
            if isinstance(entry,dict) and entry.get("service")==owner_name]
    if len(routes)!=1:return None
    name,entry=routes[0]
    max_args=entry.get("max_args")
    if (entry.get("kind")!="RemoteFunction"
        or (design.get("remotes") or {}).get(name)!="RemoteFunction"
        or (max_args is not None and (type(max_args) is not int or max_args<1))):return None
    if module.kind==ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):return None
    else:
        if module.name!=owner_name.removesuffix("Server")+"Client" or not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):return None
        linked=(design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and name not in linked:return None
    return owner_name,name,upgrades[0].name

def _validate(value:Any, levels:dict[str,int])->dict[str,Any]:
    if not isinstance(value,dict):raise ValueError("SHIP_LAUNCH_INVALID_CONTRACT")
    minimum,rows=value.get("currencyThreshold"),value.get("requiredUpgrades")
    if (type(minimum) is not int or not 1<=minimum<=1000000 or
        not isinstance(rows,list) or not 1<=len(rows)<=len(levels)):raise ValueError("SHIP_LAUNCH_INVALID_CONTRACT")
    output,seen=[],set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError("SHIP_LAUNCH_INVALID_REQUIRED_SLOT")
        sid,n=row.get("slot"),row.get("minLevel")
        if (not isinstance(sid,str) or sid not in levels or sid in seen or
            type(n) is not int or not 1<=n<=levels[sid]):
            raise ValueError("SHIP_LAUNCH_INVALID_REQUIRED_SLOT")
        seen.add(sid)
        output.append({"slot":sid,"minLevel":n})
    return {"currencyThreshold":minimum,"requiredUpgrades":output}

def _read(proposal:Any, owner:str, upgrade_owner:str, router:Any)->dict[str,Any]:
    catalog=(proposal.game_design.get("_host_ship_level_upgrades") or {}).get(upgrade_owner)
    if catalog is None:raise ValueError("SHIP_LAUNCH_MISSING_VALIDATED_UPGRADES")
    # Never validate the upgrade IDs against themselves: validate against the
    # independent, earlier host-authored ship-slot catalog instead.
    builders = [m for m in proposal.modules
                if m.kind == ModuleKind.SERVER_MODULE
                and eligible_ship_slot_configuration(m, proposal) is not None]
    if len(builders) != 1:
        raise ValueError("SHIP_LAUNCH_MISSING_VERIFIED_BUILDER")
    raw_slots = (proposal.game_design.get("_host_ship_slot_config") or {}).get(builders[0].name)
    if raw_slots is None:
        raise ValueError("SHIP_LAUNCH_MISSING_BUILDER_CATALOG")
    actual_ids = {entry["id"] for entry in _valid_ship_slots({"slots": raw_slots})}
    ship_slots = {x["slot"]: x["maxLevel"] for x in _validate_levels(
        {"upgrades": catalog}, actual_ids)}
    cache=proposal.game_design.setdefault("_host_ship_launch_rules",{})
    if owner in cache:return _validate(cache[owner],ship_slots)
    if router is None or not hasattr(router,"complete_json"):raise ValueError("SHIP_LAUNCH_RULES_NOT_AUTHORED")
    requirement=next(m.description for m in proposal.modules if m.name==owner)
    prompt=("Return ONLY JSON {currencyThreshold,requiredUpgrades:[{slot,minLevel}]}. "
            "The threshold is positive earned currency (1-1000000), and "
            "requiredUpgrades is a nonempty subset of actual host-owned ship "
            "upgrade IDs and maximum permitted levels: "+json.dumps(ship_slots)+". "
            "DO NOT invent extra slots, levels, Lua, Roblox methods, teleport "
            "APIs, successful launches or unauthorized currency. The host "
            "generates and enforces the actual gate and server-only space "
            "transition. Authored rule: "+requirement[:900])
    last=""
    for _ in range(2):
        try:
            data=router.complete_json(prompt+("\nFix invalid JSON: "+last if last else ""),
                role="planner",temperature=0,max_tokens=850,json_schema=_SCHEMA)
            validated=_validate(data,ship_slots)
            cache[owner]=validated
            return validated
        except Exception as exc:last=str(exc)[:200]
    raise ValueError("SHIP_LAUNCH_RULES_EXHAUSTED: "+last)

def try_ship_launch_gate(module:Any,proposal:Any,router:Any=None)->str|None:
    match=eligible_ship_launch_gate(module,proposal)
    if match is None:return None
    owner,remote,upgrade_owner=match
    data=_read(proposal,owner,upgrade_owner,router)
    if module.kind==ModuleKind.CLIENT_SCRIPT:
        return _CLIENT.replace("__REMOTE__",json.dumps(remote)).replace(
            "__THRESHOLD__",str(data["currencyThreshold"]))
    requirements=", ".join("{slot="+json.dumps(x["slot"])+",level="+str(x["minLevel"])+"}"
        for x in data["requiredUpgrades"])
    return (_SERVER.replace("__THRESHOLD__",str(data["currencyThreshold"]))
            .replace("__REQUIRED__",requirements))

_SERVER=r'''--!strict
local Players=game:GetService("Players")
local Service={}
local CURRENCY_THRESHOLD=__THRESHOLD__
local REQUIRED={__REQUIRED__}
local function reject(reason) return {success=false,reason=reason} end
local function ensurePart(name,position,size)
    local old=workspace:FindFirstChild(name)
    if old then
        if old:IsA("BasePart") then return old end
        error("Host space launch name collision")
    end
    local part=Instance.new("Part")
    part.Name=name
    part.Size=size
    part.Anchored=true
    part.Position=position
    part.Parent=workspace
    return part
end
local function playerState(player,services)
    local manager=services.PlayerDataManager
    if type(manager)~="table" or type(manager.GetState)~="function" then return nil end
    local ship=manager.GetState(player,"RMMShipSections")
    local levels=manager.GetState(player,"RMMShipSectionUpgradeLevels")
    local travel=manager.GetState(player,"RMMTravelProgress")
    local gameMode=manager.GetState(player,"RMMGameMode")
    if type(ship)~="table" or type(ship.sections)~="table" or
        type(levels)~="table" or type(levels.levels)~="table" or
        type(travel)~="table" or type(gameMode)~="table" then return nil end
    return ship.sections,levels.levels,travel,gameMode
end
local function check(player,services)
    local sections,levels,travel,mode=playerState(player,services)
    if not sections then return reject("profile_loading") end
    local stats=player:FindFirstChild("leaderstats")
    local coins=stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value<0 then
        return reject("currency_unavailable")
    end
    local upgradesReady=true
    for _,requirement in REQUIRED do
        local installed=sections[requirement.slot]
        local owned=levels[requirement.slot]
        if type(installed)~="table" or installed.owned~=true or
            type(owned)~="table" or owned.typeId~=installed.typeId or
            type(owned.level)~="number" or owned.level%1~=0 or
            owned.level<requirement.level then
            upgradesReady=false
            break
        end
    end
    local ready=coins.Value>=CURRENCY_THRESHOLD and upgradesReady
    player:SetAttribute("RMMLaunchEligible",ready)
    return {success=true,eligible=ready,coins=coins.Value,
        requiredCurrency=CURRENCY_THRESHOLD,upgradesReady=upgradesReady,
        inSpace=travel.inSpace==true}
end
function Service.start(services)
    assert(type(services)=="table" and type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function"
        and type(services.PlayerDataManager.OnReady)=="function",
        "Launch needs authoritative host profile")
    ensurePart("RMMLaunchGate",Vector3.new(22,6,22),Vector3.new(12,12,3))
    ensurePart("RMMOrbitPlatform",Vector3.new(0,700,0),Vector3.new(100,3,100))
    services.PlayerDataManager.OnReady(function(player)
        local status=check(player,services)
        if status.success and status.inSpace then
            player:SetAttribute("RMMInSpace",true)
            player:SetAttribute("RMMActiveGameMode","Space Mode")
        end
    end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player") or
        player.Parent~=Players or select("#",...)~=1 then return reject("invalid_request") end
    local action=...
    if action~="launch" and action~="status" then return reject("invalid_action") end
    local status=check(player,services)
    if action=="status" or status.success~=true then return status end
    if status.inSpace then return reject("already_in_space") end
    if not status.eligible then return reject("progression_requirements_not_met") end
    local gate=workspace:FindFirstChild("RMMLaunchGate")
    local orbit=workspace:FindFirstChild("RMMOrbitPlatform")
    local character=player.Character
    local root=character and character:FindFirstChild("HumanoidRootPart")
    local human=character and character:FindFirstChildOfClass("Humanoid")
    if not gate or not gate:IsA("BasePart") or not orbit or
        not orbit:IsA("BasePart") or not root or not human or human.Health<=0 then
        return reject("gate_unavailable")
    end
    if (gate.Position-root.Position).Magnitude>22 then return reject("outside_launch_gate") end
    local _,_,travel,mode=playerState(player,services)
    if not travel or travel.inSpace==true then return reject("invalid_travel_state") end
    -- Only the server grants this saved state and moves the live character.
    travel.inSpace=true
    travel.unlocked=true
    mode.activeMode="Space Mode"
    player:SetAttribute("RMMInSpace",true)
    player:SetAttribute("RMMSpaceUnlocked",true)
    player:SetAttribute("RMMActiveGameMode","Space Mode")
    character:PivotTo(CFrame.new(orbit.Position+Vector3.new(0,6,0)))
    return {success=true,eligible=true,inSpace=true,mode="Space Mode"}
end
return Service
'''
_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remotes=ReplicatedStorage:WaitForChild("Remotes",20)
if not remotes then error("Missing launch Remote folder") end
local remote=remotes:WaitForChild(__REMOTE__,20)
if not remote or not remote:IsA("RemoteFunction") then error("Launch Remote mismatch") end
local gui=Instance.new("ScreenGui")
gui.Name="RMMShipLaunch"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local box=Instance.new("Frame")
box.Size=UDim2.fromOffset(310,130)
box.Position=UDim2.new(0,20,0,180)
box.Parent=gui
local label=Instance.new("TextLabel")
label.Size=UDim2.fromOffset(300,75)
label.Parent=box
label.Text="Launch requires "..tostring(__THRESHOLD__).." coins and required ship upgrades"
local button=Instance.new("TextButton")
button.Size=UDim2.fromOffset(300,43)
button.Position=UDim2.fromOffset(0,80)
button.Text="Launch from gate"
button.Parent=box
local busy=false
button.Activated:Connect(function()
    if busy then return end
    busy=true
    local ok,result=pcall(function() return remote:InvokeServer("launch") end)
    busy=false
    if ok and type(result)=="table" and result.success==true then
        label.Text="Launch granted by server"
    else
        label.Text="Rejected: "..tostring(ok and type(result)=="table" and result.reason or "network")
    end
end)
task.defer(function()
    local ok,response=pcall(function() return remote:InvokeServer("status") end)
    if ok and type(response)=="table" and response.success then
        label.Text="Coins "..tostring(response.coins).."/"..tostring(response.requiredCurrency)
            .." | Upgrades "..tostring(response.upgradesReady)
    end
end)
'''