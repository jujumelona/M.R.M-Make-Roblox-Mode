"""Host-authoritative mining + earned currency + bilateral barter in one service.

The accepted plan sometimes places three mechanics behind ONE RemoteFunction.
A mining-only renderer would silently discard trades; an unrestricted small
model body fabricates nodes, balances and APIs. This adapter owns the composite
transaction protocol only when the actual server contract and owned Part are
proven. Other trading or mining architectures remain separate adapters.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_mining_nodes import mining_world_nodes
from .spec import ModuleKind


def eligible_mining_exchange(module: Any, proposal: Any) -> tuple[str, str, list[str]] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    description = owner.description.casefold()
    if (not re.search(r"\b(?:mining|harvesting|gathering)\b.{0,65}"
                      r"\b(?:resource|ore|mineral)\s+(?:node|deposit)\b", description)
            or not re.search(r"\b(?:currency|coins?|credits?)\b", description)
            or not re.search(r"\b(?:trade|exchange)\s+actions?\b", description)
            or not re.search(r"\b(?:both sides|two players|both players|atomic)\w*\b", description)
            or not re.search(r"\b(?:finite|deplet|bounded|server-issued)\w*\b", description)
            or not re.search(r"\bserver\b", description)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(name, val) for name, val in (design.get("host_actions") or {}).items()
              if isinstance(val, dict) and val.get("service") == server]
    world_routes = [name for name, val in (design.get("host_world_actions") or {}).items()
                    if isinstance(val, dict) and val.get("service") == server]
    if len(routes) != 1 or world_routes:
        return None
    remote, spec = routes[0]
    max_args = spec.get("max_args")
    if (spec.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (max_args is not None and
                (type(max_args) is not int or max_args < 2))):
        return None
    nodes = mining_world_nodes(proposal, owner)
    if not nodes:
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
            return None
    else:
        if (module.name != server.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    return server, remote, nodes


def render_host_mining_exchange(module: Any, proposal: Any) -> str | None:
    result = eligible_mining_exchange(module, proposal)
    if result is None:
        return None
    _server, remote, nodes = result
    if module.kind == ModuleKind.SERVER_MODULE:
        return _SERVER.replace("__NODES__", "{" + ", ".join(json.dumps(x) for x in nodes) + "}")
    return _CLIENT.replace("__REMOTE__", json.dumps(remote))


_SERVER = r'''--!strict
-- A SINGLE server-authored ingress for mining and consent-based resource trade.
-- Clients can choose offers, but NEVER choose yield, balances or mining range.
local Players = game:GetService("Players")
local Service = {}
local NODE_NAMES = __NODES__
local NODE_CAPACITY = 100
local MINE_DISTANCE = 18
local MINE_COOLDOWN = 0.7
local OFFER_TTL = 45
local MAX_OFFER_RESOURCES = 100
local MAX_OFFER_COINS = 100000
local MAX_PENDING_PER_SELLER = 3
local INT_MAX = 2147483647
local nodes = {}
local lastMine = setmetatable({}, {__mode = "k"})
local pending = {}
local nextOffer = 0

local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player")
        and player.Parent == Players
end
local function integer(value, minValue, maxValue)
    return type(value) == "number" and value == value
        and value ~= math.huge and value ~= -math.huge and value % 1 == 0
        and value >= minValue and value <= maxValue
end
local function coinsOf(player)
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if coins and coins:IsA("IntValue")
        and integer(coins.Value, 0, INT_MAX) then return coins end
    return nil
end
local function inventoryOf(player, services)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil end
    local inv = manager.GetState(player, "RMMInventory")
    if type(inv) ~= "table" then return nil end
    local amount = inv.resources
    if amount == nil then amount = 0 end
    if not integer(amount, 0, INT_MAX) then return nil end
    return inv, amount
end
local function validNode(part)
    if typeof(part) ~= "Instance" or not part:IsA("BasePart")
        or not part:IsDescendantOf(workspace) then return false end
    for _, name in NODE_NAMES do
        if part.Name == name and workspace:FindFirstChild(name, true) == part then
            return true
        end
    end
    return false
end
local function getNode(part)
    if not validNode(part) then return nil end
    if nodes[part] == nil then
        nodes[part] = {remaining = NODE_CAPACITY}
        part:SetAttribute("RemainingResources", NODE_CAPACITY)
        part:SetAttribute("ResourceDepleted", false)
    end
    return nodes[part]
end
local function mine(player, services)
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0 or not root then
        return {success = false, reason = "no_character"}
    end
    local chosen, distance = nil, MINE_DISTANCE
    for _, name in NODE_NAMES do
        local part = workspace:FindFirstChild(name, true)
        if part and validNode(part) then
            local d = (root.Position - part.Position).Magnitude
            if d <= distance then
                local state = getNode(part)
                if state and state.remaining > 0 then chosen = part; distance = d end
            end
        end
    end
    if not chosen then return {success = false, reason = "no_mineable_node_nearby"} end
    local inv, resources = inventoryOf(player, services)
    local coins = coinsOf(player)
    if not inv or not coins then return {success = false, reason = "profile_loading"} end
    if resources >= INT_MAX or coins.Value >= INT_MAX then
        return {success = false, reason = "capacity_limit"}
    end
    local now = os.clock()
    if lastMine[player] and now - lastMine[player] < MINE_COOLDOWN then
        return {success = false, reason = "mining_cooldown"}
    end
    local state = getNode(chosen)
    if not state or state.remaining <= 0 then
        return {success = false, reason = "depleted"}
    end
    -- No yield between the final server validation and the owned mutations.
    lastMine[player] = now
    state.remaining -= 1
    inv.resources = resources + 1
    coins.Value += 1
    chosen:SetAttribute("RemainingResources", state.remaining)
    chosen:SetAttribute("ResourceDepleted", state.remaining == 0)
    player:SetAttribute("RMMCurrencyBalance", coins.Value)
    return {success = true, action = "mine", node = chosen.Name,
        gainedResources = 1, gainedCoins = 1,
        resources = inv.resources, credits = coins.Value,
        remaining = state.remaining}
end
local function pruneExpired()
    local now = os.clock()
    for id, offer in pairs(pending) do
        if offer.expiration <= now then pending[id] = nil end
    end
end
local function makeOffer(player, services, payload)
    if type(payload) ~= "table" then
        return {success = false, reason = "invalid_offer_payload"}
    end
    local buyerId, units, price = payload.buyerUserId, payload.resources, payload.coins
    if not integer(buyerId, 1, 9007199254740991)
        or not integer(units, 1, MAX_OFFER_RESOURCES)
        or not integer(price, 1, MAX_OFFER_COINS) then
        return {success = false, reason = "invalid_offer_values"}
    end
    local buyer = Players:GetPlayerByUserId(buyerId)
    if not buyer or buyer == player then
        return {success = false, reason = "invalid_buyer"}
    end
    local sellerInv, sellerResources = inventoryOf(player, services)
    local buyerInv = inventoryOf(buyer, services)
    if not sellerInv or not buyerInv or sellerResources < units
        or not coinsOf(player) or not coinsOf(buyer) then
        return {success = false, reason = "insufficient_inventory"}
    end
    local count = 0
    for _, existing in pairs(pending) do
        if existing.sellerId == player.UserId then
            count += 1
            if existing.buyerId == buyerId and existing.resources == units
                and existing.coins == price then
                return {success = false, reason = "duplicate_offer"}
            end
        end
    end
    if count >= MAX_PENDING_PER_SELLER then
        return {success = false, reason = "too_many_pending"}
    end
    nextOffer += 1
    pending[nextOffer] = {sellerId = player.UserId, buyerId = buyerId,
        resources = units, coins = price, expiration = os.clock() + OFFER_TTL}
    return {success = true, action = "offer", id = nextOffer,
        resources = units, coins = price, status = "pending_acceptance"}
end
local function acceptOffer(player, services, id)
    if not integer(id, 1, INT_MAX) then
        return {success = false, reason = "invalid_offer_id"}
    end
    local offer = pending[id]
    if not offer or offer.buyerId ~= player.UserId then
        return {success = false, reason = "offer_missing_or_unauthorized"}
    end
    if os.clock() >= offer.expiration then
        pending[id] = nil
        return {success = false, reason = "offer_expired"}
    end
    local seller = Players:GetPlayerByUserId(offer.sellerId)
    if not seller or not validPlayer(seller) then
        pending[id] = nil
        return {success = false, reason = "seller_unavailable"}
    end
    local sellerInv, sellerResources = inventoryOf(seller, services)
    local buyerInv, buyerResources = inventoryOf(player, services)
    local sellerCoins, buyerCoins = coinsOf(seller), coinsOf(player)
    if not sellerInv or not buyerInv or not sellerCoins or not buyerCoins then
        return {success = false, reason = "profile_loading"}
    end
    if sellerResources < offer.resources or buyerCoins.Value < offer.coins
        or buyerResources > INT_MAX - offer.resources
        or sellerCoins.Value > INT_MAX - offer.coins then
        return {success = false, reason = "insufficient_funds_or_capacity"}
    end
    -- Snapshot/commit within the single active server (no yielding).
    -- Both session-locked profiles are persisted by PlayerDataManager.
    -- This is not a cross-DataStore atomic commit guarantee.
    pending[id] = nil
    sellerInv.resources = sellerResources - offer.resources
    buyerInv.resources = buyerResources + offer.resources
    buyerCoins.Value -= offer.coins
    sellerCoins.Value += offer.coins
    seller:SetAttribute("RMMCurrencyBalance", sellerCoins.Value)
    player:SetAttribute("RMMCurrencyBalance", buyerCoins.Value)
    return {success = true, action = "accept", id = id,
        resources = buyerInv.resources, credits = buyerCoins.Value,
        transferredResources = offer.resources, transferredCoins = offer.coins,
        status = "committed_in_active_profiles"}
end
local function listOffers(player)
    local rows = {}
    for id, offer in pairs(pending) do
        if offer.buyerId == player.UserId then
            table.insert(rows, {id = id, sellerUserId = offer.sellerId,
                resources = offer.resources, coins = offer.coins})
        end
    end
    table.sort(rows, function(a, b) return a.id < b.id end)
    return {success = true, action = "list", pending = rows}
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function",
        "Mining/trade must use host PlayerDataManager")
    for _, name in NODE_NAMES do
        local part = workspace:FindFirstChild(name, true)
        if part and part:IsA("BasePart") then getNode(part) end
    end
    Players.PlayerRemoving:Connect(function(player)
        lastMine[player] = nil
        for id, offer in pairs(pending) do
            if offer.sellerId == player.UserId or offer.buyerId == player.UserId then
                pending[id] = nil
            end
        end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) then
        return {success = false, reason = "invalid_player"}
    end
    local argc = select("#", ...)
    if argc < 1 or argc > 2 then
        return {success = false, reason = "invalid_arity"}
    end
    local action, payload = ...
    if action == "mine" and argc == 1 then return mine(player, services) end
    pruneExpired()
    if action == "list" and argc == 1 then return listOffers(player) end
    if action == "offer" and argc == 2 then return makeOffer(player, services, payload) end
    if action == "accept" and argc == 2 then return acceptOffer(player, services, payload) end
    if action == "cancel" and argc == 2 and integer(payload, 1, INT_MAX) then
        local offer = pending[payload]
        if offer and offer.sellerId == player.UserId then
            pending[payload] = nil
            return {success = true, action = "cancel", status = "canceled"}
        end
        return {success = false, reason = "not_your_offer"}
    end
    if action == "status" and argc == 1 then
        local inv, count = inventoryOf(player, services)
        local coins = coinsOf(player)
        if not inv or not coins then return {success = false, reason = "profile_loading"} end
        player:SetAttribute("RMMCurrencyBalance", coins.Value)
        return {success = true, action = "status",
            resources = count, credits = coins.Value}
    end
    return {success = false, reason = "invalid_action"}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing authored Remotes folder") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Wrong trade and mining route") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMMiningAndTradingPanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(360, 310)
panel.Position = UDim2.new(0, 12, 1, -330)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 50)
status.Text = "Mining and two-party ore exchange"
status.Parent = panel
local mineButton = Instance.new("TextButton")
mineButton.Name = "MineNearby"
mineButton.Size = UDim2.new(1, 0, 0, 35)
mineButton.Text = "Mine nearest resource node"
mineButton.Parent = panel
local buyerName = Instance.new("TextBox")
buyerName.Name = "BuyerName"
buyerName.Size = UDim2.new(1, 0, 0, 30)
buyerName.PlaceholderText = "Buyer's exact username"
buyerName.Text = ""
buyerName.Parent = panel
local units = Instance.new("TextBox")
units.Size = UDim2.new(1, 0, 0, 30)
units.PlaceholderText = "Resource units to offer (1-100)"
units.Text = "1"
units.Parent = panel
local price = Instance.new("TextBox")
price.Size = UDim2.new(1, 0, 0, 30)
price.PlaceholderText = "Total earned Coins requested"
price.Text = "2"
price.Parent = panel
local offerButton = Instance.new("TextButton")
offerButton.Size = UDim2.new(1, 0, 0, 35)
offerButton.Text = "Offer resources for earned Coins"
offerButton.Parent = panel
local acceptButton = Instance.new("TextButton")
acceptButton.Size = UDim2.new(1, 0, 0, 35)
acceptButton.Text = "Accept next incoming trade"
acceptButton.Parent = panel
local busy = false
local function request(action, payload)
    if busy then return nil end
    busy = true
    status.Text = "Server validating " .. action .. "..."
    local ok, result = pcall(function()
        if payload == nil then return remote:InvokeServer(action) end
        return remote:InvokeServer(action, payload)
    end)
    busy = false
    if not ok or type(result) ~= "table" then
        status.Text = "Network or server unavailable"
        return nil
    end
    if result.success == true then
        status.Text = "Confirmed " .. action .. " | Coins " ..
            tostring(result.credits or result.coins or "unchanged") ..
            " | Resources " .. tostring(result.resources or "unchanged")
    else
        status.Text = "Rejected: " .. tostring(result.reason or "unknown")
    end
    return result
end
mineButton.Activated:Connect(function() request("mine", nil) end)
offerButton.Activated:Connect(function()
    local buyer = Players:FindFirstChild(buyerName.Text)
    if not buyer or not buyer:IsA("Player") then
        status.Text = "Choose an online player's exact username"; return
    end
    request("offer", {buyerUserId = buyer.UserId, resources = tonumber(units.Text),
        coins = tonumber(price.Text)})
end)
acceptButton.Activated:Connect(function()
    local list = request("list", nil)
    if list and list.success and type(list.pending) == "table" and #list.pending > 0 then
        request("accept", list.pending[1].id)
    elseif list and list.success then
        status.Text = "No incoming trade offers"
    end
end)
task.defer(function() request("status", nil) end)
'''