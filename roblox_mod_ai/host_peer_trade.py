"""Server-owned, two-party earned-resource trade with explicit counterparty consent.

Only used for authored RemoteFunction trading systems whose description
requires a real counterparty, and only if host mining supplies real inventory.
"""
from __future__ import annotations

import json
import re

from .host_mining import render_host_mining
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


def render_host_peer_trade(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)
            or not re.search(r"resource.*trad", module.name, re.I)):
        return None
    description = module.description.casefold()
    if ("counterparty" not in description or "trade" not in description
            or "inventory" not in description):
        return None
    if not any(render_host_mining(peer, proposal) is not None
               for peer in proposal.modules if peer.kind == ModuleKind.SERVER_MODULE):
        return None
    service = (module.name if module.kind == ModuleKind.SERVER_MODULE
               else module.name.removesuffix("Client") + "Server")
    design = proposal.game_design.get("dynamic_design") or {}
    matches = [(name, binding) for name, binding in
               (design.get("host_actions") or {}).items()
               if isinstance(binding, dict) and binding.get("service") == service]
    if len(matches) != 1 or matches[0][1].get("kind") != "RemoteFunction":
        return None
    if matches[0][1].get("max_args") == 0:
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
        return _SERVER
    if not module.file_path.startswith("src/client/"):
        return None
    return _CLIENT.replace("__REMOTE__", json.dumps(matches[0][0]))


