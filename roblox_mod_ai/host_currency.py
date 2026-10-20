"""Host-owned projection of the single authoritative earned-currency ledger.

Currency accumulation is NOT an independent player-requested mint action:
mining, selling, missions and purchases are the server-validated writers.
The generated RemoteEvent can request a read-only refresh, never add Coins.
"""
from __future__ import annotations

import json
import re

from .host_mining import render_host_mining
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


_ROLE = re.compile(r"^(?:CurrencyAccumulation|EarnedCurrencyAcquisition)", re.I)


def render_host_currency(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)
            or not _ROLE.search(module.name)):
        return None
    description = module.description.casefold()
    if ("currency" not in description
            or not any(x in description for x in ("balance", "earned", "validated", "mining"))):
        return None
    # This observer must have a real server-authoritative earning path.
    if not any(render_host_mining(peer, proposal) is not None
               for peer in proposal.modules
               if peer.kind == ModuleKind.SERVER_MODULE):
        return None
    service = (module.name if module.kind == ModuleKind.SERVER_MODULE
               else module.name.removesuffix("Client") + "Server")
    design = proposal.game_design.get("dynamic_design") or {}
    bound = [(name, row) for name, row in
             (design.get("host_actions") or {}).items()
             if isinstance(row, dict) and row.get("service") == service]
    if len(bound) != 1 or bound[0][1].get("kind") != "RemoteEvent":
        return None
    if bound[0][1].get("max_args") not in (None, 0):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
        return _SERVER
    if not module.file_path.startswith("src/client/"):
        return None
    return _CLIENT.replace("__REMOTE__", json.dumps(bound[0][0]))


_SERVER = r'''--!strict
-- Mirror the actual server-owned Coins into player attributes for HUD consumers.
-- The client can request a refresh, but never supplies values or claims rewards.
local Players = game:GetService("Players")
local Service = {}
local connections = setmetatable({}, {__mode = "k"})

local function projectBalance(player)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or player.Parent ~= Players then
        return false
    end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") then return false end
    player:SetAttribute("RMMCurrencyBalance", coins.Value)
    return true
end
function Service.start(services)
    assert(type(services) == "table" and
        type(services.PlayerDataManager) == "table" and
        type(services.PlayerDataManager.OnReady) == "function",
        "Currency projection requires host-managed player profile")
    services.PlayerDataManager.OnReady(function(player)
        if connections[player] then connections[player]:Disconnect() end
        local stats = player:FindFirstChild("leaderstats")
        local coins = stats and stats:FindFirstChild("Coins")
        if not coins or not coins:IsA("IntValue") then return end
        connections[player] = coins.Changed:Connect(function()
            projectBalance(player)
        end)
        projectBalance(player)
    end)
    Players.PlayerRemoving:Connect(function(player)
        if connections[player] then
            connections[player]:Disconnect()
            connections[player] = nil
        end
    end)
end
function Service.handleAction(player, _services, ...)
    if select("#", ...) ~= 0 then return false end
    return projectBalance(player)
end
return Service
'''

_CLIENT = r'''--!strict
-- HUD reads replicated trusted values; refresh event cannot award currency.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local playerGui = player:WaitForChild("PlayerGui")
-- Multiple requested currency observers share one HUD, not overlapping clones.
if playerGui:FindFirstChild("RMMEarnedCurrencyHud") then return end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMEarnedCurrencyHud"
gui.ResetOnSpawn = false
gui.Parent = playerGui
local label = Instance.new("TextLabel")
label.Name = "CurrencyBalance"
label.Size = UDim2.fromOffset(200, 42)
label.Position = UDim2.new(1, -216, 0, 22)
label.Parent = gui
local button = Instance.new("TextButton")
button.Name = "RefreshCurrency"
button.Size = UDim2.fromOffset(140, 33)
button.Position = UDim2.new(1, -156, 0, 67)
button.Text = "Refresh balance"
button.Parent = gui
local function refresh()
    local value = player:GetAttribute("RMMCurrencyBalance")
    label.Text = "Earned coins: " .. (type(value) == "number" and tostring(value) or "loading")
end
player:GetAttributeChangedSignal("RMMCurrencyBalance"):Connect(refresh)
button.Activated:Connect(function() remote:FireServer() end)
refresh()
remote:FireServer()
'''