"""Purchased, level-capped ship-section upgrades bound to actual host slots.

This host adapter never invents part IDs or accepts client-reported currency.
Small model chooses bounded level caps/cost/bonus data keyed by builder slots.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .host_catalog_purchase import _ID
from .host_ship_slot_configuration import eligible_ship_slot_configuration, _validate as _valid_slots
from .spec import ModuleKind

_SCHEMA={"type":"object","properties":{"upgrades":{"type":"array","items":{
    "type":"object","properties":{"slot":{"type":"string"},"maxLevel":{"type":"integer"},
    "baseCost":{"type":"integer"},"bonusPerLevel":{"type":"integer"}},
    "required":["slot","maxLevel","baseCost","bonusPerLevel"]}}},"required":["upgrades"]}

def eligible_ship_slot_levels(module:Any,proposal:Any)->tuple[str,str,str]|None:
    if not module.module_id.startswith("dyn_") or module.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT):return None
    owner_name=module.name if module.kind==ModuleKind.SERVER_MODULE else module.name.removesuffix("Client")+"Server"
    owner=next((m for m in getattr(proposal,"modules",()) if m.kind==ModuleKind.SERVER_MODULE and m.name==owner_name),None)
    if owner is None:return None
    d=owner.description.casefold()
    if (not re.search(r"\bship\s+upgrade\b",d)
        or not re.search(r"\b(?:expansion|upgrade)\b",d)
        or not re.search(r"\bmaximum\s+level\b",d)
        or not re.search(r"\bship\s+part\b",d)
        or not re.search(r"\b(?:currency|coins?|credits?)\b",d)
        or not re.search(r"\b(?:deduct|spend)\w*\b",d)
        or not re.search(r"\b(?:owns?|owned|owner)\b",d)
        or not re.search(r"\b(?:persist|save)\w*\b",d)):return None
    builders=[m for m in proposal.modules
              if m.kind==ModuleKind.SERVER_MODULE and m.name!=owner_name
              and eligible_ship_slot_configuration(m,proposal) is not None]
    if len(builders)!=1:return None
    design=proposal.game_design.get("dynamic_design") or {}
    routes=[(k,v) for k,v in (design.get("host_actions") or {}).items()
            if isinstance(v,dict) and v.get("service")==owner_name]
    if len(routes)!=1:return None
    remote,binding=routes[0]
    maximum=binding.get("max_args")
    if (binding.get("kind")!="RemoteFunction" or (design.get("remotes") or {}).get(remote)!="RemoteFunction"
        or (maximum is not None and (type(maximum) is not int or maximum<1))):return None
    if module.kind==ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):return None
    else:
        if module.name!=owner_name.removesuffix("Server")+"Client" or not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):return None
        linked=(design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:return None
    return owner_name,remote,builders[0].name

def _validate(value:Any,actual:set[str])->list[dict[str,Any]]:
    items=value.get("upgrades") if isinstance(value,dict) else None
    if not isinstance(items,list) or not 1<=len(items)<=8:raise ValueError("SHIP_LEVEL_UPGRADES_REQUIRED")
    used,result=set(),[]
    for row in items:
        if not isinstance(row,dict):raise ValueError("SHIP_LEVEL_UPGRADE_INVALID")
        slot,level,cost,bonus=(row.get("slot"),row.get("maxLevel"),
                               row.get("baseCost"),row.get("bonusPerLevel"))
        if (not isinstance(slot,str) or slot not in actual or slot in used
            or type(level) is not int or not 2<=level<=6
            or type(cost) is not int or not 1<=cost<=100000
            or type(bonus) is not int or not 0<=bonus<=1000):
            raise ValueError("SHIP_LEVEL_UPGRADE_INVALID")
        used.add(slot)
        result.append({"slot":slot,"maxLevel":level,"baseCost":cost,"bonusPerLevel":bonus})
    return result

def _read(proposal:Any,owner:str,builder:str,router:Any)->list[dict[str,Any]]:
    catalog=(proposal.game_design.get("_host_ship_slot_config") or {}).get(builder)
    if catalog is None:raise ValueError("HOST_SHIP_LEVELS_MISSING_BUILDER_CATALOG")
    actual={x["id"] for x in _valid_slots({"slots":catalog})}
    cache=proposal.game_design.setdefault("_host_ship_level_upgrades",{})
    if owner in cache:return _validate({"upgrades":cache[owner]},actual)
    if router is None or not hasattr(router,"complete_json"):raise ValueError("SHIP_LEVEL_UPGRADES_NOT_AUTHORED")
    desc=next(m.description for m in proposal.modules if m.name==owner)
    prompt=("Return ONLY JSON {upgrades:[{slot,maxLevel,baseCost,bonusPerLevel}]}. "
            "Use ONLY existing host-built slots: "+json.dumps(sorted(actual))+". "
            "1-8 upgrades, maxLevel 2-6, positive earned currency baseCost 1-100000, "
            "nonnegative server ship-performance bonusPerLevel 0-1000. Each upgrade "
            "can be purchased at most until its level cap; the host enforces all "
            "ownership, transactions and durable state. No Lua, APIs, invented "
            "parts, remotes or client costs. Real contract: "+desc[:850])
    problem=""
    for _ in range(2):
        try:
            raw=router.complete_json(prompt+("\nFix JSON: "+problem if problem else ""),
                role="planner",temperature=0,max_tokens=900,json_schema=_SCHEMA)
            result=_validate(raw,actual)
            cache[owner]=result
            return result
        except Exception as exc:problem=str(exc)[:200]
    raise ValueError("SHIP_LEVEL_UPGRADES_EXHAUSTED: "+problem)

def try_ship_slot_levels(module:Any,proposal:Any,router:Any=None)->str|None:
    matched=eligible_ship_slot_levels(module,proposal)
    if matched is None:return None
    owner,remote,builder=matched
    rows=_read(proposal,owner,builder,router)
    if module.kind==ModuleKind.CLIENT_SCRIPT:
        lua=",\n".join("{slot="+json.dumps(x["slot"])+",max="+str(x["maxLevel"])+
            ",base="+str(x["baseCost"])+"}" for x in rows)
        return _CLIENT.replace("__REMOTE__",json.dumps(remote)).replace("__UPGRADES__",lua)
    lua=",\n".join("["+json.dumps(x["slot"])+"]={max="+str(x["maxLevel"])+
        ",base="+str(x["baseCost"])+",bonus="+str(x["bonusPerLevel"])+"}" for x in rows)
    return _SERVER.replace("__UPGRADES__",lua)

_SERVER=r'''--!strict
local Players=game:GetService("Players")
local Service={}
local UPGRADES={__UPGRADES__}
local MAX_COINS=2147483647
local function reject(reason) return {success=false,reason=reason} end
local function profiles(player,services)
    local manager=services.PlayerDataManager
    if type(manager)~="table" or type(manager.GetState)~="function" then return nil end
    local ship=manager.GetState(player,"RMMShipSections")
    local upgrade=manager.GetState(player,"RMMShipSectionUpgradeLevels")
    if type(ship)~="table" or type(ship.sections)~="table" or type(upgrade)~="table" then return nil end
    if upgrade.levels==nil then upgrade.levels={} end
    if type(upgrade.levels)~="table" then return nil end
    return ship.sections,upgrade.levels
end
local function publish(player,sections,levels)
    local total=0
    for slot,record in pairs(levels) do
        local def=UPGRADES[slot]
        local installed=sections[slot]
        if def and type(record)=="table" and type(installed)=="table"
            and installed.owned==true and record.typeId==installed.typeId
            and type(record.level)=="number" and record.level%1==0
            and record.level>=1 and record.level<=def.max then
            total+=record.level*def.bonus
        end
    end
    player:SetAttribute("RMMShipUpgradeScore",total)
    player:SetAttribute("RMMShipSectionLevelBonus",total)
    return total
end
function Service.start(services)
    assert(type(services)=="table" and type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.OnReady)=="function"
        and type(services.PlayerDataManager.GetState)=="function",
        "Level upgrade requires real profile")
    services.PlayerDataManager.OnReady(function(player)
        local sections,levels=profiles(player,services)
        if sections and levels then publish(player,sections,levels) end
    end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player") or
        player.Parent~=Players or select("#",...)~=1 then return reject("invalid_request") end
    local slot=...
    if type(slot)~="string" then return reject("invalid_part") end
    local rule=UPGRADES[slot]
    if not rule then return reject("not_upgradable") end
    local sections,levels=profiles(player,services)
    if not sections or not levels then return reject("profile_loading") end
    local installed=sections[slot]
    if type(installed)~="table" or installed.owned~=true or
        type(installed.typeId)~="string" then return reject("part_not_owned") end
    local previous=levels[slot]
    local current=0
    if previous~=nil then
        if type(previous)~="table" or previous.typeId~=installed.typeId
            or type(previous.level)~="number" or previous.level%1~=0
            or previous.level<1 or previous.level>rule.max then
            return reject("stale_upgrade_state")
        end
        current=previous.level
    end
    if current>=rule.max then return reject("maximum_level") end
    local nextLevel=current+1
    local charge=rule.base*nextLevel
    local stats=player:FindFirstChild("leaderstats")
    local coins=stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value<0
        or coins.Value>MAX_COINS then return reject("currency_unavailable") end
    if coins.Value<charge then return reject("insufficient_currency") end
    -- No yielding: debit and profile mutation in the same live server session.
    coins.Value-=charge
    levels[slot]={level=nextLevel,typeId=installed.typeId}
    local bonus=publish(player,sections,levels)
    player:SetAttribute("RMMCurrencyBalance",coins.Value)
    return {success=true,slot=slot,level=nextLevel,charge=charge,
        coins=coins.Value,levelBonus=bonus}
end
return Service
'''
_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remotes=ReplicatedStorage:WaitForChild("Remotes",20)
if not remotes then error("Missing Remote folder") end
local remote=remotes:WaitForChild(__REMOTE__,20)
if not remote or not remote:IsA("RemoteFunction") then error("Ship level upgrade unavailable") end
local gui=Instance.new("ScreenGui")
gui.Name="RMMShipLevelUpgrades"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local frame=Instance.new("Frame")
frame.Size=UDim2.fromOffset(280,285)
frame.Position=UDim2.new(1,-294,0,155)
frame.Parent=gui
local layout=Instance.new("UIListLayout")
layout.Parent=frame
local notice=Instance.new("TextLabel")
notice.Size=UDim2.new(1,0,0,45)
notice.Text="Upgrade your owned ship sections"
notice.Parent=frame
local catalog={__UPGRADES__}
local busy=false
for _,entry in catalog do
    local button=Instance.new("TextButton")
    button.Size=UDim2.new(1,0,0,40)
    button.Text=entry.slot.." (max "..tostring(entry.max)..")"
    button.Parent=frame
    button.Activated:Connect(function()
        if busy then return end
        busy=true
        local ok,reply=pcall(function() return remote:InvokeServer(entry.slot) end)
        busy=false
        if ok and type(reply)=="table" and reply.success==true then
            notice.Text="Level "..tostring(reply.level).." | Coins "..tostring(reply.coins)
        else
            notice.Text="Rejected: "..tostring(ok and type(reply)=="table" and reply.reason or "network")
        end
    end)
end
'''