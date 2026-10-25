"""Host-owned earned-resource selling to the server's market broker.

Uses the same persistent RMMInventory and profile-backed Coins ledger as
host_mining. The route must be an authored RemoteFunction; no client balances,
prices or item ownership are trusted. Player-to-player trading is not claimed.
"""
from __future__ import annotations

import json
import re

from .host_mining import render_host_mining
from .host_space_actions import render_host_space_action
from .host_peer_barter import is_bilateral_asset_exchange
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


def render_host_trading(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if not module.module_id.startswith("dyn_"):
        return None
    if module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT):
        return None
    if not re.search(r"resource.*trad", module.name, re.I):
        return None
    description = module.description.lower()
    # Two-party consent and both-sided asset transfer cannot use a market broker.
    if is_bilateral_asset_exchange(description):
        return None
    if (not any(word in description for word in ("trade", "trading", "sell"))
            or "resource" not in description
            or not any(word in description for word in ("currency", "coin", "credit"))):
        return None
    # Only share an inventory when the accepted plan contains an actual
    # host-owned mining producer. Never grant missing resources artificially.
    if not any(render_host_mining(m, proposal) is not None
               for m in proposal.modules
               if m.kind == ModuleKind.SERVER_MODULE and m.module_id.startswith("dyn_")):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    route = [(name, v) for name, v in
             (proposal.game_design.get("dynamic_design") or {})
             .get("host_actions", {}).items()
             if isinstance(v, dict) and v.get("service") == server]
    if len(route) != 1 or route[0][1].get("kind") != "RemoteFunction":
        return None
    if route[0][1].get("max_args") == 0:
        return None
    # Only expose extraterrestrial trading when a VERIFIED authored planet
    # mining service exists in this same proposal. Other genres stay unchanged.
    space_ready = any(
        m.kind == ModuleKind.SERVER_MODULE
        and m.name.startswith("ExtractOtherPlanetMineral")
        and render_host_space_action(m, proposal) is not None
        for m in proposal.modules
    )
    if module.kind == ModuleKind.SERVER_MODULE:
        return _SPACE_SERVER if space_ready else _SERVER
    if not module.file_path.startswith("src/client/"):
        return None
    client = _SPACE_CLIENT if space_ready else _CLIENT
    return client.replace("__REMOTE__", json.dumps(route[0][0]))


