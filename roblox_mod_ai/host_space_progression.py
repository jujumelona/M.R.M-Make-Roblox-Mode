"""Host-owned, shared starter progression for ships, upgrades and space entry.

These three source-owned mechanics are often split into different generated
services. A small coder cannot independently invent their state ABI. The host
owns the persistent cross-service namespaces and Remote contracts; unmatched
novel mechanics still go through normal model coding and verification.
"""
from __future__ import annotations

import json
import re

from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal

_ROLES = (
    (re.compile(r"^(?:SpaceModeActivation|EnterSpaceMode|SpaceLaunchGateAndLaunchS)", re.I), "mode"),
    (re.compile(r"^(?:SectionBySectionSpaceship|ModularSpaceshipConstruction|ModularSpaceshipPartConst)", re.I), "build"),
    (re.compile(r"^(?:SpaceshipUpgradeUnlockAnd|SpaceshipUpgradeUnlock|SpaceshipUpgradeExpansion)", re.I), "upgrade"),
)
_ROLE_DESC = {
    "mode": ("space", "mode"),
    "build": ("ship", "section"),
    "upgrade": ("ship", "upgrade"),
}
_TEMPLATES = {}  # Filled below; template selection is contract-driven.


def _role(name: str) -> str | None:
    for pattern, role in _ROLES:
        if pattern.search(name):
            return role
    return None


def render_host_space_progression(
    module: RobloxModuleSpec, proposal: RobloxProposal
) -> str | None:
    """Return source only when a COMPLETE connected progression exists."""
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    if module.kind == ModuleKind.SERVER_MODULE and not module.file_path.startswith("src/server/"):
        return None
    if module.kind == ModuleKind.CLIENT_SCRIPT and not module.file_path.startswith("src/client/"):
        return None
    server_name = (module.name if module.kind == ModuleKind.SERVER_MODULE
                   else module.name.removesuffix("Client") + "Server")
    role = _role(server_name)
    if role is None:
        return None
    modules = getattr(proposal, "modules", [])
    owners = {r: next((m for m in modules if m.kind == ModuleKind.SERVER_MODULE
                       and _role(m.name) == r), None) for r in _ROLE_DESC}
    if any(owner is None for owner in owners.values()):
        return None
    owner = owners[role]
    if owner.name != server_name:
        return None
    description = owner.description.lower()
    if role == "mode" and owner.name.startswith("SpaceLaunchGateAndLaunchS"):
        required = ("space", "launch")
    elif role == "build" and owner.name.startswith("ModularSpaceshipPartConst"):
        required = ("ship", "part")
    else:
        required = _ROLE_DESC[role]
    if not all(word in description for word in required):
        return None
    # Every step needs its exact declared host-owned ingress. The module never
    # binds remotes itself; the bootstrap resolves their Roblox classes.
    design = proposal.game_design.get("dynamic_design") or {}
    routes = {}
    for r, peer in owners.items():
        matching = [(remote, binding) for remote, binding
                    in (design.get("host_actions") or {}).items()
                    if isinstance(binding, dict) and binding.get("service") == peer.name]
        if len(matching) != 1:
            return None
        name, binding = matching[0]
        is_launch_gate = (r == "mode" and peer.name.startswith("SpaceLaunchGateAndLaunchS"))
        expected_kind = ("RemoteEvent" if r == "mode" and not is_launch_gate
                         else "RemoteFunction")
        if (binding.get("kind") != expected_kind
                or binding.get("max_args") == 0 and r != "mode"
                or design.get("remotes", {}).get(name, binding["kind"]) != binding["kind"]):
            return None
        routes[r] = name
    if role == "mode":
        if owner.name.startswith("SpaceLaunchGateAndLaunchS"):
            template = (_LAUNCH_SERVER if module.kind == ModuleKind.SERVER_MODULE
                        else _LAUNCH_CLIENT)
        else:
            template = _SPACE_SERVER if module.kind == ModuleKind.SERVER_MODULE else _SPACE_CLIENT
    elif role == "build":
        template = _BUILD_SERVER if module.kind == ModuleKind.SERVER_MODULE else _BUILD_CLIENT
    else:
        template = _UPGRADE_SERVER if module.kind == ModuleKind.SERVER_MODULE else _UPGRADE_CLIENT
    return template.replace("__REMOTE__", json.dumps(routes[role]))


