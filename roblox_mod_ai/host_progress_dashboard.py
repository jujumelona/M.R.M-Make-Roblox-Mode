"""Host-owned cross-system progress dashboard for compositional Roblox games.

This module does NOT mint resources or implement imaginary catch-all gameplay.
Domain-specific server services own changes; the coordinator offers only a
server-authoritative, read-only snapshot to a paired client. Selecting this
requires a separately routed collection of actual gameplay modules.
"""
from __future__ import annotations

import json
import re
from typing import Any
from .spec import ModuleKind


def eligible_progress_dashboard(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((p for p in getattr(proposal, "modules", [])
                  if p.kind == ModuleKind.SERVER_MODULE and p.name == server), None)
    if owner is None:
        return None
    desc = owner.description.casefold()
    # Semantic contract, not generated module names, game title, or prompt.
    if (not re.search(r"\b(?:progression|progress)\b", desc)
            or not re.search(r"\b(?:authoritative|server[- ]owned)\b", desc)
            or not re.search(r"\b(?:state|status)\b", desc)
            or not re.search(r"\b(?:currency|coins?|credits?)\b", desc)
            or not re.search(r"\b(?:ship|vehicle|vessel)\b", desc)
            or not re.search(r"\b(?:upgrade|performance)\w*\b", desc)
            or not re.search(r"\b(?:expand|expansion|settlement|coloniz)\w*\b", desc)):
        return None
    # Only a coordinating facade: independent feature owners must actually
    # be planned so the facade cannot silently replace their functionality.
    peers = [p for p in getattr(proposal, "modules", []) if
             p.kind == ModuleKind.SERVER_MODULE and p is not owner
             and p.module_id.startswith("dyn_")]
    categories = (
        r"\b(?:mine|mining|harvest|gather|resource)\w*\b",
        r"\b(?:trad|purchas|buy|shop|currency)\w*\b",
        r"\b(?:assem|build|construct|part|ship)\w*\b",
        r"\b(?:launch|travel|planet|settle|coloniz|expansion)\w*\b",
    )
    if sum(any(re.search(rule, p.description.casefold()) for p in peers)
           for rule in categories) < 3:
        return None
    dynamic = proposal.game_design.get("dynamic_design") or {}
    bound = [(name, action) for name, action in (dynamic.get("host_actions") or {}).items()
             if isinstance(action, dict) and action.get("service") == server]
    if len(bound) != 1 or bound[0][1].get("kind") != "RemoteFunction":
        return None
    remote = bound[0][0]
    if (dynamic.get("remotes") or {}).get(remote) != "RemoteFunction":
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if (not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (dynamic.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    return server, remote


def render_host_progress_dashboard(module: Any, proposal: Any) -> str | None:
    selected = eligible_progress_dashboard(module, proposal)
    if selected is None:
        return None
    _, remote = selected
    return (_SERVER if module.kind == ModuleKind.SERVER_MODULE else
            _CLIENT.replace("__REMOTE__", json.dumps(remote)))


_SERVER = r'''--!strict
-- No externally supplied resource/currency amounts. Transactions are owned
-- by separately routed service modules (mining, purchasing, crafting, etc.).
local Players = game:GetService("Players")
local Service = {}

local function countOwned(data)
    if type(data) ~= "table" then return nil end
    local count = 0
    for _, owned in pairs(data) do
        if owned == true or (type(owned) == "table" and owned.owned == true) then
            count += 1
        end
    end
    return count
end
local function coinsOf(player)
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") then return nil end
    if coins.Value < 0 then return nil end
    return coins.Value
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function",
        "A real loaded host profile is required")
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players then return {success = false, reason = "invalid_player"} end
    local argc = select("#", ...)
    if argc > 1 then return {success = false, reason = "invalid_request"} end
    local action = ...
    if argc == 1 and action ~= "snapshot" then
        return {success = false, reason = "use_domain_service"}
    end
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return {success = false, reason = "profile_unavailable"}
    end
    local inventory = manager.GetState(player, "RMMInventory")
    if not inventory then return {success = false, reason = "profile_loading"} end
    local ship = manager.GetState(player, "RMMShipSections")
    local upgrades = manager.GetState(player, "RMMUpgradePurchases")
    local purchased = manager.GetState(player, "RMMCatalogPurchases")
    if not ship or not upgrades or not purchased then
        return {success = false, reason = "profile_loading"}
    end
    local resources = type(inventory.resources) == "number" and inventory.resources or nil
    if resources and (resources ~= resources or resources < 0) then resources = nil end
    return {success = true, coins = coinsOf(player), resources = resources,
        installedParts = countOwned(ship.sections),
        upgrades = countOwned(upgrades), shopPurchases = countOwned(purchased),
        performance = player:GetAttribute("RMMShipPerformance"),
        inSpace = player:GetAttribute("RMMInSpace"),
        spaceUnlocked = player:GetAttribute("RMMSpaceUnlocked")}
end
return Service
'''

_CLIENT = r'''--!strict
-- The dedicated feature UIs handle all transactions; this facade only
-- displays server-confirmed status and never pretends to implement them.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing Remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Status RemoteFunction unavailable") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMProgressDashboard"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(260, 230)
panel.Position = UDim2.fromOffset(12, 120)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 135)
status.TextWrapped = true
status.Text = "Loading authoritative progress..."
status.Parent = panel
local refresh = Instance.new("TextButton")
refresh.Name = "RefreshProgress"
refresh.Text = "Refresh progress"
refresh.Size = UDim2.new(1, 0, 0, 36)
refresh.Parent = panel
local busy = false
local function show(value)
    if value == nil then return "?" end
    return tostring(value)
end
local function update()
    if busy then return end
    busy = true
    local ok, result = pcall(function() return remote:InvokeServer("snapshot") end)
    busy = false
    if not ok or type(result) ~= "table" or result.success ~= true then
        status.Text = "Progress unavailable (profile not ready)"
        return
    end
    status.Text = "Coins: " .. show(result.coins) .. "  Resources: " .. show(result.resources)
        .. "\nShip parts: " .. show(result.installedParts)
        .. "  Upgrades: " .. show(result.upgrades)
        .. "\nPurchased: " .. show(result.shopPurchases)
        .. "  Performance: " .. show(result.performance)
        .. "\nSpace unlocked: " .. show(result.spaceUnlocked)
        .. "  In space: " .. show(result.inSpace)
end
refresh.Activated:Connect(update)
task.defer(update)
'''