_SERVER = r'''--!strict
-- Host-owned one-way trade: players sell earned ore to a server-owned market.
local Players = game:GetService("Players")
local Service = {}
local PRICE_PER_ORE = 2
local MAX_TRADE = 100
local recent = setmetatable({}, {__mode = "k"})
local brokerStock = 0
function Service.start(services)
    assert(type(services) == "table" and
        type(services.PlayerDataManager) == "table" and
        type(services.PlayerDataManager.GetState) == "function",
        "Trading requires the host player profile service")
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or player.Parent ~= Players then return false end
    if select("#", ...) ~= 1 then return false end
    local quantity = ...
    if type(quantity) ~= "number" or quantity ~= quantity or
       quantity < 1 or quantity > MAX_TRADE or quantity % 1 ~= 0 then return false end
    local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not inventory or type(inventory.resources) ~= "number" or
       inventory.resources < quantity or inventory.resources % 1 ~= 0 then return false end
    local trades = services.PlayerDataManager.GetState(player, "RMMTrades")
    if not trades then return false end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or
       coins.Value > 2147483647 - quantity * PRICE_PER_ORE then return false end
    local now = os.clock()
    if recent[player] and now - recent[player] < 0.4 then return false end
    recent[player] = now
    inventory.resources -= quantity
    coins.Value += quantity * PRICE_PER_ORE
    trades.oreSold = (type(trades.oreSold) == "number" and trades.oreSold or 0) + quantity
    brokerStock += quantity
    return {success = true, credits = coins.Value,
            remainingResources = inventory.resources, marketStock = brokerStock}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local gui = Instance.new("ScreenGui")
gui.Name = "RMMResourceMarket"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Name = "SellOre"
button.Size = UDim2.fromOffset(160, 45)
button.Position = UDim2.new(0, 200, 1, -112)
button.Text = "Sell 1 ore"
button.Parent = gui
local status = Instance.new("TextLabel")
status.Size = UDim2.fromOffset(270, 36)
status.Position = UDim2.new(0, 200, 1, -64)
status.Text = "Sell mined ore at the market"
status.Parent = gui
local busy = false
button.Activated:Connect(function()
    if busy then return end
    busy = true
    local ok, result = pcall(function() return remote:InvokeServer(1) end)
    busy = false
    if ok and type(result) == "table" and result.success == true then
        status.Text = "Coins " .. tostring(result.credits) ..
            " | Ore " .. tostring(result.remainingResources)
    else
        status.Text = "Sale rejected: no ore, cooldown, or profile loading"
    end
end)
'''
# The authenticated planet-mineral branch is opt-in by source-grounded
# producer availability. On this branch the same broker converts two
# server-owned inventories into persistent Coins; it never accepts prices,
# players, ownership flags or balances from a client.
_SPACE_SERVER = r'''--!strict
local Players=game:GetService("Players")
local Service={}
local PRICE_PER_ORE=2
local PRICE_PER_ALIEN_MINERAL=15
local MAX_TRADE=100
local recent=setmetatable({}, {__mode="k"})
local brokerStock=0
local brokerMinerals=0
local function validAmount(value)
    return type(value)=="number" and value==value and value%1==0
        and value>=0 and value<=2147483647
end
function Service.start(services)
    assert(type(services)=="table" and type(services.PlayerDataManager)=="table"
        and type(services.PlayerDataManager.GetState)=="function",
        "Trading requires the host player profile service")
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players or select("#",...)~=1 then
        return {success=false,reason="invalid_player"} end
    local request=(...)
    local quantity=request
    local kind="ore"
    if typeof(request)=="table" then
        for key in pairs(request) do
            if key~="resource" and key~="quantity" then
                return {success=false,reason="invalid_fields"} end
        end
        if request.resource~="alien_mineral" then
            return {success=false,reason="invalid_resource"} end
        kind="alien_mineral"
        quantity=request.quantity
    end
    if not validAmount(quantity) or quantity<1 or quantity>MAX_TRADE then
        return {success=false,reason="invalid_quantity"} end
    local data=services.PlayerDataManager
    local trades=data.GetState(player,"RMMTrades")
    if type(trades)~="table" then return {success=false,reason="loading"} end
    local inventory=nil
    local planet=nil
    local balance
    if kind=="ore" then
        inventory=data.GetState(player,"RMMInventory")
        if type(inventory)~="table" then return {success=false,reason="loading"} end
        balance=inventory.resources or 0
    else
        planet=data.GetState(player,"RMMPlanetProgress")
        if type(planet)~="table" then return {success=false,reason="loading"} end
        if planet.planetOwned~=true or planet.colonized~=true then
            return {success=false,reason="planet_not_owned"} end
        balance=planet.minerals or 0
    end
    if not validAmount(balance) or balance<quantity then
        return {success=false,reason="insufficient_resource"} end
    local leaderstats=player:FindFirstChild("leaderstats")
    local coins=leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or not validAmount(coins.Value) then
        return {success=false,reason="invalid_coins"} end
    local unitPrice=kind=="ore" and PRICE_PER_ORE or PRICE_PER_ALIEN_MINERAL
    local payout=quantity*unitPrice
    if coins.Value>2147483647-payout then
        return {success=false,reason="coin_cap"} end
    local now=os.clock()
    if recent[player] and now-recent[player]<0.4 then
        return {success=false,reason="cooldown"} end
    -- All state transitions below execute without a yield. Do not grant
    -- Coins until the authoritative inventory was debited.
    recent[player]=now
    if kind=="ore" then
        inventory.resources=balance-quantity
        trades.oreSold=(validAmount(trades.oreSold) and trades.oreSold or 0)+quantity
        brokerStock+=quantity
    else
        planet.minerals=balance-quantity
        trades.alienMineralsSold=(validAmount(trades.alienMineralsSold)
            and trades.alienMineralsSold or 0)+quantity
        brokerMinerals+=quantity
        player:SetAttribute("RMMPlanetMinerals",planet.minerals)
    end
    coins.Value+=payout
    return {success=true,resource=kind,credits=coins.Value,
        payout=payout,remainingResources=kind=="ore" and inventory.resources or nil,
        remainingMinerals=kind=="alien_mineral" and planet.minerals or nil,
        marketStock=brokerStock,marketMinerals=brokerMinerals}
end
return Service
'''

# RMMHUDLayout moves one ScrollingFrame into the Trade card; putting
# multiple root buttons on the ScreenGui would silently delete the second.
_SPACE_CLIENT = r'''--!strict
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remote=ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
assert(remote:IsA("RemoteFunction"),"Market route must be a RemoteFunction")
local gui=Instance.new("ScreenGui")
gui.Name="RMMResourceMarket"
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local scroll=Instance.new("ScrollingFrame")
scroll.Name="MarketOptions"
scroll.Size=UDim2.fromOffset(260,190)
scroll.CanvasSize=UDim2.new()
scroll.AutomaticCanvasSize=Enum.AutomaticSize.Y
scroll.Parent=gui
local layout=Instance.new("UIListLayout")
layout.Padding=UDim.new(0,8)
layout.Parent=scroll
local status=Instance.new("TextLabel")
status.Size=UDim2.new(1,-12,0,44)
status.TextWrapped=true
status.Text="Server market: ore 2 | alien mineral 15"
local busy=false
local function makeButton(name,label,request)
    local button=Instance.new("TextButton")
    button.Name=name
    button.Size=UDim2.new(1,-12,0,43)
    button.Text=label
    button.Parent=scroll
    button.Activated:Connect(function()
        if busy then return end
        busy=true
        local ok,result=pcall(function() return remote:InvokeServer(request) end)
        busy=false
        if ok and type(result)=="table" and result.success then
            status.Text="Sold "..result.resource.." | +"..tostring(result.payout)
                .." credits | total "..tostring(result.credits)
        else
            status.Text="Trade rejected: "..tostring(
                type(result)=="table" and result.reason or "network_error")
        end
    end)
end
makeButton("SellOre","Sell 1 ground ore",1)
makeButton("SellAlienMineral","Sell 1 alien mineral",{resource="alien_mineral",quantity=1})
status.Parent=scroll
'''