_SPACE_SERVER = r'''--!strict
-- Server-only launch authorization; no client-provided progress or currency.
local Players = game:GetService("Players")
local Service = {}
local function status(player, services)
    local profile = services.PlayerDataManager.GetState(player, "RMMTravelProgress")
    local build = services.PlayerDataManager.GetState(player, "RMMShipBuild")
    if not profile or not build then return false end
    local allowed = profile.unlocked == true and build.shipReady == true
    local active = allowed and profile.inSpace == true
    player:SetAttribute("RMMSpaceUnlocked", allowed)
    player:SetAttribute("RMMInSpace", active)
    return active
end
local function orbitPlatform()
    local old = workspace:FindFirstChild("RMMOrbitPlatform")
    if old and old:IsA("BasePart") then return old end
    if old then error("Orbit platform name belongs to an unexpected instance") end
    local platform = Instance.new("Part")
    platform.Name = "RMMOrbitPlatform"
    platform.Size = Vector3.new(110, 2, 110)
    platform.Position = Vector3.new(0, 180, 0)
    platform.Anchored = true
    platform.Material = Enum.Material.Metal
    platform.Parent = workspace
    return platform
end
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Space transition requires host-owned persistent profile")
    orbitPlatform()
    services.PlayerDataManager.OnReady(function(player)
        status(player, services)
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 0 then return false end
    local profile = services.PlayerDataManager.GetState(player, "RMMTravelProgress")
    local build = services.PlayerDataManager.GetState(player, "RMMShipBuild")
    if not profile or not build or profile.unlocked ~= true or build.shipReady ~= true then
        return false
    end
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0 or not root then return false end
    if profile.inSpace == true then return false end
    local platform = orbitPlatform()
    profile.inSpace = true
    status(player, services)
    character:PivotTo(CFrame.new(platform.Position + Vector3.new(0, 6, 0)))
    return true
end
return Service
'''

_SPACE_CLIENT = r'''--!strict
-- Read-only HUD: pressing the button requests a SERVER-validated transition.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Lighting = game:GetService("Lighting")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local gui = Instance.new("ScreenGui")
gui.Name = "RMMSpaceModePanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Name = "EnterSpace"
button.Size = UDim2.fromOffset(185, 44)
button.Position = UDim2.new(1, -204, 0, 135)
button.Parent = gui
local function refresh()
    if player:GetAttribute("RMMInSpace") == true then
        button.Text = "In orbit"
        button.Active = false
        Lighting.ClockTime = 0
    elseif player:GetAttribute("RMMSpaceUnlocked") == true then
        button.Text = "Launch into space"
        button.Active = true
    else
        button.Text = "Build and upgrade ship"
        button.Active = false
    end
end
button.Activated:Connect(function()
    if player:GetAttribute("RMMSpaceUnlocked") ~= true
        or player:GetAttribute("RMMInSpace") == true then return end
    remote:FireServer()
end)
player:GetAttributeChangedSignal("RMMInSpace"):Connect(refresh)
player:GetAttributeChangedSignal("RMMSpaceUnlocked"):Connect(refresh)
refresh()
'''

