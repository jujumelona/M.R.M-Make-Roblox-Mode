"""Server-authored earned currency projection and verified mining receipts.

Client RemoteFunction access only provides a snapshot. The only crediting path
is a server-to-server call checking a real host mining producer's monotonic,
persisted cumulative extraction count. Never grant client-supplied amounts.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind


def matching_ledger(proposal: Any) -> tuple[str, str] | None:
    """Detect an authored single authoritative earn-ledger; not module names."""
    dynamic = proposal.game_design.get("dynamic_design") or {}
    remotes = dynamic.get("remotes") or {}
    actions = dynamic.get("host_actions") or {}
    matches = []
    for owner in getattr(proposal, "modules", []):
        if not owner.module_id.startswith("dyn_") or owner.kind != ModuleKind.SERVER_MODULE:
            continue
        desc = owner.description.casefold()
        # A real world-node mining owner already grants its earned rewards.
        # Calling the same RemoteFunction an independent currency *ledger*
        # would claim two incompatible host implementations and mask the
        # actual mining action. A projection ledger is a separate service.
        from .host_mining_nodes import mining_world_nodes
        service_tokens = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", owner.name)
        source_nodes = ((dynamic.get("module_world_objects") or {})
                        .get(owner.module_id) or [])
        is_mining_owner = (
            re.search(r"\b(?:mining|mine|gather|gathering|harvest|ore)\b",
                      service_tokens, re.I)
            and re.search(r"\b(?:mine|mining|gather|harvest|resource)\w*\b", desc)
            and source_nodes
            and mining_world_nodes(proposal, owner)
        )
        if is_mining_owner:
            continue
        if (not re.search(r"\b(?:currency|coins?|credits?)\s+balances?\b", desc)
                or not re.search(r"\b(?:sole owner|server.authoritative|server[- ]owned)\b", desc)
                or not re.search(r"\bearn(?:ing)?\s+(?:event|source)\b", desc)
                or not re.search(r"\b(?:duplicat|negativ|out.of.range|invalid)\w*\b", desc)
                or not re.search(r"\b(?:publish|replicat|client)\w*\b", desc)):
            continue
        linked = [(name, action) for name, action in actions.items()
                  if isinstance(action, dict) and action.get("service") == owner.name]
        if len(linked) != 1:
            continue
        remote, route = linked[0]
        max_args = route.get("max_args")
        if (route.get("kind") != "RemoteFunction" or remotes.get(remote) != "RemoteFunction"
                or (max_args is not None and
                    (type(max_args) is not int or max_args < 1))):
            continue
        if not owner.file_path.startswith("src/server/"):
            continue
        matches.append((owner.name, remote))
    return matches[0] if len(matches) == 1 else None


def eligible_earned_currency(module: Any, proposal: Any) -> tuple[str, str] | None:
    found = matching_ledger(proposal)
    if found is None or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT):
        return None
    server, remote = found
    if module.kind == ModuleKind.SERVER_MODULE:
        if module.name != server:
            return None
    else:
        if module.name != server.removesuffix("Server") + "Client":
            return None
        if not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):
            return None
        linked = ((proposal.game_design.get("dynamic_design") or {})
                  .get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    # At least one REAL source-owned mining mechanism is required. This doesn't
    # invent a money faucet just because the ledger mentions earning.
    from .host_mining import render_host_mining
    sources = [peer for peer in getattr(proposal, "modules", [])
               if peer.kind == ModuleKind.SERVER_MODULE and peer.name != server
               and render_host_mining(peer, proposal) is not None]
    if not sources:
        return None
    return found


def render_host_earned_currency(module: Any, proposal: Any) -> str | None:
    selected = eligible_earned_currency(module, proposal)
    if selected is None:
        return None
    _, remote = selected
    return (_SERVER if module.kind == ModuleKind.SERVER_MODULE else
            _CLIENT.replace("__REMOTE__", json.dumps(remote)))


_SERVER = r'''--!strict
-- An untrusted caller can read its own balance but never grant money.
local Players = game:GetService("Players")
local Service = {}
local LIMIT = 2147483647
local function coinsFor(player)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players then return nil end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value < 0 then return nil end
    return coins
end
local function publish(player)
    local coins = coinsFor(player)
    if not coins then return nil end
    player:SetAttribute("RMMCurrencyBalance", coins.Value)
    return coins.Value
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Earned currency requires the host profile and income source")
    services.PlayerDataManager.OnReady(function(player)
        local stats = player:FindFirstChild("leaderstats")
        local coins = stats and stats:FindFirstChild("Coins")
        if coins and coins:IsA("IntValue") then
            coins.Changed:Connect(function() publish(player) end)
        end
        publish(player)
    end)
end

-- Host mining calls this only AFTER it mutates server-owned totalMined.
-- The amount is derived from server-persisted proof, never remote arguments.
function Service.recordMiningReward(player, services)
    local coins = coinsFor(player)
    if not coins then return false end
    local manager = services.PlayerDataManager
    local inv = manager.GetState(player, "RMMInventory")
    local record = manager.GetState(player, "RMMCurrencyMiningLedger")
    if type(inv) ~= "table" or type(record) ~= "table" then return false end
    local mined = inv.totalMined
    local paid = record.paidThrough
    if paid == nil then paid = 0 end
    if type(mined) ~= "number" or mined ~= mined or mined % 1 ~= 0
        or mined <= 0 or mined > LIMIT
        or type(paid) ~= "number" or paid ~= paid or paid % 1 ~= 0
        or paid < 0 or paid > LIMIT then return false end
    local unpaid = mined - paid
    -- A single mining interaction cannot produce unbounded rewards.
    if unpaid <= 0 or unpaid > 32 or coins.Value > LIMIT - unpaid then return false end
    coins.Value += unpaid
    record.paidThrough = mined
    publish(player)
    return true
end

function Service.handleAction(player, _services, ...)
    if select("#", ...) > 1 then
        return {success = false, reason = "read_only"}
    end
    if select("#", ...) == 1 and ... ~= "balance" then
        return {success = false, reason = "read_only"}
    end
    local amount = publish(player)
    if amount == nil then return {success = false, reason = "profile_loading"} end
    return {success = true, balance = amount}
end
return Service
'''

_CLIENT = r'''--!strict
-- Client always displays a server-published balance, never speculative income.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Missing balance route") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMEarnedCurrencyHud"
gui.ResetOnSpawn = false
local playerGui = player:WaitForChild("PlayerGui")
if playerGui:FindFirstChild("RMMEarnedCurrencyHud") then return end
gui.Parent = playerGui
local text = Instance.new("TextLabel")
text.Name = "AuthoritativeBalance"
text.Size = UDim2.fromOffset(260, 55)
text.Position = UDim2.new(1, -278, 0, 20)
text.Text = "Coins: loading..."
text.Parent = gui
local last = nil
local function show(value)
    if type(value) ~= "number" or value < 0 or value % 1 ~= 0 then return end
    if last ~= nil and value > last then
        text.Text = "Coins: " .. tostring(value) .. " (earned +" .. tostring(value-last) .. ")"
    else
        text.Text = "Coins: " .. tostring(value)
    end
    last = value
end
player:GetAttributeChangedSignal("RMMCurrencyBalance"):Connect(function()
    show(player:GetAttribute("RMMCurrencyBalance"))
end)
local function refresh()
    local ok, result = pcall(function() return remote:InvokeServer("balance") end)
    if ok and type(result) == "table" and result.success == true then
        show(result.balance)
    end
end
task.defer(refresh)
'''