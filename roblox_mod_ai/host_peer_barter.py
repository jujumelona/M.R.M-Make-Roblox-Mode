"""Host-owned, consent-based two-player barter over validated persistent assets.

Atomic in the non-yielding server memory transition; per-player DataStore
persistence is NOT a single atomic cross-user write.
"""
from __future__ import annotations
import json
import re
from .host_mining import render_host_mining
from .spec import ModuleKind, RobloxModuleSpec


def is_bilateral_asset_exchange(description: str) -> bool:
    """Distinguish consensual two-sided exchange from one-way market selling."""
    prose = description.casefold()
    return bool(
        re.search(r"\b(?:trad(?:e|es|ing)|exchang(?:e|es|ing)|barter)\b", prose)
        and (
            re.search(r"\b(?:two players|both players|both sides|both parties|"
                      r"two[- ]party|two[- ]players?|player[- ]to[- ]player|peer[- ]to[- ]peer)\b", prose)
            # Different authored plans express two-sided, consensual trading
            # through sender/receiver matching offers rather than saying
            # "both players" literally. Do not claim one-way sales.
            or (
                re.search(r"\bsender\b", prose)
                and re.search(r"\breceiver\b", prose)
                and re.search(r"\b(?:matching offer|selected offer|confirm)\b", prose)
                and re.search(r"\b(?:exchang|both inventories|trade lifecycle)\w*\b", prose)
            )
            # A server-authored description may identify the two distinct
            # player roles as seller and buyer, with separate offered/wanted
            # assets. This is a bilateral inventory exchange, not an NPC shop.
            or (
                re.search(r"\\bseller(?:'s)?\\b", prose)
                and re.search(r"\\bbuyer(?:'s)?\\b", prose)
                and re.search(r"\\b(?:offered|wanted|transfer|both inventories)\\b", prose)
            )
            # A two-sided asset exchange may be phrased as requester and
            # counterparty, without literally saying "both players".
            or (
                re.search(r"\bcounterparty\b", prose)
                and re.search(r"\b(?:requester|offered items?|offered quantities)\b", prose)
                and re.search(r"\b(?:requested items?|requested quantities|"
                              r"requested amount)\b", prose)
                and re.search(r"\b(?:transfer|exchang|quantit)\w*\b", prose)
            )
        )
        and re.search(r"\b(?:resource|item|inventory|balance)", prose)
        and re.search(r"\b(?:validat|verif|check|reject)", prose)
    )


