"""Luau source code generator for Roblox Studio experiences."""

from __future__ import annotations

import re
from typing import Any

from .model_router import ModelRouter
from .spec import RobloxModuleSpec, RobloxProposal


class LuauCodeGenerator:
    """Generates idiomatic, type-checked Luau code for Roblox services."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router or ModelRouter()

    def generate_all_modules(self, proposal: RobloxProposal) -> list[RobloxModuleSpec]:
        """Generates Luau code for each module in the proposal."""
        completed_modules: list[RobloxModuleSpec] = []
        for mod in proposal.modules:
            if not mod.code:
                code = self.generate_module_code(mod, proposal)
                mod.code = code
            completed_modules.append(mod)
        return completed_modules

    def generate_module_code(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        """Generates Luau code based on module kind, role, and proposal context."""
        kind = module.kind.lower()
        if "modding" in module.name.lower() or "mod_manager" in module.name.lower():
            return self._generate_modding_system(module, proposal)
        elif "remote" in kind or "bridge" in kind or "shared" in kind:
            return self._generate_shared_module(module, proposal)
        elif "server" in kind or "datastore" in kind or module.file_path.endswith(".server.luau"):
            return self._generate_server_script(module, proposal)
        elif "client" in kind or "gui" in kind or module.file_path.endswith(".client.luau"):
            return self._generate_client_script(module, proposal)
        else:
            return self._generate_generic_module(module, proposal)

    def _generate_shared_module(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Module: {module.name}
-- Service: {module.roblox_service}
-- Description: {module.description or "Shared network bridge and definitions"}

local {module.name} = {{}}

export type GameState = {{
    title: string,
    version: string,
    maxPlayers: number,
}}

export type PlayerData = {{
    userId: number,
    coins: number,
    level: number,
    experience: number,
    inventory: {{ string }},
}}

-- Global network channel names
{module.name}.Remotes = {{
    AttackRequest = "AttackRequest",
    DamageEvent = "DamageEvent",
    ShopPurchase = "ShopPurchase",
    UpdateStats = "UpdateStats",
    PlayEffect = "PlayEffect",
}}

-- Configuration constants
{module.name}.Config = {{
    BASE_COIN_DROP = 10,
    RESPAWN_DELAY_SEC = 5,
    MAX_LEVEL = 100,
    SAVE_INTERVAL_SEC = 60,
}}

return {module.name}
"""

    def _generate_server_script(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        is_datastore = "data" in module.name.lower() or "store" in module.name.lower()
        if is_datastore:
            return f"""--!strict
-- Script: {module.name}
-- Service: ServerScriptService
-- Description: Server-authoritative player data persistence with pcall safety

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local PlayerDataStore = DataStoreService:GetDataStore("RMM_PlayerData_v1")

local sessionData: {{ [number]: {{ coins: number, level: number, kills: number }} }} = {{}}

local function loadPlayerData(player: Player)
    local userId = player.UserId
    local key = "Player_" .. tostring(userId)

    local success, savedData = pcall(function()
        return PlayerDataStore:GetAsync(key)
    end)

    if success and savedData then
        sessionData[userId] = savedData
    else
        sessionData[userId] = {{ coins = 0, level = 1, kills = 0 }}
    end

    -- Setup leaderstats
    local leaderstats = Instance.new("Folder")
    leaderstats.Name = "leaderstats"
    leaderstats.Parent = player

    local coins = Instance.new("IntValue")
    coins.Name = "Coins"
    coins.Value = sessionData[userId].coins
    coins.Parent = leaderstats

    local level = Instance.new("IntValue")
    level.Name = "Level"
    level.Value = sessionData[userId].level
    level.Parent = leaderstats
end

local function savePlayerData(player: Player)
    local userId = player.UserId
    local data = sessionData[userId]
    if not data then return end

    local leaderstats = player:FindFirstChild("leaderstats")
    if leaderstats then
        local coins = leaderstats:FindFirstChild("Coins") :: IntValue?
        if coins then data.coins = coins.Value end
    end

    local key = "Player_" .. tostring(userId)
    local retries = 3
    while retries > 0 do
        local success, err = pcall(function()
            PlayerDataStore:SetAsync(key, data)
        end)
        if success then
            break
        else
            warn("Failed to save data for user " .. userId .. ", retrying: " .. tostring(err))
            task.wait(1)
            retries -= 1
        end
    end
    sessionData[userId] = nil
end

Players.PlayerAdded:Connect(loadPlayerData)
Players.PlayerRemoving:Connect(savePlayerData)

game:BindToClose(function()
    for _, player in Players:GetPlayers() do
        task.spawn(savePlayerData, player)
    end
end)
"""

        # General gameplay server script
        return f"""--!strict
-- Script: {module.name}
-- Service: ServerScriptService
-- Description: {module.description or "Core gameplay logic and server-authoritative validation"}

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Debris = game:GetService("Debris")

-- Ensure remotes exist in ReplicatedStorage
local remotesFolder = ReplicatedStorage:FindFirstChild("Remotes")
if not remotesFolder then
    remotesFolder = Instance.new("Folder")
    remotesFolder.Name = "Remotes"
    remotesFolder.Parent = ReplicatedStorage
end

local function getOrCreateRemote(name: string): RemoteEvent
    local existing = remotesFolder:FindFirstChild(name) :: RemoteEvent?
    if not existing then
        existing = Instance.new("RemoteEvent")
        existing.Name = name
        existing.Parent = remotesFolder
    end
    return existing
end

local attackRemote = getOrCreateRemote("AttackRequest")
local damageRemote = getOrCreateRemote("DamageEvent")

-- Cooldown tracker for anti-cheat
local playerCooldowns: {{ [number]: number }} = {{}}
local COOLDOWN_TIME = 0.5

attackRemote.OnServerEvent:Connect(function(player: Player, targetPart: Instance?)
    local now = os.clock()
    local lastAttack = playerCooldowns[player.UserId] or 0
    if now - lastAttack < COOLDOWN_TIME then
        return -- Cooldown rate limit
    end
    playerCooldowns[player.UserId] = now

    local character = player.Character
    if not character then return end
    local humanoid = character:FindFirstChildOfClass("Humanoid")
    if not humanoid or humanoid.Health <= 0 then return end

    if targetPart and targetPart:IsA("BasePart") then
        local targetModel = targetPart:FindFirstAncestorOfClass("Model")
        if targetModel and targetModel ~= character then
            local targetHumanoid = targetModel:FindFirstChildOfClass("Humanoid")
            if targetHumanoid and targetHumanoid.Health > 0 then
                -- Verify distance (sanity check)
                local hrp = character:FindFirstChild("HumanoidRootPart") :: BasePart?
                local targetHrp = targetModel:FindFirstChild("HumanoidRootPart") :: BasePart?
                if hrp and targetHrp and (hrp.Position - targetHrp.Position).Magnitude <= 15 then
                    targetHumanoid:TakeDamage(25)
                    damageRemote:FireAllClients(targetHrp.Position)

                    -- Award coins if knockout
                    if targetHumanoid.Health <= 0 then
                        local leaderstats = player:FindFirstChild("leaderstats")
                        if leaderstats then
                            local coins = leaderstats:FindFirstChild("Coins") :: IntValue?
                            if coins then
                                coins.Value += 50
                            end
                        end
                    end
                end
            end
        end
    end
end)
"""

    def _generate_client_script(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- LocalScript: {module.name}
-- Service: StarterPlayer.StarterPlayerScripts
-- Description: {module.description or "Client input controller and visual effects"}

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local TweenService = game:GetService("TweenService")
local SoundService = game:GetService("SoundService")

local player = Players.LocalPlayer
local mouse = player:GetMouse()

local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local attackRemote = remotesFolder:WaitForChild("AttackRequest") :: RemoteEvent
local damageRemote = remotesFolder:WaitForChild("DamageEvent") :: RemoteEvent

-- Input binding for attack
UserInputService.InputBegan:Connect(function(input, gameProcessed)
    if gameProcessed then return end

    if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
        local target = mouse.Target
        attackRemote:FireServer(target)
    end
end)

-- Visual damage effect on client
damageRemote.OnClientEvent:Connect(function(position: Vector3)
    local effectPart = Instance.new("Part")
    effectPart.Shape = Enum.PartType.Ball
    effectPart.Size = Vector3.new(1, 1, 1)
    effectPart.Material = Enum.Material.Neon
    effectPart.Color = Color3.fromRGB(255, 80, 80)
    effectPart.Anchored = true
    effectPart.CanCollide = false
    effectPart.Position = position
    effectPart.Parent = workspace

    local tweenInfo = TweenInfo.new(0.4, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
    local tween = TweenService:Create(effectPart, tweenInfo, {{
        Size = Vector3.new(3, 3, 3),
        Transparency = 1,
    }})
    tween:Play()
    tween.Completed:Connect(function()
        effectPart:Destroy()
    end)
end)
"""

    def _generate_modding_system(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Module: {module.name}
-- Service: ReplicatedStorage
-- Description: Safe Data-Driven In-Game Modding System without loadstring

local HttpService = game:GetService("HttpService")

local {module.name} = {{}}

export type ModItemConfig = {{
    id: string,
    name: string,
    category: "Weapon" | "Armor" | "Consumable",
    damageMultiplier: number?,
    speedMultiplier: number?,
    assetId: string?,
}}

export type ModDefinition = {{
    modId: string,
    title: string,
    author: string,
    version: string,
    description: string,
    items: {{ ModItemConfig }},
    customRules: {{ [string]: number | boolean }},
}}

local registeredMods: {{ [string]: ModDefinition }} = {{}}

-- Register a verified data-driven mod
function {module.name}.registerMod(mod: ModDefinition): (boolean, string)
    if not mod.modId or mod.modId == "" then
        return false, "Invalid modId"
    end

    -- Sanitize values to prevent extreme exploit numbers
    for _, item in mod.items do
        if item.damageMultiplier and item.damageMultiplier > 5.0 then
            item.damageMultiplier = 5.0 -- Clamp max damage
        end
        if item.speedMultiplier and item.speedMultiplier > 2.0 then
            item.speedMultiplier = 2.0 -- Clamp max speed
        end
    end

    registeredMods[mod.modId] = mod
    print(string.format("[ModdingSystem] Registered mod '%s' v%s by %s", mod.title, mod.version, mod.author))
    return true, "Success"
end

function {module.name}.getMod(modId: string): ModDefinition?
    return registeredMods[modId]
end

function {module.name}.getAllMods(): {{ ModDefinition }}
    local list = {{}}
    for _, mod in registeredMods do
        table.insert(list, mod)
    end
    return list
end

-- Export mod to shareable JSON string
function {module.name}.exportModToJSON(modId: string): string?
    local mod = registeredMods[modId]
    if not mod then return nil end
    return HttpService:JSONEncode(mod)
end

-- Import community mod from JSON string safely
function {module.name}.importModFromJSON(jsonString: string): (boolean, string)
    local success, decoded = pcall(function()
        return HttpService:JSONDecode(jsonString)
    end)
    if not success or type(decoded) ~= "table" then
        return false, "Malformed JSON mod data"
    end
    return {module.name}.registerMod(decoded :: ModDefinition)
end

return {module.name}
"""

    def _generate_generic_module(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Module: {module.name}
-- Service: {module.roblox_service}
-- Description: {module.description}

local {module.name} = {{}}

function {module.name}.init()
    print("[{module.name}] Initialized")
end

return {module.name}
"""
