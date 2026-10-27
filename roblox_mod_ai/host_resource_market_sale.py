"""Deterministic host-owned, source-authorized mined-resource sale.

An atomic market settlement is core server infrastructure, not Luau for a 9B
model to invent. Only an already-authored server market action with the exact
selection/quantity transport and a verified mining producer can use it.
Prices are explicit first-party game defaults (one Coin per mined resource),
not client input, an invented DataStore namespace, or a peer transfer.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind


def eligible_resource_market_sale(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not getattr(module, "module_id", "").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    d = (proposal.game_design.get("dynamic_design") or {})
    remote_links = d.get("module_remotes") or {}
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in proposal.modules
                  if m.name == server and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None or not owner.file_path.startswith("src/server/"):
        return None
    desc = owner.description.casefold()
    # The author explicitly promised a PLAYER-OWNED RESOURCE -> MONEY exchange.
    if not all(re.search(s, desc, re.I) for s in (
        r"\b(?:sale|sell|market)\b",
        r"\b(?:resource|ore|mineral)\b",
        r"\b(?:price|priced)\b",
        r"\b(?:quantity|amount|stock)\b",
        r"\b(?:deduct|subtract|consume|debit)\w*\b",
        r"\b(?:credit|earn|money|coins|currency)\w*\b",
        r"\b(?:owner|owned|inventory)\b",
    )):
        return None
    if re.search(r"\b(?:peer[- ]to[- ]peer|player[- ]to[- ]player|"
                 r"weapon|ship\s+part\s+purchase|refund)\b", desc, re.I):
        return None
    routes = [(name, binding) for name, binding in
              (d.get("host_actions") or {}).items()
              if isinstance(binding, dict) and binding.get("service") == server]
    if len(routes) != 1:
        return None
    remote, route = routes[0]
    if (route.get("kind") != "RemoteFunction"
            or (d.get("remotes") or {}).get(remote) != "RemoteFunction"
            or route.get("max_args", 1) != 1):
        return None
    typed = (d.get("host_typed_actions") or {}).get(remote)
    if not isinstance(typed, dict) or not typed.get("transport_only"):
        return None
    if (typed.get("server") != server
            or typed.get("client") != server.removesuffix("Server") + "Client"):
        return None
    contract = typed.get("contract") or {}
    fields = contract.get("inputs") or []
    if (not isinstance(fields, list) or len(fields) != 2
            or {(x.get("id"), x.get("type")) for x in fields if isinstance(x, dict)}
            != {("selection", "text"), ("quantity", "integer")}):
        return None
    if any(field.get("id") == "quantity"
           and (field.get("min") != 1 or field.get("max") != 10000)
           for field in fields):
        return None
    if remote_links.get(owner.module_id) not in (None, [remote]):
        return None
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        if (module.name != server.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")
                or remote_links.get(module.module_id) not in (None, [remote])):
            return None
    # Do not mint sellable inventory without a real source-owned miner.
    from .host_mining import render_host_mining
    miners = [
        m for m in proposal.modules
        if m.name != server and m.kind == ModuleKind.SERVER_MODULE
        and render_host_mining(m, proposal) is not None
    ]
    if not miners:
        return None
    return server, remote


def render_resource_market_sale(module: Any, proposal: Any) -> str | None:
    verified = eligible_resource_market_sale(module, proposal)
    if verified is None:
        return None
    _, remote = verified
    code = _SERVER if module.kind == ModuleKind.SERVER_MODULE else _CLIENT
    return code.replace("__REMOTE__", json.dumps(remote))


_SERVER = r'''--!strict
-- First-party market: a fixed server price; no client-supplied exchange rate.
local Players = game:GetService("Players")
local Service = {}
local MAX_BALANCE = 2147483647
local PRICE_PER_RESOURCE = 1
local LAST_SALE = setmetatable({}, {__mode = "k"})
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function",
        "Market requires the server-authoritative player profile")
    Players.PlayerRemoving:Connect(function(player)
        LAST_SALE[player] = nil
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_player_or_payload"}
    end
    local payload = ...
    if type(payload) ~= "table" or payload.selection ~= "resources"
        or type(payload.quantity) ~= "number" then
        return {success = false, reason = "invalid_selection"}
    end
    local quantity = payload.quantity
    if quantity ~= quantity or quantity % 1 ~= 0
        or quantity < 1 or quantity > 10000 then
        return {success = false, reason = "invalid_quantity"}
    end
    local now = os.clock()
    local previous = LAST_SALE[player]
    if previous and now - previous < 0.3 then
        return {success = false, reason = "cooldown"}
    end
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return {success = false, reason = "missing_profile"}
    end
    local inventory = manager.GetState(player, "RMMInventory")
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if type(inventory) ~= "table" or not coins or not coins:IsA("IntValue") then
        return {success = false, reason = "profile_not_ready"}
    end
    local resources = inventory.resources
    local balance = coins.Value
    if type(resources) ~= "number" or resources ~= resources
        or resources % 1 ~= 0 or resources < quantity
        or resources > MAX_BALANCE
        or balance < 0 or balance > MAX_BALANCE then
        return {success = false, reason = "insufficient_or_invalid_balance"}
    end
    local payout = quantity * PRICE_PER_RESOURCE
    if payout > MAX_BALANCE - balance then
        return {success = false, reason = "currency_overflow"}
    end
    -- Both authoritative mutations run without yields. The existing
    -- PlayerDataManager persists RMMInventory and leaderstats.Coins.
    inventory.resources = resources - quantity
    coins.Value = balance + payout
    LAST_SALE[player] = now
    return {success = true, resources = inventory.resources,
        coins = coins.Value, earned = payout}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local folder = ReplicatedStorage:WaitForChild("Remotes", 20)
if not folder then error("Missing host Remotes") end
local remote = folder:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Market Remote mismatch") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMResourceMarket"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(260, 140)
panel.Position = UDim2.new(1, -280, 0, 160)
panel.Parent = gui
local title = Instance.new("TextLabel")
title.Size = UDim2.fromOffset(260, 36)
title.Text = "Sell mined resources (1 Coin each)"
title.Parent = panel
local amount = Instance.new("TextBox")
amount.Size = UDim2.fromOffset(250, 36)
amount.Position = UDim2.fromOffset(5, 40)
amount.Text = "1"
amount.ClearTextOnFocus = false
amount.Parent = panel
local sell = Instance.new("TextButton")
sell.Size = UDim2.fromOffset(250, 30)
sell.Position = UDim2.fromOffset(5, 81)
sell.Text = "Sell resources"
sell.Parent = panel
local busy = false
sell.Activated:Connect(function()
    if busy then return end
    local quantity = tonumber(amount.Text)
    if not quantity or quantity % 1 ~= 0
        or quantity < 1 or quantity > 10000 then
        title.Text = "Choose 1-10000 resources"
        return
    end
    busy = true
    local ok, result = pcall(function()
        return remote:InvokeServer({selection = "resources", quantity = quantity})
    end)
    busy = false
    if ok and type(result) == "table" and result.success == true then
        title.Text = "Sold! Coins: " .. tostring(result.coins)
    else
        title.Text = "Sale rejected: " ..
            tostring(ok and type(result) == "table" and result.reason or "network")
    end
end)
'''.replace("__REMOTE__", "__REMOTE__")
