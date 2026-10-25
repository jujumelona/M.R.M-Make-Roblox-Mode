"""Bounded-data paid rank upgrade, compiled to authoritative server Luau.

9B supplies price and rank numbers only, never arbitrary service Lua.
This supports one source-owned target and earned player Coins.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .spec import ModuleKind

_NAME=re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,59}$")
_PAY=re.compile(r"\b(?:cost|price|currency|coins?|credits?|balance)\b",re.I)
_UP=re.compile(r"\b(?:upgrad\w*|enhanc\w*|improv\w*)\b",re.I)
_DEBIT=re.compile(r"\b(?:deduct\w*|debit\w*|spend\w*|charg\w*|subtract\w*)\b",re.I)
_WALLET=re.compile(r"currency|coins?|credits?|cost|price|balance|wallet",re.I)
_OWNED=re.compile(r"\b(?:owned\s+(?:weapon|item|tool|equipment)|weapon\s+exists\s+and\s+is\s+owned)\b",re.I)
_SCHEMA={"type":"object","properties":{
    "label":{"type":"string"},"cost":{"type":"integer"},
    "increment":{"type":"integer"},"max_level":{"type":"integer"}},
    "required":["label","cost","increment","max_level"],"additionalProperties":False}

def eligible_rank_protocol(m:Any,p:Any)->tuple[str,str,str,bool]|None:
    if not m.module_id.startswith("dyn_") or m.kind not in (ModuleKind.SERVER_MODULE,ModuleKind.CLIENT_SCRIPT):return None
    server=m.name if m.kind==ModuleKind.SERVER_MODULE else m.name.removesuffix("Client")+"Server"
    owner=next((x for x in p.modules if x.name==server and x.kind==ModuleKind.SERVER_MODULE),None)
    if owner is None or not all(rx.search(owner.description) for rx in (_PAY,_UP,_DEBIT)):return None
    if re.search(r"\b(?:assembly|barter|trade\s+offer)\b",owner.description,re.I):return None
    d=p.game_design.get("dynamic_design") or {}
    routes=[(name,r) for name,r in (d.get("host_actions") or {}).items() if r.get("service")==server]
    if len(routes)!=1:return None
    remote,route=routes[0]
    if route.get("kind")!="RemoteFunction" or (d.get("remotes") or {}).get(remote)!="RemoteFunction":return None
    spec=((d.get("host_typed_actions") or {}).get(remote)
          or (d.get("host_rank_contracts") or {}).get(remote))
    if not isinstance(spec,dict) or spec.get("transport_only") is not True:return None
    if spec.get("server")!=server or spec.get("client")!=server.removesuffix("Server")+"Client":return None
    targets=[x for x in spec.get("world_entities",[]) if isinstance(x,str) and _NAME.fullmatch(x) and not _WALLET.search(x)]
    if len(targets)!=1:return None
    if m.kind==ModuleKind.CLIENT_SCRIPT and not m.file_path.endswith(".client.luau"):return None
    if m.kind==ModuleKind.SERVER_MODULE and not m.file_path.startswith("src/server/"):return None
    links=(d.get("module_remotes") or {}).get(m.module_id)
    if links is not None and links!=[remote]:return None
    return server,remote,targets[0],bool(_OWNED.search(owner.description))

def _allows_paid_first_ownership(proposal: Any, target: str,
                                 owner_description: str, owned: bool) -> bool:
    """Close an explicit weapon-buy -> ownership -> upgrade progression gap.

    A paid rank-only action must not silently give equipment. Enable a first
    paid acquisition only for this canonical inventory item, an explicitly
    requested weapon purchase, and a purchase owner that also checks price.
    """
    if not owned or target != "owned_weapon":
        return False
    source = str(getattr(proposal, "requested_prompt", "") or "").casefold()
    source_buy = (
        bool(re.search(r"무기.{0,95}(?:구매|살\s*수|구입)", source))
        or bool(re.search(r"\b(?:buy|purchase|purchasing)\b.{0,100}\bweapons?\b", source))
        or bool(re.search(r"\bweapons?\b.{0,100}\b(?:buy|purchase|purchasing)\b", source))
    )
    return bool(source_buy and re.search(r"\bweapon\b", owner_description, re.I)
                and re.search(r"\bpurchas\w*\b", owner_description, re.I))


def _check(value:Any)->dict:
    if not isinstance(value,dict) or set(value)!={"label","cost","increment","max_level"}:raise ValueError("RANK_FIELDS")
    if not isinstance(value["label"],str) or not 2<=len(value["label"].strip())<=60:raise ValueError("RANK_LABEL")
    for k,cap in (("cost",1000000),("increment",1000),("max_level",100)):
        if type(value[k]) is not int or not 1<=value[k]<=cap:raise ValueError("RANK_"+k)
    return dict(value,label=value["label"].strip())

def _data(p:Any,server:str,router:Any)->dict:
    store=p.game_design.setdefault("_bounded_rank_catalog",{})
    if server in store:return _check(store[server])
    if not hasattr(router,"complete_json"):raise ValueError("RANK_DATA_ROUTER_REQUIRED")
    source=next(x.description for x in p.modules if x.name==server)
    failure=""
    for _ in range(2):
        try:
            raw=router.complete_json("Return JSON {label,cost,increment,max_level} "
                "for ONE paid rank improvement. Positive bounded integers. "
                "No Luau code, invented extra gameplay, free items, or "
                "client-supplied prices. The host owns transaction, saved "
                "state and UI. Requirement: "+source[:850]+
                ("\nRejected: "+failure if failure else ""),
                role="planner",temperature=0,max_tokens=225,json_schema=_SCHEMA)
            result=_check(raw);store[server]=result;return result
        except (TypeError,ValueError) as e:failure=str(e)[:180]
    raise ValueError("RANK_DATA_EXHAUSTED: "+failure)

def render_rank_protocol(m:Any,p:Any,router:Any)->str|None:
    selected=eligible_rank_protocol(m,p)
    if selected is None:return None
    server,remote,target,owned=selected
    owner_description=next(x.description for x in p.modules if x.name==server)
    acquire=_allows_paid_first_ownership(p,target,owner_description,owned)
    data=_data(p,server,router)
    replacements={"@REMOTE@":json.dumps(remote),"@TARGET@":json.dumps(target),
        "@LABEL@":json.dumps(data["label"],ensure_ascii=False),
        "@COST@":str(data["cost"]),"@STEP@":str(data["increment"]),
        "@MAX@":str(data["max_level"]),"@OWNED@":"true" if owned else "false",
        "@ATTR@":json.dumps("RMMRank_"+target),
        "@ACQUIRE_FIRST@":"true" if acquire else "false"}
    result=_SERVER if m.kind==ModuleKind.SERVER_MODULE else _CLIENT
    for key,val in replacements.items():result=result.replace(key,val)
    return result

_SERVER=r'''--!strict
local Players=game:GetService("Players")
local Service={}
local TARGET=@TARGET@
local COST=@COST@
local STEP=@STEP@
local MAX=@MAX@
local OWNED=@OWNED@
local ACQUIRE_FIRST=@ACQUIRE_FIRST@
local ATTR=@ATTR@
local last={}
local function good(v)
    return type(v)=="number" and v==v and v%1==0 and v>=0 and v<=2147483647
end
function Service.start(services)
    assert(services.PlayerDataManager and type(services.PlayerDataManager.GetState)=="function", "Rank upgrade requires PlayerDataManager.GetState")
    services.PlayerDataManager.OnReady(function(player)
        local saved=services.PlayerDataManager.GetState(player,"RMMRankProgress")
        if saved and good(saved[TARGET] or 0) then player:SetAttribute(ATTR,saved[TARGET] or 0) end
    end)
    Players.PlayerRemoving:Connect(function(player) last[player]=nil end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player") or player.Parent~=Players
        or select("#",...)~=1 or (...)~=TARGET then return {success=false} end
    local ranks=services.PlayerDataManager.GetState(player,"RMMRankProgress")
    local inventory=services.PlayerDataManager.GetState(player,"RMMInventory")
    if not ranks or not inventory then return {success=false,reason="loading"} end
    local acquired=false
    if OWNED then
        if inventory.items~=nil and type(inventory.items)~="table" then
            return {success=false,reason="inventory_invalid"} end
        local quantity=inventory.items and inventory.items[TARGET] or 0
        if not good(quantity) then return {success=false,reason="inventory_invalid"} end
        acquired=quantity>=1
        if not acquired and not ACQUIRE_FIRST then
            return {success=false,reason="not_owned"} end
    end
    local acquiring=OWNED and ACQUIRE_FIRST and not acquired
    local rank=ranks[TARGET] or 0
    if not good(rank) or (not acquiring and rank>=MAX) then
        return {success=false,reason="max"} end
    local stats=player:FindFirstChild("leaderstats")
    local coins=stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or not good(coins.Value)
        or coins.Value<COST then return {success=false,reason="funds"} end
    local nextRank=math.min(MAX,rank+STEP)
    if not acquiring and nextRank<=rank then
        return {success=false,reason="unchanged"} end
    local now=os.clock()
    if last[player] and now-last[player]<0.25 then return {success=false,reason="cooldown"} end
    last[player]=now
    coins.Value-=COST
    if acquiring then
        if inventory.items==nil then inventory.items={} end
        inventory.items[TARGET]=1
        player:SetAttribute("RMMWeaponOwned",true)
        return {success=true,acquired=true,level=rank,coins=coins.Value}
    end
    ranks[TARGET]=nextRank
    player:SetAttribute(ATTR,nextRank)
    return {success=true,level=nextRank,coins=coins.Value}
end
return Service
'''
_CLIENT=r'''--!strict
local Players=game:GetService("Players")
local Storage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remotes=Storage:WaitForChild("Remotes",20)
if not remotes then error("Missing Remotes") end
local remote=remotes:WaitForChild(@REMOTE@,20)
if not remote or not remote:IsA("RemoteFunction") then error("Invalid Remote") end
local gui=Instance.new("ScreenGui")
gui.Name="RMMRankUpgrade"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local button=Instance.new("TextButton")
button.Size=UDim2.fromOffset(260,55)
button.Position=UDim2.new(1,-280,0,200)
button.Text=@LABEL@.." ("..tostring(@COST@).." Coins)"
button.Parent=gui
local status=Instance.new("TextLabel")
status.Size=UDim2.fromOffset(260,45)
status.Position=UDim2.new(1,-280,0,260)
status.Text=""
status.Parent=gui
local busy=false
button.Activated:Connect(function()
    if busy then return end
    busy=true
    local ok,result=pcall(function() return remote:InvokeServer(@TARGET@) end)
    if not ok or type(result)~="table" then status.Text="Network error"
    elseif result.success then status.Text=(result.acquired and "Weapon purchased" or ("Rank "..tostring(result.level)))
    else status.Text=tostring(result.reason or "Rejected") end
    busy=false
end)
'''
