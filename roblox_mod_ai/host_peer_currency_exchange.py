"""Host-owned, consent-based two-player coin exchange.

A non-yielding live-server update is NOT an atomic cross-player DataStore
commit; each player's existing session-locked profile saves independently.
"""
from __future__ import annotations
import json
import re
from .spec import ModuleKind
from .host_mining import render_host_mining


def eligible_peer_currency_exchange(module, proposal):
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    description = owner.description.casefold()
    requirements = (
        r"\btrad(?:e|es|ing)\b", r"\binitiator\b", r"\bcounterparty\b",
        r"\boffered currency\b", r"\breceived amount\b",
        r"\bbalances?\b", r"\bdebits?\b", r"\bcredits?\b",
        r"\b(?:duplicat|stale|replay)\w*\b", r"\b(?:persist|session lock)\w*\b",
    )
    if not all(re.search(pattern, description) for pattern in requirements):
        return None
    if not any(peer.name != server and peer.kind == ModuleKind.SERVER_MODULE
               and render_host_mining(peer, proposal) is not None
               for peer in proposal.modules):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    matches = [(name, action) for name, action in (design.get("host_actions") or {}).items()
               if isinstance(action, dict) and action.get("service") == server]
    if len(matches) != 1:
        return None
    remote, route = matches[0]
    max_args = route.get("max_args")
    if (route.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (max_args is not None and (type(max_args) is not int or max_args < 4))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):
            return None
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if linked is not None and remote not in linked:
        return None
    return server, remote


def render_host_peer_currency_exchange(module, proposal):
    match = eligible_peer_currency_exchange(module, proposal)
    if match is None:
        return None
    return _SERVER if module.kind == ModuleKind.SERVER_MODULE else _CLIENT.replace("__REMOTE__", json.dumps(match[1]))


