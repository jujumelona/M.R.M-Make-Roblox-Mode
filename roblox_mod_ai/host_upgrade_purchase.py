"""Deterministic purchase contract across client GUI and authoritative server.

The role only matches a source-claimed weapon/crew/ship purchase service with
one declared RemoteFunction. Price, identity, state, remotes and UI are host
owned. The stored bonuses are public attributes for other game services;
this is not a complete weapon, crew NPC or vehicle simulation.
"""
from __future__ import annotations

import json
import re
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal

_ROLE = re.compile(r"^TradingBasedWeaponCrewAnd[A-Za-z0-9]*Server$", re.I)


def render_host_upgrade_purchase(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    if not _ROLE.fullmatch(server):
        return None
    owner = next((m for m in proposal.modules
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    description = owner.description.casefold()
    prompt = proposal.requested_prompt.casefold()
    if (not all(t in description for t in ("weapon", "crew", "ship", "currency",
                                           "upgrade", "purchase", "inventory"))
            or not any(x in prompt for x in ("무기", "weapon"))
            or not any(x in prompt for x in ("선원", "crew"))):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    bound = [(name, binding) for name, binding in
             (design.get("host_actions") or {}).items()
             if isinstance(binding, dict) and binding.get("service") == server]
    if len(bound) != 1:
        return None
    remote, binding = bound[0]
    if (not isinstance(remote, str)
            or binding.get("kind") != "RemoteFunction"
            or binding.get("max_args") == 0
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        return _SERVER if module.file_path.startswith("src/server/") else None
    if not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):
        return None
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if linked is not None and remote not in linked:
        return None
    return _CLIENT.replace("__REMOTE__", json.dumps(remote))


_SERVER = r'''--!strict
-- All upgrades use the same server-owned saved currency and ownership records.
local Players = game:GetService("Players")
local Service = {}
local CATALOG = {
    weapon = {cost = 50, attribute = "RMMWeaponDamageBonus", amount = 5},
    crew = {cost = 80, attribute = "RMMCrewCapacityBonus", amount = 1},
    ship = {cost = 120, attribute = "RMMShipSpeedBonus", amount = 10},
}
local recent = setmetatable({}, {__mode = "k"})
local function publish(player, purchases)
    for id, item in pairs(CATALOG) do
        player:SetAttribute(item.attribute, purchases[id] == true and item.amount or 0)
    end
end
function Service.start(services)
    assert(type(services) == "table" and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Host player data must be loaded for purchases")
    services.PlayerDataManager.OnReady(function(player)
        local purchases = services.PlayerDataManager.GetState(player, "RMMUpgradePurchases")
        if purchases then publish(player, purchases) end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then return false end
    local itemId = ...
    if type(itemId) ~= "string" then return false end
    local item = CATALOG[itemId]
    if not item then return false end
    local purchases = services.PlayerDataManager.GetState(player, "RMMUpgradePurchases")
    if not purchases or purchases[itemId] ~= nil then return false end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value < item.cost
        or coins.Value < 0 then return false end
    local now = os.clock()
    if recent[player] and now - recent[player] < 0.25 then return false end
    recent[player] = now
    -- No yield between cost/ownership checks and both committed mutations.
    coins.Value -= item.cost
    purchases[itemId] = true
    publish(player, purchases)
    return {success = true, purchased = itemId, credits = coins.Value}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
if not remote:IsA("RemoteFunction") then error("Wrong upgrade Remote") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMUpgradePurchasePanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(245, 235)
panel.Position = UDim2.new(1, -260, 0, 180)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Padding = UDim.new(0, 4)
layout.Parent = panel
local title = Instance.new("TextLabel")
title.Size = UDim2.new(1, 0, 0, 30)
title.Text = "Weapon / crew / ship upgrades"
title.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 34)
status.Text = "The server validates every purchase"
status.Parent = panel
local catalog = {
    {id = "weapon", label = "Weapon damage +5", cost = 50},
    {id = "crew", label = "Crew capacity +1", cost = 80},
    {id = "ship", label = "Ship speed +10", cost = 120},
}
local busy = false
for _, entry in catalog do
    local button = Instance.new("TextButton")
    button.Name = entry.id
    button.Size = UDim2.new(1, 0, 0, 42)
    button.Text = entry.label .. " - " .. tostring(entry.cost) .. " Coins"
    button.Parent = panel
    button.Activated:Connect(function()
        if busy then return end
        busy = true
        button.Active = false
        local ok, result = pcall(function() return remote:InvokeServer(entry.id) end)
        busy = false
        button.Active = true
        if ok and type(result) == "table" and result.success == true then
            button.Active = false
            button.Text = entry.label .. " (owned)"
            status.Text = "Purchased " .. entry.id .. "; Coins: " .. tostring(result.credits)
        else
            status.Text = "Rejected: insufficient Coins, duplicate or unavailable"
        end
    end)
end
'''