_BUILD_SERVER = r'''--!strict
-- Server validates ore and build order; the client supplies only a section ID.
local Players = game:GetService("Players")
local Service = {}
local ORDER = {"Hull", "Cockpit", "Engine"}
local COSTS = {Hull = 2, Cockpit = 3, Engine = 4}
local function station(player)
    local name = "RMMShip" .. tostring(player.UserId)
    local existing = workspace:FindFirstChild(name)
    if existing then
        assert(existing:IsA("Model"), "Ship name occupied by non-Model")
        return existing
    end
    local ship = Instance.new("Model")
    ship.Name = name
    ship.Parent = workspace
    return ship
end
local function showSection(player, section)
    local ship = station(player)
    if ship:FindFirstChild(section) then return end
    local index = table.find(ORDER, section)
    if not index then return end
    local modelPart = Instance.new("Part")
    modelPart.Name = section
    modelPart.Anchored = true
    modelPart.Size = (section == "Hull" and Vector3.new(12, 2, 22)
        or section == "Cockpit" and Vector3.new(6, 4, 6)
        or Vector3.new(6, 4, 5))
    local offset = Vector3.new(24 + (player.UserId % 8) * 20, 7, 55)
    modelPart.Position = offset + Vector3.new(0, index * 3, (index - 2) * 6)
    modelPart.Parent = ship
end
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Ship build requires a live persistent host profile")
    services.PlayerDataManager.OnReady(function(player)
        local state = services.PlayerDataManager.GetState(player, "RMMShipBuild")
        if not state or type(state.sections) ~= "table" then return end
        for _, section in ORDER do
            if state.sections[section] == true then showSection(player, section) end
        end
    end)
    Players.PlayerRemoving:Connect(function(player)
        local model = workspace:FindFirstChild("RMMShip" .. tostring(player.UserId))
        if model and model:IsA("Model") then model:Destroy() end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then return false end
    local requested = ...
    if type(requested) ~= "string" or not table.find(ORDER, requested) then return false end
    local build = services.PlayerDataManager.GetState(player, "RMMShipBuild")
    local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not build or not inventory then return false end
    if type(build.sections) ~= "table" then build.sections = {} end
    if build.sections[requested] == true then return false end
    local index = table.find(ORDER, requested)
    if index > 1 and build.sections[ORDER[index - 1]] ~= true then return false end
    local ore = inventory.resources
    if type(ore) ~= "number" or ore ~= ore or ore % 1 ~= 0
        or ore < COSTS[requested] then return false end
    -- No yields between balance validation and committed build.
    inventory.resources -= COSTS[requested]
    build.sections[requested] = true
    build.shipReady = build.sections.Engine == true
    showSection(player, requested)
    return {success = true, section = requested, ore = inventory.resources,
        shipReady = build.shipReady}
end
return Service
'''

_BUILD_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipConstruction"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local status = Instance.new("TextLabel")
status.Size = UDim2.fromOffset(320, 38)
status.Position = UDim2.new(0, 15, 0, 170)
status.Text = "Mine ore, then build hull, cockpit, engine"
status.Parent = gui
local busy = false
for index, section in {"Hull", "Cockpit", "Engine"} do
    local button = Instance.new("TextButton")
    button.Name = section
    button.Size = UDim2.fromOffset(125, 40)
    button.Position = UDim2.new(0, 15 + (index - 1) * 130, 0, 213)
    button.Text = "Build " .. section
    button.Parent = gui
    button.Activated:Connect(function()
        if busy then return end
        busy = true
        local ok, result = pcall(function() return remote:InvokeServer(section) end)
        busy = false
        if ok and type(result) == "table" and result.success then
            status.Text = result.section .. " built. Ore left: " .. tostring(result.ore)
        else status.Text = "Build rejected: gather ore or build in order" end
    end)
end
'''

_UPGRADE_SERVER = r'''--!strict
-- Shared ship-to-space progression; clients cannot choose price, tier or unlock.
local Players = game:GetService("Players")
local Service = {}
local MAX_TIER = 3
local function publish(player, progress)
    player:SetAttribute("RMMShipTier", progress.tier or 0)
    player:SetAttribute("RMMSpaceUnlocked", progress.unlocked == true)