_SERVER = r'''--!strict
-- Same-server exchange only; per-user DataStore saves are NOT atomic as a pair.
local Players = game:GetService("Players")
local Service = {}
local MAX_COIN = 2147483647
local MAX_AMOUNT = 1000000
local offers = {}
local sequence = 0
local function reject(reason) return {success = false, reason = reason} end
local function validPlayer(p)
    return typeof(p) == "Instance" and p:IsA("Player") and p.Parent == Players
end
local function amount(n, positive)
    return type(n) == "number" and n == n and n % 1 == 0
        and n >= (positive and 1 or 0) and n <= MAX_AMOUNT
end
local function balance(p, services)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil, nil end
    local ledger = manager.GetState(p, "RMMTrades")
    local stats = p:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if type(ledger) ~= "table" or not coins or not coins:IsA("IntValue")
        or coins.Value < 0 or coins.Value > MAX_COIN then return nil, nil end
    return coins, ledger
end
local function prune()
    for id, record in pairs(offers) do
        if record.expires <= os.clock() then offers[id] = nil end
    end
end
function Service.start(services)
    assert(type(services) == "table" and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function",
        "Two-party trade requires session-locked host player data")
    Players.PlayerRemoving:Connect(function(player)
        for id, record in pairs(offers) do
            if record.from == player.UserId or record.to == player.UserId then offers[id] = nil end
        end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) then return reject("invalid_player") end
    local argc = select("#", ...)
    local action, a, b, c = ...
    if type(action) ~= "string" then return reject("invalid_action") end
    prune()
    if action == "list" and argc == 1 then
        local pending = {}
        for id, record in pairs(offers) do
            if record.to == player.UserId then
                table.insert(pending, {id = id, from = record.from,
                    offered = record.offered, wanted = record.wanted})
            end
        end
        table.sort(pending, function(x, y) return x.id < y.id end)
        return {success = true, pending = pending}
    end
    if action == "offer" and argc == 4 then
        if not amount(a, true) or not amount(b, true) or not amount(c, false)
            or b == c then return reject("invalid_offer") end
        local other = Players:GetPlayerByUserId(a)
        if not validPlayer(other) or other == player then return reject("invalid_counterparty") end
        local fromCoins = balance(player, services)
        local toCoins = balance(other, services)
        if not fromCoins or not toCoins then return reject("profile_loading") end
        if fromCoins.Value < b or toCoins.Value < c then return reject("insufficient_balance") end
        local count = 0
        for _, record in pairs(offers) do
            if record.from == player.UserId then
                count += 1
                if record.to == a then return reject("duplicate_offer") end
            end
        end
        if count >= 3 then return reject("too_many_offers") end
        sequence += 1
        offers[sequence] = {from = player.UserId, to = a, offered = b,
            wanted = c, expires = os.clock() + 45}
        return {success = true, id = sequence}
    end
    if action == "accept" and argc == 2 then
        if not amount(a, true) then return reject("invalid_offer_id") end
        local offer = offers[a]
        if not offer or offer.to ~= player.UserId then return reject("not_your_offer") end
        local sender = Players:GetPlayerByUserId(offer.from)
        if not validPlayer(sender) then offers[a] = nil; return reject("sender_left") end
        local senderCoins, senderLedger = balance(sender, services)
        local receiverCoins, receiverLedger = balance(player, services)
        if not senderCoins or not receiverCoins then return reject("profile_loading") end
        local fromAmount, toAmount = offer.offered, offer.wanted
        if senderCoins.Value < fromAmount or receiverCoins.Value < toAmount then
            return reject("insufficient_balance")
        end
        local senderAfter = senderCoins.Value - fromAmount + toAmount
        local receiverAfter = receiverCoins.Value - toAmount + fromAmount
        if senderAfter > MAX_COIN or receiverAfter > MAX_COIN then return reject("overflow") end
        -- Neither action below yields, and consuming the offer prevents replay.
        -- These records are saved later, separately, by PlayerDataManager.
        offers[a] = nil
        senderCoins.Value = senderAfter
        receiverCoins.Value = receiverAfter
        senderLedger.lastExchange = {id = a, peer = player.UserId,
            offered = fromAmount, received = toAmount}
        receiverLedger.lastExchange = {id = a, peer = sender.UserId,
            offered = toAmount, received = fromAmount}
        return {success = true, id = a, initiatorBalance = senderAfter,
            counterpartyBalance = receiverAfter}
    end
    if action == "cancel" and argc == 2 then
        if not amount(a, true) then return reject("invalid_offer_id") end
        if not offers[a] or offers[a].from ~= player.UserId then return reject("not_your_offer") end
        offers[a] = nil
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
local folder = ReplicatedStorage:WaitForChild("Remotes", 20)
if not folder then error("Remotes unavailable") end
local remote = folder:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Trading unavailable") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMCurrencyExchange"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local function input(name, hint, y)
    local box = Instance.new("TextBox")
    box.Name = name
    box.PlaceholderText = hint
    box.Text = ""
    box.Size = UDim2.fromOffset(245, 35)
    box.Position = UDim2.fromOffset(12, y)
    box.Parent = gui
    return box
end
local target = input("Target", "Online player name", 180)
local offered = input("Offered", "Coins offered", 220)
local wanted = input("Wanted", "Coins requested (0 allowed)", 260)
local status = Instance.new("TextLabel")
status.Name = "Result"
status.Size = UDim2.fromOffset(475, 40)
status.Position = UDim2.fromOffset(12, 355)
status.Text = "Both players must approve the trade"
status.Parent = gui
local busy = false
local lastOffer = nil
local reviewed = nil
local function request(...)
    if busy then return nil end
    busy = true
    local packed = table.pack(...)
    local ok, result = pcall(function()
        return remote:InvokeServer(table.unpack(packed, 1, packed.n))
    end)
    busy = false
    return ok and type(result) == "table" and result or nil
end
local function button(name, title, x, callback)
    local b = Instance.new("TextButton")
    b.Name = name
    b.Text = title
    b.Size = UDim2.fromOffset(109, 35)
    b.Position = UDim2.fromOffset(x, 307)
    b.Parent = gui
    b.Activated:Connect(callback)
end
button("Offer", "Offer", 12, function()
    local other = Players:FindFirstChild(target.Text)
    if not other or not other:IsA("Player") then status.Text = "Choose online player"; return end
    local reply = request("offer", other.UserId, tonumber(offered.Text), tonumber(wanted.Text))
    if reply and reply.success then lastOffer = reply.id end
    status.Text = reply and (reply.success and ("Offer " .. tostring(reply.id) .. " sent")
        or tostring(reply.reason)) or "Network error"
end)
button("Review", "Review", 127, function()
    reviewed = nil
    local reply = request("list")
    if reply and reply.success and #reply.pending > 0 then
        local row = reply.pending[1]
        reviewed = row.id
        status.Text = "From " .. tostring(row.from) .. ": get " .. tostring(row.offered)
            .. ", pay " .. tostring(row.wanted) .. " Coins"
    else
        status.Text = "No incoming offers"
    end
end)
button("Accept", "Accept", 242, function()
    if not reviewed then status.Text = "Review offer first"; return end
    local reply = request("accept", reviewed)
    reviewed = nil
    status.Text = reply and (reply.success and "Exchange confirmed"
        or tostring(reply.reason)) or "Network error"
end)
button("Cancel", "Cancel", 357, function()
    if not lastOffer then return end
    local reply = request("cancel", lastOffer)
    lastOffer = nil
    status.Text = reply and (reply.success and "Offer canceled"
        or tostring(reply.reason)) or "Network error"
end)
'''