def render_host_peer_barter(module, proposal):
    if not module.module_id.startswith("dyn_") or module.kind not in (
        ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT
    ):
        return None
    owner_name = (module.name if module.kind == ModuleKind.SERVER_MODULE
                  else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.name == owner_name and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    if not is_bilateral_asset_exchange(prose):
        return None
    if not any(render_host_mining(m, proposal) is not None
               for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(k, v) for k, v in (design.get("host_actions") or {}).items()
              if isinstance(v, dict) and v.get("service") == owner_name]
    if (len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction"
            or routes[0][1].get("max_args") == 0):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        return _SERVER if module.file_path.startswith("src/server/") else None
    return (_CLIENT.replace("__REMOTE__", json.dumps(routes[0][0]))
            if module.file_path.startswith("src/client/") else None)


_SERVER = r'''--!strict
-- Uses real profile-backed resources, Coins and existing earned item IDs.
local Players = game:GetService("Players")
local Service = {}
local LIMIT = 2147483647
local pending = {}
local sequence = 0
local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player") and player.Parent == Players
end
local function validNumber(n)
    return type(n) == "number" and n == n and n % 1 == 0 and n >= 0 and n <= LIMIT
end
local function validAsset(asset)
    return type(asset) == "string" and #asset > 0 and #asset <= 32
        and string.match(asset, "^[%a_][%w_]*$") ~= nil
end
local function owned(services, player, asset)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil end
    local state = manager.GetState(player, "RMMInventory")
    if not state then return nil end
    if asset == "coins" then
        local stats = player:FindFirstChild("leaderstats")
        local obj = stats and stats:FindFirstChild("Coins")
        if not obj or not obj:IsA("IntValue") or not validNumber(obj.Value) then return nil end
        return {kind = "coins", object = obj, amount = obj.Value}
    end
    if asset == "resources" then
        if not validNumber(state.resources) then return nil end
        return {kind = "resources", object = state, amount = state.resources}
    end
    if state.items ~= nil and type(state.items) ~= "table" then return nil end
    local value = state.items and state.items[asset] or 0
    if not validNumber(value) then return nil end
    return {kind = "item", object = state, asset = asset, amount = value}
end
local function setOwned(balance, amount)
    if balance.kind == "coins" then
        balance.object.Value = amount
    elseif balance.kind == "resources" then
        balance.object.resources = amount
    else
        local state = balance.object
        if state.items == nil then state.items = {} end
        state.items[balance.asset] = amount
    end
end
local function reject(reason)
    return {success = false, reason = reason}
end
function Service.start(services)
    assert(type(services) == "table" and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function", "Missing profile API")
    Players.PlayerRemoving:Connect(function(player)
        for id, offer in pairs(pending) do
            if offer.from == player.UserId or offer.to == player.UserId then
                pending[id] = nil
            end
        end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) then return reject("invalid_player") end
    local argc = select("#", ...)
    local action, a, b, c, d, e = ...
    for id, offer in pairs(pending) do
        if offer.expires <= os.clock() then pending[id] = nil end
    end
    if action == "list" and argc == 1 then
        local items = {}
        for id, offer in pairs(pending) do
            if offer.to == player.UserId then
                table.insert(items, {id = id, from = offer.from, giveAsset = offer.giveAsset,
                    giveQty = offer.giveQty, wantAsset = offer.wantAsset, wantQty = offer.wantQty})
            end
        end
        table.sort(items, function(left, right) return left.id < right.id end)
        local ownedItems = {}
        local bag = services.PlayerDataManager.GetState(player, "RMMInventory")
        if type(bag) == "table" then
            if validNumber(bag.resources) and bag.resources > 0 then
                table.insert(ownedItems, {id = "resources", quantity = bag.resources})
            end
            local coin = owned(services, player, "coins")
            if coin and coin.amount > 0 then
                table.insert(ownedItems, {id = "coins", quantity = coin.amount})
            end
            if type(bag.items) == "table" then
                for id, quantity in pairs(bag.items) do
                    if validAsset(id) and validNumber(quantity) and quantity > 0 then
                        table.insert(ownedItems, {id = id, quantity = quantity})
                    end
                end
            end
        end
        table.sort(ownedItems, function(a, b) return a.id < b.id end)
        return {success = true, pending = items, ownedItems = ownedItems}
    end
    if action == "offer" and argc == 6 then
        if not validNumber(a) or a < 1 or not validAsset(b) or not validNumber(c)
            or c < 1 or not validAsset(d) or not validNumber(e) or e < 1 or b == d then
            return reject("invalid_offer")
        end
        local other = Players:GetPlayerByUserId(a)
        if not validPlayer(other) or other == player then return reject("invalid_counterparty") end
        local given = owned(services, player, b)
        local wanted = owned(services, other, d)
        if not given or not wanted then return reject("profile_loading") end
        if given.amount < c or wanted.amount < e then return reject("insufficient_balance") end
        local count = 0
        for _, offer in pairs(pending) do
            if offer.from == player.UserId then
                count += 1
                -- No sender may reserve the same owned asset for multiple
                -- receivers. Actual balances are rechecked at acceptance.
                if offer.giveAsset == b then return reject("trade_in_progress") end
                if offer.to == other.UserId then return reject("duplicate_offer") end
            end
        end
        if count >= 3 then return reject("too_many_offers") end
        sequence += 1
        pending[sequence] = {from = player.UserId, to = other.UserId, giveAsset = b,
            giveQty = c, wantAsset = d, wantQty = e, expires = os.clock() + 45}
        return {success = true, id = sequence}
    end
    if action == "accept" and argc == 2 then
        if not validNumber(a) or a < 1 then return reject("invalid_id") end
        local offer = pending[a]
        if not offer or offer.to ~= player.UserId then return reject("not_your_offer") end
        local other = Players:GetPlayerByUserId(offer.from)
        if not validPlayer(other) then
            pending[a] = nil
            return reject("player_left")
        end
        local giverOut = owned(services, other, offer.giveAsset)
        local giverIn = owned(services, other, offer.wantAsset)
        local takerOut = owned(services, player, offer.wantAsset)
        local takerIn = owned(services, player, offer.giveAsset)
        if not giverOut or not giverIn or not takerOut or not takerIn then
            return reject("profile_loading")
        end
        if giverOut.amount < offer.giveQty or takerOut.amount < offer.wantQty
            or giverIn.amount > LIMIT - offer.wantQty
            or takerIn.amount > LIMIT - offer.giveQty then
            return reject("insufficient_balance")
        end
        -- Non-yielding per-server transition; no fake global DataStore atomicity.
        pending[a] = nil
        setOwned(giverOut, giverOut.amount - offer.giveQty)
        setOwned(takerOut, takerOut.amount - offer.wantQty)
        setOwned(giverIn, giverIn.amount + offer.wantQty)
        setOwned(takerIn, takerIn.amount + offer.giveQty)
        return {success = true, giveAsset = offer.giveAsset, giveQty = offer.giveQty,
            wantAsset = offer.wantAsset, wantQty = offer.wantQty}
    end
    if action == "cancel" and argc == 2 then
        if not validNumber(a) or a < 1 then return reject("invalid_id") end
        local offer = pending[a]
        if not offer or offer.from ~= player.UserId then return reject("not_your_offer") end
        pending[a] = nil
        return {success = true, canceled = true}
    end
    return reject("invalid_action")
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes", 20):WaitForChild(__REMOTE__, 20)
local gui = Instance.new("ScreenGui")
gui.Name = "RMMBarter"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local inputs = {}
local function addInput(name, hint, x, width)
    local box = Instance.new("TextBox")
    box.Name = name
    box.Size = UDim2.fromOffset(width, 32)
    box.Position = UDim2.new(0, x, 1, -150)
    box.PlaceholderText = hint
    box.Text = ""
    box.Parent = gui
    inputs[name] = box
end
addInput("Target", "Player", 10, 130)
addInput("GiveAsset", "Give item", 143, 90)
addInput("GiveQty", "Give qty", 237, 65)
addInput("WantAsset", "Want item", 307, 90)
addInput("WantQty", "Want qty", 402, 65)
local function addButton(name, label, x)
    local b = Instance.new("TextButton")
    b.Name = name
    b.Text = label
    b.Size = UDim2.fromOffset(115, 34)
    b.Position = UDim2.new(0, x, 1, -110)
    b.Parent = gui
    return b
end
local send = addButton("Send", "Offer", 10)
local review = addButton("Review", "Review", 128)
local accept = addButton("Accept", "Accept reviewed", 246)
local cancel = addButton("Cancel", "Cancel my offer", 364)
local itemsText = Instance.new("TextLabel")
itemsText.Name = "OwnedAssets"
itemsText.Size = UDim2.fromOffset(470, 28)
itemsText.Position = UDim2.new(0, 10, 1, -192)
itemsText.Text = "Review server-owned assets to select an item"
itemsText.Parent = gui
local resultText = Instance.new("TextLabel")
resultText.Name = "TradeResult"
resultText.Size = UDim2.fromOffset(480, 40)
resultText.Position = UDim2.new(0, 10, 1, -70)
resultText.Text = "Assets: resources, coins or existing item IDs"
resultText.Parent = gui
local busy = false
local reviewed = nil
local reviewOffset = 0
local lastOffered = nil
local function callRemote(...)
    if busy then return nil end
    busy = true
    local args = table.pack(...)
    local ok, response = pcall(function()
        return remote:InvokeServer(table.unpack(args, 1, args.n))
    end)
    busy = false
    if not ok or type(response) ~= "table" then return nil end
    return response
end
send.Activated:Connect(function()
    local target = Players:FindFirstChild(inputs.Target.Text)
    if not target or not target:IsA("Player") then
        resultText.Text = "Enter exact player name"
        return
    end
    local response = callRemote("offer", target.UserId, inputs.GiveAsset.Text,
        tonumber(inputs.GiveQty.Text), inputs.WantAsset.Text, tonumber(inputs.WantQty.Text))
    if response and response.success then lastOffered = response.id end
    resultText.Text = response and (response.success and
        ("Offer #" .. tostring(response.id) .. " created") or tostring(response.reason))
        or "Network error"
end)
review.Activated:Connect(function()
    reviewed = nil
    local response = callRemote("list")
    if not response or not response.success then
        resultText.Text = "Cannot load trades or owned assets"
        return
    end
    if type(response.ownedItems) == "table" then
        local shown = {}
        for i, entry in ipairs(response.ownedItems) do
            if i > 5 then break end
            table.insert(shown, tostring(entry.id) .. ": " .. tostring(entry.quantity))
        end
        itemsText.Text = #shown > 0 and table.concat(shown, " | ") or "No owned assets"
    end
    if type(response.pending) ~= "table" or #response.pending == 0 then
        resultText.Text = "No pending offers"
        return
    end
    reviewOffset = (reviewOffset % #response.pending) + 1
    local offer = response.pending[reviewOffset]
    reviewed = offer.id
    resultText.Text = "Receive " .. tostring(offer.giveQty) .. " " .. tostring(offer.giveAsset)
        .. ", pay " .. tostring(offer.wantQty) .. " " .. tostring(offer.wantAsset)
end)
cancel.Activated:Connect(function()
    if lastOffered == nil then
        resultText.Text = "No active outgoing offer to cancel"
        return
    end
    local response = callRemote("cancel", lastOffered)
    if response and response.success then lastOffered = nil end
    resultText.Text = response and (response.success and "Offer canceled"
        or tostring(response.reason)) or "Network error"
end)
accept.Activated:Connect(function()
    if reviewed == nil then
        resultText.Text = "Review offer first"
        return
    end
    local id = reviewed
    reviewed = nil
    local response = callRemote("accept", id)
    resultText.Text = response and (response.success and "Trade completed"
        or tostring(response.reason)) or "Network error"
end)
'''