end
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Ship upgrades require an authoritative host profile")
    services.PlayerDataManager.OnReady(function(player)
        local progress = services.PlayerDataManager.GetState(player, "RMMTravelProgress")
        if progress then publish(player, progress) end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then return false end
    local action = ...
    if action ~= "upgrade" then return false end
    local progress = services.PlayerDataManager.GetState(player, "RMMTravelProgress")
    local build = services.PlayerDataManager.GetState(player, "RMMShipBuild")
    local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not progress or not build or not inventory or build.shipReady ~= true then return false end
    local tier = progress.tier or 0
    if type(tier) ~= "number" or tier ~= tier or tier % 1 ~= 0
        or tier < 0 or tier >= MAX_TIER then return false end
    local oreCost = 2 + tier
    local coinCost = (tier + 1) * 6
    local ore = inventory.resources
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if type(ore) ~= "number" or ore ~= ore or ore % 1 ~= 0
        or ore < oreCost or not coins or not coins:IsA("IntValue")
        or coins.Value < coinCost then return false end
    -- All mutable values are server-authoritative and validated before writes.
    inventory.resources -= oreCost
    coins.Value -= coinCost
    progress.tier = tier + 1
    progress.unlocked = progress.tier >= MAX_TIER
    publish(player, progress)
    return {success = true, tier = progress.tier, unlocked = progress.unlocked,
        coins = coins.Value, ore = inventory.resources}
end
return Service
'''

_UPGRADE_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipTravelUpgrades"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Name = "UpgradeShip"
button.Size = UDim2.fromOffset(225, 45)
button.Position = UDim2.new(0, 15, 0, 260)
button.Parent = gui
local status = Instance.new("TextLabel")
status.Size = UDim2.fromOffset(320, 35)
status.Position = UDim2.new(0, 15, 0, 309)
status.Text = "Build ship, mine ore, earn credits"
status.Parent = gui
local function refresh()
    button.Text = "Upgrade ship tier " .. tostring(player:GetAttribute("RMMShipTier") or 0)
    button.Active = player:GetAttribute("RMMSpaceUnlocked") ~= true
end
local busy = false
button.Activated:Connect(function()
    if busy or player:GetAttribute("RMMSpaceUnlocked") == true then return end
    busy = true
    local ok, result = pcall(function() return remote:InvokeServer("upgrade") end)
    busy = false
    if ok and type(result) == "table" and result.success then
        status.Text = "Tier " .. tostring(result.tier) .. " | Coins " .. tostring(result.coins)
    else status.Text = "Upgrade rejected: build ship or earn resources" end
    refresh()
end)
player:GetAttributeChangedSignal("RMMShipTier"):Connect(refresh)
player:GetAttributeChangedSignal("RMMSpaceUnlocked"):Connect(refresh)
refresh()
'''

# Alternative source-owned launch gate variant: a RemoteFunction requests a
# server-measured transition while standing near a physical gate. This is not
# the zero-arg RemoteEvent used by passive SpaceModeActivation.
_LAUNCH_SERVER = _SPACE_SERVER.replace(
    'function Service.start(services)',
    '''local function launchGate()
    local gate = workspace:FindFirstChild("RMMLaunchGate")
    if gate ~= nil then
        assert(gate:IsA("BasePart"), "Launch gate name belongs to non-Part")
        return gate
    end
    gate = Instance.new("Part")
    gate.Name = "RMMLaunchGate"
    gate.Size = Vector3.new(12, 18, 3)
    gate.Position = Vector3.new(0, 9, 38)
    gate.Anchored = true
    gate.Material = Enum.Material.Neon
    gate.Color = Color3.fromRGB(67, 143, 210)
    gate.Parent = workspace
    return gate
end
function Service.start(services)'''
).replace(
    '''    orbitPlatform()
    services.PlayerDataManager.OnReady''',
    '''    orbitPlatform()
    launchGate()
    services.PlayerDataManager.OnReady'''
).replace(
    '''    if profile.inSpace == true then return false end
    local platform = orbitPlatform()''',
    '''    if profile.inSpace == true then return false end
    local gate = launchGate()
    if (root.Position - gate.Position).Magnitude > 50 then return false end
    local platform = orbitPlatform()'''
)
assert (_LAUNCH_SERVER.count("function Service.handleAction(") == 1
        and _LAUNCH_SERVER != _SPACE_SERVER), "Launch gate ABI changed"

_LAUNCH_CLIENT = _SPACE_CLIENT.replace(
    "    remote:FireServer()",
    '''    local ok, result = pcall(function()
        return remote:InvokeServer()
    end)
    if not ok or result ~= true then refresh() end'''
)
assert _LAUNCH_CLIENT != _SPACE_CLIENT, "Launch client ABI changed"