_SERVER = r'''--!strict
-- Buyer pays a server-fixed in-game price for one unit of seller-owned ore.
-- Both parties must be online; only the designated buyer may accept the offer.
local Players = game:GetService("Players")
local Service = {}
local PRICE = 2
local OFFER_TTL = 45
local MAX_PENDING_PER_PLAYER = 3
local offers = {}
local nextId = 0

local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player") and player.Parent == Players
end
local function resources(services, player)
    local state = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not state or type(state.resources) ~= "number" then return nil end
    if state.resources ~= state.resources or state.resources < 0 or state.resources % 1 ~= 0 then return nil end
    return state
end
local function coinsOf(player)
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") then return nil end
    return coins
end
local function pruneExpired()
    local now = os.clock()
    for id, offer in pairs(offers) do
        if now >= offer.expiresAt then offers[id] = nil end
    end
end
function Service.start(services)
    assert(type(services) == "table" and
        type(services.PlayerDataManager) == "table" and
        type(services.PlayerDataManager.GetState) == "function",
        "Host PlayerDataManager required for two-party trade")
    Players.PlayerRemoving:Connect(function(player)
        for id, offer in pairs(offers) do
            if offer.seller == player.UserId or offer.buyer == player.UserId then
                offers[id] = nil
            end
        end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) then return {success = false, reason = "invalid_player"} end
    local argc = select("#", ...)
    if argc < 1 or argc > 2 then return {success = false, reason = "bad_arity"} end
    local action, value = ...
    if type(action) ~= "string" then return {success = false, reason = "bad_action"} end
    pruneExpired()
    if action == "list" and argc == 1 then
        local pending = {}
        for id, offer in pairs(offers) do
            if offer.buyer == player.UserId then
                table.insert(pending, {id = id, seller = offer.seller, price = PRICE})
            end
        end
        return {success = true, pending = pending}
    end
    if action == "offer" and argc == 2 then
        if type(value) ~= "number" or value ~= value or value % 1 ~= 0 then
            return {success = false, reason = "invalid_target"}
        end
        local buyer = Players:GetPlayerByUserId(value)
        if not buyer or buyer == player then return {success = false, reason = "unavailable_buyer"} end
        local sellerInventory = resources(services, player)
        local buyerInventory = services.PlayerDataManager.GetState(buyer, "RMMInventory")
        if not sellerInventory or sellerInventory.resources < 1 or not buyerInventory then
            return {success = false, reason = "no_inventory"}
        end
        if not coinsOf(player) or not coinsOf(buyer) then
            return {success = false, reason = "profile_loading"}
        end
        local ownPending = 0
        for _, offer in pairs(offers) do
            if offer.seller == player.UserId then ownPending += 1 end
        end
        if ownPending >= MAX_PENDING_PER_PLAYER then
            return {success = false, reason = "too_many_offers"}
        end
        nextId += 1
        offers[nextId] = {seller = player.UserId, buyer = buyer.UserId,
                          expiresAt = os.clock() + OFFER_TTL}
        return {success = true, id = nextId, price = PRICE}
    end
    if action == "accept" and argc == 2 then
        if type(value) ~= "number" or value % 1 ~= 0 or value ~= value then
            return {success = false, reason = "invalid_offer"}
        end
        local offer = offers[value]
        if not offer or offer.buyer ~= player.UserId then
            return {success = false, reason = "not_your_offer"}
        end
        local seller = Players:GetPlayerByUserId(offer.seller)
        if not seller or not validPlayer(seller) then
            offers[value] = nil
            return {success = false, reason = "seller_left"}
        end
        local sellerInv = resources(services, seller)
        local buyerInv = resources(services, player)
        local sellerCoins, buyerCoins = coinsOf(seller), coinsOf(player)
        if not sellerInv or not buyerInv or not sellerCoins or not buyerCoins
           or sellerInv.resources < 1 or buyerCoins.Value < PRICE
           or sellerCoins.Value > 2147483647 - PRICE
           or buyerInv.resources >= 2147483647 then
            return {success = false, reason = "insufficient_balance"}
        end
        -- No yielding between checking and applying this transaction.
        -- Removing the offer first prevents replay from charging either party twice.
        offers[value] = nil
        sellerInv.resources -= 1
        buyerInv.resources = buyerInv.resources + 1
        buyerCoins.Value -= PRICE
        sellerCoins.Value += PRICE
        return {success = true, price = PRICE,
                sellerCoins = sellerCoins.Value, buyerCoins = buyerCoins.Value,
                buyerResources = buyerInv.resources}
    end
    if action == "cancel" and argc == 2 then
        local offer = offers[value]
        if offer and offer.seller == player.UserId then
            offers[value] = nil
            return {success = true, canceled = true}
        end
        return {success = false, reason = "not_your_offer"}
    end
    return {success = false, reason = "unknown_action"}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local gui = Instance.new("ScreenGui")
gui.Name = "RMMPlayerTrading"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local target = Instance.new("TextBox")
target.Name = "TradeTarget"
target.Size = UDim2.fromOffset(165, 35)
target.Position = UDim2.new(0, 385, 1, -117)
target.PlaceholderText = "Other player's name"
target.Text = ""
target.Parent = gui
local offer = Instance.new("TextButton")
offer.Name = "OfferOre"
offer.Size = UDim2.fromOffset(90, 35)
offer.Position = UDim2.new(0, 555, 1, -117)
offer.Text = "Offer ore"
offer.Parent = gui
local accept = Instance.new("TextButton")
accept.Name = "AcceptOre"
accept.Size = UDim2.fromOffset(95, 35)
accept.Position = UDim2.new(0, 650, 1, -117)
accept.Text = "Accept offer"
accept.Parent = gui
local status = Instance.new("TextLabel")
status.Name = "TradeResult"
status.Size = UDim2.fromOffset(360, 35)
status.Position = UDim2.new(0, 385, 1, -77)
status.Text = "Trade one earned ore for 2 coins with consent"
status.Parent = gui
local busy = false
offer.Activated:Connect(function()
    if busy then return end
    local recipient = Players:FindFirstChild(target.Text)
    if not recipient or not recipient:IsA("Player") then
        status.Text = "Select a connected player's exact username"
        return
    end
    busy = true
    local ok, result = pcall(function() return remote:InvokeServer("offer", recipient.UserId) end)
    busy = false
    status.Text = ok and type(result) == "table" and result.success
        and ("Offer " .. tostring(result.id) .. " created; other player must accept")
        or "Offer rejected"
end)
accept.Activated:Connect(function()
    if busy then return end
    busy = true
    local ok, listed = pcall(function() return remote:InvokeServer("list") end)
    if not ok or type(listed) ~= "table" or type(listed.pending) ~= "table"
       or #listed.pending == 0 then
        status.Text = "No pending offers for you"
        busy = false
        return
    end
    local id = listed.pending[1].id
    local accepted, result = pcall(function() return remote:InvokeServer("accept", id) end)
    busy = false
    status.Text = accepted and type(result) == "table" and result.success
        and ("Trade completed; coins left " .. tostring(result.buyerCoins))
        or "Trade rejected"
end)
'''