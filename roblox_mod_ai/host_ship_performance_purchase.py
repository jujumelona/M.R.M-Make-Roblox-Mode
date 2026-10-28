"""Compile owned-ship part performance upgrades without model-authored Luau.

The verified physical ship builder owns the inventory of installed parts.
The purchase path only mutates a preexisting, server-owned installed section;
it cannot mint sections or change ownership flags.
"""
from __future__ import annotations
import re
from .spec import ModuleKind
from .host_ship_attachment import eligible_ship_attachment


def eligible_ship_performance_purchase(module, proposal):
    if (module.kind != ModuleKind.SERVER_MODULE
            or not module.module_id.startswith("dyn_")
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    desc = module.description.casefold()
    if not all(re.search(p, desc) for p in (
        r"\b(?:ship|spaceship)\b", r"\bperformance\b",
        r"\bupgrad\w*\b", r"\b(?:purchase|trade|price|cost)\b",
        r"\b(?:balance|currency)\b", r"\b(?:validat|reject)\w*\b",
        r"\b(?:persist|record)\w*\b",
    )):
        return None
    design = (proposal.game_design or {}).get("dynamic_design") or {}
    owners = [(remote, row) for remote, row in
              (design.get("host_actions") or {}).items()
              if isinstance(row, dict) and row.get("service") == module.name]
    if len(owners) != 1:
        return None
    remote, row = owners[0]
    if (row.get("kind") != "RemoteFunction" or row.get("max_args") != 1
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (design.get("module_remotes") or {}).get(module.module_id) != [remote]):
        return None
    typed = (design.get("host_typed_actions") or {}).get(remote)
    if (not isinstance(typed, dict) or typed.get("transport_only") is not True
            or typed.get("server") != module.name
            or not isinstance(typed.get("contract"), dict)):
        return None
    manifest = typed["contract"]
    if manifest.get("target") != {"kind": "none"} or manifest.get("state_changes") != []:
        return None
    fields = manifest.get("inputs")
    if (not isinstance(fields, list) or len(fields) != 2
            or {(x.get("id"), x.get("type")) for x in fields
                if isinstance(x, dict)}
               != {("selection", "text"), ("quantity", "integer")}):
        return None
    if (typed.get("client") != module.name.removesuffix("Server") + "Client"
            or not any(m.kind == ModuleKind.CLIENT_SCRIPT and m.name == typed["client"]
                       and (design.get("module_remotes") or {}).get(m.module_id) == [remote]
                       for m in proposal.modules)):
        return None
    verified_builders = [m for m in proposal.modules
                         if m.kind == ModuleKind.SERVER_MODULE
                         and m.module_id != module.module_id
                         and (design.get("host_flight_ready_builders") or {}).get(m.name)
                         == "section_attachment"
                         and eligible_ship_attachment(m, proposal) is not None]
    if len(verified_builders) != 1:
        return None
    if not any(m.name == "PlayerDataManager" for m in proposal.modules):
        return None
    return verified_builders[0].name


def render_ship_performance_purchase(module, proposal):
    if eligible_ship_performance_purchase(module, proposal) is None:
        return None
    return _SERVER


_SERVER = r'''--!strict
local Players=game:GetService("Players")
local Service={}
local recent=setmetatable({}, {__mode="k"})
local MAX_LEVEL=5
local MAX_BALANCE=2147483647
local function integer(n,limit)
    return type(n)=="number" and n==n and n%1==0 and n>=0 and n<=limit
end
function Service.start(services)
    assert(type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function",
        "Ship upgrade requires persisted authoritative assembly")
    Players.PlayerRemoving:Connect(function(player) recent[player]=nil end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players or select("#",...)~=1 then
        return {success=false,reason="invalid_player"} end
    local args=...
    if type(args)~="table" or type(args.selection)~="string"
        or #args.selection<1 or #args.selection>120
        or not integer(args.quantity,1) or args.quantity~=1 then
        return {success=false,reason="invalid_args"} end
    for key in pairs(args) do
        if key~="selection" and key~="quantity" then
            return {success=false,reason="extra_input"} end
    end
    local state=services.PlayerDataManager.GetState(player,"RMMShipSections")
    if type(state)~="table" or type(state.sections)~="table" then
        return {success=false,reason="assembly_loading"} end
    local section=state.sections[args.selection]
    if type(section)~="table" or section.owned~=true then
        return {success=false,reason="part_not_installed"} end
    local level=section.level
    local perf=section.performance
    if not integer(level,MAX_LEVEL) or level<1
        or not integer(perf,1000) or perf<1 then
        return {success=false,reason="invalid_section_state"} end
    if level>=MAX_LEVEL or perf>998 then
        return {success=false,reason="max_level"} end
    local coinsFolder=player:FindFirstChild("leaderstats")
    local coins=coinsFolder and coinsFolder:FindFirstChild("Coins")
    local cost=100*level
    if not coins or not coins:IsA("IntValue")
        or not integer(coins.Value,MAX_BALANCE) or coins.Value<cost then
        return {success=false,reason="insufficient_currency"} end
    local now=os.clock()
    if recent[player] and now-recent[player]<0.35 then
        return {success=false,reason="cooldown"} end
    -- Single non-yielding transaction; ownership is NEVER toggled.
    coins.Value-=cost
    section.level=level+1
    section.performance=perf+2
    recent[player]=now
    local total=0
    for _,saved in pairs(state.sections) do
        if type(saved)=="table" and saved.owned==true
            and integer(saved.performance,1000) then
            total=math.min(8000,total+saved.performance) end
    end
    player:SetAttribute("RMMShipAssemblyPerformance",total)
    return {success=true,section=args.selection,level=section.level,
        performance=section.performance,total=total,coins=coins.Value}
end
return Service
'''
