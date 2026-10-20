"""Host-owned mining: validated world target, proximity, cooldown, persistent Coins.

Only applies when an accepted authored plan defines a matching resource Part and
a matching RemoteFunction. Does not substitute for unrelated game mechanics.
"""
from __future__ import annotations

import json
import re

from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal

_NODES = re.compile(r"resource.*node|ore.*node|ore.*deposit", re.I)


def render_host_mining(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if not module.module_id.startswith("dyn_"):
        return None
    if module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT):
        return None
    description = module.description.lower()
    if (not re.search("mining", module.name, re.I)
            or "mining" not in description
            or "resource node" not in description
            or not any(token in description for token in ("currency", "coin", "credit"))):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    nodes = [row["name"] for row in design.get("world_objects", [])
             if isinstance(row, dict) and row.get("class") == "Part"
             and isinstance(row.get("name"), str) and _NODES.search(row["name"])]
    if not nodes:
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    routes = [(name, binding) for name, binding in
              (design.get("host_actions") or {}).items()
              if isinstance(binding, dict) and binding.get("service") == server]
    if (len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction"
            or routes[0][1].get("max_args") == 0):
        return None
    remote = routes[0][0]
    if module.kind == ModuleKind.SERVER_MODULE:
        return _SERVER.replace("__NODES__", json.dumps(nodes))
    if not module.file_path.startswith("src/client/"):
        return None
    return (_CLIENT.replace("__NODES__", json.dumps(nodes))
                   .replace("__REMOTE__", json.dumps(remote)))


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local NODE_NAMES = __NODES__
local NODE_INITIAL = 100
local COOLDOWN = 0.7
local MAX_RANGE = 18
local nodes = {}
local recent = setmetatable({}, {__mode = "k"})

local function validNode(part)
    if typeof(part) ~= "Instance" or not part:IsA("BasePart") then return false end
    if not part:IsDescendantOf(workspace) then return false end
    for _, name in NODE_NAMES do
        if part.Name == name then return true end
    end
    return false
end
local function getNode(part)
    if not validNode(part) then return nil end
    if nodes[part] then return nodes[part] end
    nodes[part] = {remaining = NODE_INITIAL}
    part:SetAttribute("RemainingResources", NODE_INITIAL)
    part:SetAttribute("ResourceDepleted", false)
    return nodes[part]
end
function Service.start(services)
    assert(type(services) == "table" and
        type(services.PlayerDataManager) == "table" and
        type(services.PlayerDataManager.GetState) == "function",
        "PlayerDataManager.GetState is required")
    for _, name in NODE_NAMES do
        local part = workspace:FindFirstChild(name, true)
        if part and part:IsA("BasePart") then getNode(part) end
    end
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or player.Parent ~= Players then return false end
    if select("#", ...) ~= 1 then return false end
    local part = ...
    local node = getNode(part)
    if not node or node.remaining <= 0 then return false end
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0 or not root then return false end
    if (root.Position - part.Position).Magnitude > MAX_RANGE then return false end
    local progress = services.PlayerDataManager.GetState(player, "RMMMining")
    if not progress then return false end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value > 2147483646 then return false end
    local now = os.clock()
    if recent[player] and now - recent[player] < COOLDOWN then return false end
    recent[player] = now
    node.remaining -= 1
    coins.Value += 1
    progress.resources = (type(progress.resources) == "number" and progress.resources or 0) + 1
    part:SetAttribute("RemainingResources", node.remaining)
    part:SetAttribute("ResourceDepleted", node.remaining == 0)
    return {success = true, remaining = node.remaining,
            credits = coins.Value, resources = progress.resources}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local NODE_NAMES = __NODES__
local gui = Instance.new("ScreenGui")
gui.Name = "RMMMiningPanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Name = "Mine"
button.Size = UDim2.fromOffset(175, 48)
button.Position = UDim2.new(0, 16, 1, -112)
button.Text = "Mine nearby node"
button.Parent = gui
local status = Instance.new("TextLabel")
status.Name = "MiningResult"
status.Size = UDim2.fromOffset(320, 35)
status.Position = UDim2.new(0, 16, 1, -64)
status.Text = "Approach a resource node"
status.Parent = gui
local busy = false
button.Activated:Connect(function()
    if busy then return end
    local root = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
    if not root then return end
    local target = nil
    local best = 18
    for _, name in NODE_NAMES do
        local node = workspace:FindFirstChild(name, true)
        if node and node:IsA("BasePart") then
            local distance = (node.Position - root.Position).Magnitude
            if distance <= best then target = node; best = distance end
        end
    end
    if not target then status.Text = "No nearby node"; return end
    busy = true
    local ok, result = pcall(function() return remote:InvokeServer(target) end)
    busy = false
    if ok and type(result) == "table" and result.success == true then
        status.Text = "Coins: " .. tostring(result.credits) ..
            " | Ore: " .. tostring(result.resources) ..
            " | Remaining: " .. tostring(result.remaining)
    else
        status.Text = "Mining rejected: range, cooldown, depleted, or loading"
    end
end)
'''