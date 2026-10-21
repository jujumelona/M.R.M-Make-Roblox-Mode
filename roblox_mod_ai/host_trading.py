"""Host-owned earned-resource selling to the server's market broker.

Uses the same persistent RMMInventory and profile-backed Coins ledger as
host_mining. The route must be an authored RemoteFunction; no client balances,
prices or item ownership are trusted. Player-to-player trading is not claimed.
"""
from __future__ import annotations

import json
import re

from .host_mining import render_host_mining
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
    if module.kind == ModuleKind.SERVER_MODULE:
        return _SERVER
    if not module.file_path.startswith("src/client/"):
        return None
    return _CLIENT.replace("__REMOTE__", json.dumps(route[0][0]))


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