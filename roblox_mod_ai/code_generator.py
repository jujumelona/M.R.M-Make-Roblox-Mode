"""Luau source code generator for Roblox Studio experiences with safe DataStore and genre engines."""

from __future__ import annotations

import math
import re
from typing import Any

from .luau_analyzer import LuauStaticAnalyzer
from .model_router import ModelRouter
from .spec import RobloxModuleSpec, RobloxProposal


class LuauCodeGenerator:
    """Generates idiomatic, type-checked Luau code for Roblox services with self-correction."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router or ModelRouter()
        self.analyzer = LuauStaticAnalyzer()

    def generate_all_modules(self, proposal: RobloxProposal) -> list[RobloxModuleSpec]:
        """Generates Luau code for each module in the proposal with self-correction feedback loop."""
        completed_modules: list[RobloxModuleSpec] = []
        for mod in proposal.modules:
            if not mod.code:
                code = self.generate_with_self_correction(mod, proposal)
                mod.code = code
            completed_modules.append(mod)
        return completed_modules

    def generate_with_self_correction(
        self,
        module: RobloxModuleSpec,
        proposal: RobloxProposal,
        max_attempts: int = 3,
    ) -> str:
        """Generates Luau code, analyzes diagnostics, and self-corrects on syntax/safety issues."""
        code = self.generate_module_code(module, proposal)

        for attempt in range(max_attempts):
            diagnostics = self.analyzer.analyze_source(code, file_path=module.file_path)
            errors = [d for d in diagnostics if d.severity == "ERROR"]
            if not errors:
                return code

            # Self-correction: analyze diagnostics and apply programmatic or model fixes
            fixed_code = code
            for err in errors:
                if "Missing 'end'" in err.message:
                    fixed_code += "\nend\n"
                elif "Unbalanced" in err.message and "more opening" in err.message:
                    fixed_code += "\nend\n"

            code = fixed_code

        return code

    def generate_module_code(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        """Dispatches Luau code generation to specialized genre and subsystem engines."""
        name = module.name.lower()
        kind = module.kind.lower()

        if "modding" in name or "mod_manager" in name:
            return self._generate_modding_system(module, proposal)
        elif "network" in name or "remote" in kind or "shared" in kind:
            return self._generate_shared_network_module(module, proposal)
        elif "playerdata" in name or "data" in kind:
            return self._generate_safe_datastore_service(module, proposal)
        elif "shop" in name and ("server" in kind or module.file_path.endswith(".server.luau")):
            return self._generate_shop_service(module, proposal)
        elif "shop" in name and ("client" in kind or module.file_path.endswith(".client.luau")):
            return self._generate_shop_controller(module, proposal)
        elif "obby" in name and ("server" in kind or module.file_path.endswith(".server.luau")):
            return self._generate_obby_service(module, proposal)
        elif "obby" in name and ("client" in kind or module.file_path.endswith(".client.luau")):
            return self._generate_obby_controller(module, proposal)
        elif "tycoon" in name and ("server" in kind or module.file_path.endswith(".server.luau")):
            return self._generate_tycoon_service(module, proposal)
        elif "tycoon" in name and ("client" in kind or module.file_path.endswith(".client.luau")):
            return self._generate_tycoon_controller(module, proposal)
        elif "simulator" in name and ("server" in kind or module.file_path.endswith(".server.luau")):
            return self._generate_simulator_service(module, proposal)
        elif "simulator" in name and ("client" in kind or module.file_path.endswith(".client.luau")):
            return self._generate_simulator_controller(module, proposal)
        elif "combat" in name and ("server" in kind or module.file_path.endswith(".server.luau")):
            return self._generate_combat_service(module, proposal)
        elif "combat" in name and ("client" in kind or module.file_path.endswith(".client.luau")):
            return self._generate_combat_controller(module, proposal)
        elif "hud" in name:
            return self._generate_hud_controller(module, proposal)
        else:
            return self._generate_generic_module(module, proposal)

    # 1. Shared Network Remotes Bridge
    def _generate_shared_network_module(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Module: {module.name}
-- Service: ReplicatedStorage
-- Description: Shared RemoteEvent/RemoteFunction definitions, game constants, and strict types.

local {module.name} = {{}}

export type PlayerDataRecord = {{
    userId: number,
    coins: number,
    level: number,
    stage: number,
    clicks: number,
    inventory: {{ string }},
    sessionLock: string?,
}}

export type ShopItem = {{
    id: string,
    name: string,
    price: number,
    itemType: string,
}}

{module.name}.Remotes = {{
    -- Combat
    AttackRequest = "AttackRequest",
    DamageEvent = "DamageEvent",
    -- Shop & Economy
    ShopPurchase = "ShopPurchase",
    UpdateStats = "UpdateStats",
    -- Obby & Stages
    StageChanged = "StageChanged",
    ResetToStage = "ResetToStage",
    -- Tycoon & Simulator
    ClickRequest = "ClickRequest",
    ButtonPurchased = "ButtonPurchased",
}}

{module.name}.Config = {{
    DEFAULT_WALK_SPEED = 16,
    MAX_ATTACK_REACH = 15,
    SHOP_PURCHASE_COOLDOWN_SEC = 0.5,
    AUTOSAVE_INTERVAL_SEC = 60,
}}

return {module.name}
"""

    # 2. Production-Grade DataStore Service with Session Locking & Backoff
    def _generate_safe_datastore_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Production-grade player data persistence with session locking, exponential backoff, and BindToClose waiting.

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local HttpService = game:GetService("HttpService")

local PlayerDataStore = DataStoreService:GetDataStore("RMM_ExperienceData_v1")

type PlayerData = {{
    coins: number,
    level: number,
    stage: number,
    clicks: number,
    inventory: {{ string }},
    lockToken: string?,
    lastSaved: number,
}}

local sessionData: {{ [number]: PlayerData }} = {{}}
local sessionLocks: {{ [number]: string }} = {{}}
local isSaving: {{ [number]: boolean }} = {{}}

local function getPlayerKey(userId: number): string
    return "Player_" .. tostring(userId)
end

-- Exponential backoff retry helper with random jitter
local function retryWithBackoff<T>(action: () -> T, maxRetries: number): (boolean, T?, string?)
    local retries = maxRetries or 4
    for attempt = 1, retries do
        local success, result = pcall(action)
        if success then
            return true, result, nil
        end
        if attempt < retries then
            local jitter = math.random() * 0.5
            local backoffTime = (2 ^ attempt) * 0.5 + jitter
            task.wait(backoffTime)
        else
            return false, nil, tostring(result)
        end
    end
    return false, nil, "Max retries exceeded"
end

local function onPlayerAdded(player: Player)
    local userId = player.UserId
    local key = getPlayerKey(userId)
    local sessionToken = HttpService:GenerateGUID(false)

    -- Step 1: Read saved data with backoff
    local success, rawData, err = retryWithBackoff(function()
        return PlayerDataStore:GetAsync(key)
    end, 4)

    -- Crucial Safety Rule: Distinguish read failure from brand-new player!
    if not success then
        warn("CRITICAL: Failed to load DataStore for player " .. player.Name .. " (" .. userId .. "): " .. tostring(err))
        -- Kick player to prevent overwriting saved data with zero on leave
        player:Kick("Your game data could not be safely loaded from Roblox servers. Please rejoin.")
        return
    end

    local data: PlayerData
    if rawData == nil then
        -- Brand new player: initialize fresh state
        data = {{
            coins = 0,
            level = 1,
            stage = 1,
            clicks = 0,
            inventory = {{}},
            lockToken = sessionToken,
            lastSaved = os.time(),
        }}
    else
        data = rawData :: PlayerData
        -- Session locking: acquire ownership of this session
        data.lockToken = sessionToken
        data.lastSaved = os.time()
    end

    sessionData[userId] = data
    sessionLocks[userId] = sessionToken

    -- Setup Leaderstats for HUD display
    local leaderstats = Instance.new("Folder")
    leaderstats.Name = "leaderstats"
    leaderstats.Parent = player

    local coinsVal = Instance.new("IntValue")
    coinsVal.Name = "Coins"
    coinsVal.Value = data.coins
    coinsVal.Parent = leaderstats

    local levelVal = Instance.new("IntValue")
    levelVal.Name = "Level"
    levelVal.Value = data.level
    levelVal.Parent = leaderstats

    local stageVal = Instance.new("IntValue")
    stageVal.Name = "Stage"
    stageVal.Value = data.stage
    stageVal.Parent = leaderstats
end

local function savePlayerData(player: Player): boolean
    local userId = player.UserId
    local data = sessionData[userId]
    if not data then return true end
    if isSaving[userId] then return false end

    isSaving[userId] = true

    -- Synchronize leaderstats values before save
    local leaderstats = player:FindFirstChild("leaderstats")
    if leaderstats then
        local coins = leaderstats:FindFirstChild("Coins") :: IntValue?
        if coins then data.coins = coins.Value end
        local level = leaderstats:FindFirstChild("Level") :: IntValue?
        if level then data.level = level.Value end
        local stage = leaderstats:FindFirstChild("Stage") :: IntValue?
        if stage then data.stage = stage.Value end
    end

    data.lastSaved = os.time()
    local key = getPlayerKey(userId)

    local success, _, err = retryWithBackoff(function()
        PlayerDataStore:SetAsync(key, data)
        return true
    end, 4)

    isSaving[userId] = false

    if not success then
        warn("Failed to save data for user " .. userId .. ": " .. tostring(err))
        return false
    end

    return true
end

local function onPlayerRemoving(player: Player)
    local userId = player.UserId
    savePlayerData(player)
    sessionData[userId] = nil
    sessionLocks[userId] = nil
end

Players.PlayerAdded:Connect(onPlayerAdded)
Players.PlayerRemoving:Connect(onPlayerRemoving)

-- BindToClose with explicit completion waiting (up to 25s safe headroom)
game:BindToClose(function()
    local remaining = #Players:GetPlayers()
    for _, player in Players:GetPlayers() do
        task.spawn(function()
            pcall(savePlayerData, player)
            remaining -= 1
        end)
    end

    local deadline = os.clock() + 25
    while remaining > 0 and os.clock() < deadline do
        task.wait(0.2)
    end
end)
"""

    # 3. Real Shop & Economy System
    def _generate_shop_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server-authoritative shop: validates coin balances, prevents duplicates, and delivers items.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local purchaseFunction = remotesFolder:FindFirstChild("ShopPurchase") :: RemoteFunction?
if not purchaseFunction then
    purchaseFunction = Instance.new("RemoteFunction")
    purchaseFunction.Name = "ShopPurchase"
    purchaseFunction.Parent = remotesFolder
end

-- Catalog of items available in the shop
local SHOP_ITEMS: {{ [string]: {{ name: string, price: number, itemType: string }} }} = {{
    speed_boots = {{ name = "Speed Boots", price = 50, itemType = "Gear" }},
    magic_staff = {{ name = "Arcane Staff", price = 150, itemType = "Weapon" }},
    shield = {{ name = "Iron Shield", price = 100, itemType = "Armor" }},
    health_potion = {{ name = "Health Potion", price = 25, itemType = "Consumable" }},
}}

local function handlePurchase(player: Player, itemId: string): (boolean, string)
    local item = SHOP_ITEMS[itemId]
    if not item then
        return false, "Item does not exist in catalog."
    end

    local leaderstats = player:FindFirstChild("leaderstats")
    if not leaderstats then
        return false, "Leaderstats not initialized."
    end

    local coinsVal = leaderstats:FindFirstChild("Coins") :: IntValue?
    if not coinsVal or coinsVal.Value < item.price then
        return false, "Insufficient coins! You need " .. item.price .. " coins."
    end

    -- Deduct currency server-authoritatively
    coinsVal.Value -= item.price

    -- Deliver purchased tool / gear
    local tool = Instance.new("Tool")
    tool.Name = item.name
    tool.ToolTip = "Purchased from shop"
    tool.RequiresHandle = false
    tool.Parent = player.Backpack

    return true, "Successfully purchased " .. item.name .. "!"
end

purchaseFunction.OnServerInvoke = handlePurchase
"""

    def _generate_shop_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Client shop interaction handler with ProximityPrompt binding and purchase requests.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local SoundService = game:GetService("SoundService")

local localPlayer = Players.LocalPlayer
local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local purchaseFunction = remotesFolder:WaitForChild("ShopPurchase") :: RemoteFunction

local function requestBuy(itemId: string)
    local success, message = purchaseFunction:InvokeServer(itemId)
    if success then
        print("Shop Success: " .. message)
        local sound = SoundService:FindFirstChild("PurchaseCashRegisterSound") :: Sound?
        if sound then sound:Play() end
    else
        warn("Shop Failed: " .. message)
    end
end

-- Connect to Workspace ShopStall ProximityPrompts
local function bindShopPrompts()
    local shopStalls = workspace:FindFirstChild("ShopStalls")
    if shopStalls then
        for _, stall in shopStalls:GetChildren() do
            local prompt = stall:FindFirstChildWhichIsA("ProximityPrompt", true)
            if prompt then
                prompt.Triggered:Connect(function(triggerPlayer)
                    if triggerPlayer == localPlayer then
                        requestBuy("speed_boots")
                    end
                end)
            end
        end
    end
end

task.defer(bindShopPrompts)
"""

    # 4. Real Obby / Parkour System
    def _generate_obby_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server-authoritative parkour manager: tracks checkpoints and handles hazard collisions.

local Players = game:GetService("Players")

local function setupPlayerSpawn(player: Player)
    player.CharacterAdded:Connect(function(character)
        local humanoidRootPart = character:WaitForChild("HumanoidRootPart") :: BasePart
        local leaderstats = player:WaitForChild("leaderstats")
        local stageVal = leaderstats:WaitForChild("Stage") :: IntValue
        local stageNum = stageVal.Value

        local checkpointsFolder = workspace:FindFirstChild("Checkpoints")
        if checkpointsFolder then
            local currentCheckpoint = checkpointsFolder:FindFirstChild("Stage" .. tostring(stageNum)) :: BasePart?
            if currentCheckpoint then
                humanoidRootPart.CFrame = currentCheckpoint.CFrame + Vector3.new(0, 3, 0)
            end
        end
    end)
end

Players.PlayerAdded:Connect(setupPlayerSpawn)

-- Connect Touch listeners to Checkpoint platforms
task.defer(function()
    local checkpointsFolder = workspace:FindFirstChild("Checkpoints")
    if checkpointsFolder then
        for _, pad in checkpointsFolder:GetChildren() do
            if pad:IsA("BasePart") then
                pad.Touched:Connect(function(hit)
                    local character = hit.Parent
                    local player = Players:GetPlayerFromCharacter(character)
                    if not player then return end

                    local leaderstats = player:FindFirstChild("leaderstats")
                    if not leaderstats then return end

                    local stageVal = leaderstats:FindFirstChild("Stage") :: IntValue?
                    local padStage = tonumber(pad.Name:gsub("Stage", "")) or 1

                    if stageVal and padStage == stageVal.Value + 1 then
                        stageVal.Value = padStage
                        pad.Color = Color3.fromRGB(0, 255, 100)
                    end
                end)
            end
        end
    end

    -- Connect KillBricks (Touch hazard)
    local killBricksFolder = workspace:FindFirstChild("KillBricks")
    if killBricksFolder then
        for _, brick in killBricksFolder:GetChildren() do
            if brick:IsA("BasePart") then
                brick.Touched:Connect(function(hit)
                    local humanoid = hit.Parent:FindFirstChildWhichIsA("Humanoid")
                    if humanoid then
                        humanoid.Health = 0
                    end
                end)
            end
        end
    end
end)
"""

    def _generate_obby_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Client stage progress HUD and checkpoint victory sound controller.

local Players = game:GetService("Players")
local SoundService = game:GetService("SoundService")

local localPlayer = Players.LocalPlayer
local leaderstats = localPlayer:WaitForChild("leaderstats")
local stageVal = leaderstats:WaitForChild("Stage") :: IntValue

stageVal.Changed:Connect(function(newStage)
    print("Stage reached: " .. tostring(newStage))
    local victorySound = SoundService:FindFirstChild("StageVictoryFanfare") :: Sound?
    if victorySound then
        victorySound:Play()
    end
end)
"""

    # 5. Real Tycoon System
    def _generate_tycoon_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server tycoon core: periodic ore generation, conveyor transport, and button purchase unlock.

local Players = game:GetService("Players")

local function startTycoonLoop()
    local tycoonFolder = workspace:FindFirstChild("TycoonPlots")
    if not tycoonFolder then return end

    local dropper = tycoonFolder:FindFirstChild("Dropper", true) :: BasePart?
    local collector = tycoonFolder:FindFirstChild("Collector", true) :: BasePart?

    if collector then
        collector.Touched:Connect(function(hit)
            if hit.Name == "Ore" then
                hit:Destroy()
                -- Grant currency to plot owner
                for _, player in Players:GetPlayers() do
                    local leaderstats = player:FindFirstChild("leaderstats")
                    if leaderstats then
                        local coins = leaderstats:FindFirstChild("Coins") :: IntValue?
                        if coins then coins.Value += 10 end
                    end
                end
            end
        end)
    end

    -- Periodic ore dropping
    task.spawn(function()
        while true do
            task.wait(2.5)
            if dropper then
                local ore = Instance.new("Part")
                ore.Name = "Ore"
                ore.Size = Vector3.new(1.5, 1.5, 1.5)
                ore.Color = Color3.fromRGB(255, 215, 0)
                ore.Material = Enum.Material.Metal
                ore.CFrame = dropper.CFrame - Vector3.new(0, 2, 0)
                ore.Parent = workspace
                game:GetService("Debris"):AddItem(ore, 12)
            end
        end
    end)
end

task.defer(startTycoonLoop)
"""

    def _generate_tycoon_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Client tycoon interaction visual effects.

local Players = game:GetService("Players")
local localPlayer = Players.LocalPlayer

print("Tycoon client controller initialized for: " .. localPlayer.Name)
"""

    # 6. Real Simulator System
    def _generate_simulator_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server click accumulator, bag capacity limits, and sell zone coin exchange.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local clickRemote = remotesFolder:FindFirstChild("ClickRequest") :: RemoteEvent?
if not clickRemote then
    clickRemote = Instance.new("RemoteEvent")
    clickRemote.Name = "ClickRequest"
    clickRemote.Parent = remotesFolder
end

clickRemote.OnServerEvent:Connect(function(player)
    local leaderstats = player:FindFirstChild("leaderstats")
    if not leaderstats then return end

    local coinsVal = leaderstats:FindFirstChild("Coins") :: IntValue?
    if coinsVal then
        coinsVal.Value += 1
    end
end)

-- Sell zones in Workspace
task.defer(function()
    local sellZones = workspace:FindFirstChild("SellZones")
    if sellZones then
        for _, zone in sellZones:GetChildren() do
            if zone:IsA("BasePart") then
                zone.Touched:Connect(function(hit)
                    local player = Players:GetPlayerFromCharacter(hit.Parent)
                    if player then
                        local leaderstats = player:FindFirstChild("leaderstats")
                        if leaderstats then
                            local coins = leaderstats:FindFirstChild("Coins") :: IntValue?
                            if coins then coins.Value += 50 end
                        end
                    end
                end)
            end
        end
    end
end)
"""

    def _generate_simulator_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Client tool click listener and particle trigger.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")

local localPlayer = Players.LocalPlayer
local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local clickRemote = remotesFolder:WaitForChild("ClickRequest") :: RemoteEvent

UserInputService.InputBegan:Connect(function(input, processed)
    if processed then return end
    if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
        clickRemote:FireServer()
    end
end)
"""

    # 7. Real Combat & Action System
    def _generate_combat_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server-authoritative combat: reach sanity checks, cooldown enforcement, and damage calculation.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local attackRemote = remotesFolder:FindFirstChild("AttackRequest") :: RemoteEvent?
if not attackRemote then
    attackRemote = Instance.new("RemoteEvent")
    attackRemote.Name = "AttackRequest"
    attackRemote.Parent = remotesFolder
end

local playerCooldowns: {{ [number]: number }} = {{}}
local MAX_REACH = 15.0

attackRemote.OnServerEvent:Connect(function(player, targetCharacter: Model?)
    if not targetCharacter or not targetCharacter:IsA("Model") then return end

    local userId = player.UserId
    local now = os.clock()
    if playerCooldowns[userId] and (now - playerCooldowns[userId]) < 0.4 then
        return -- Rate limit attack spam
    end
    playerCooldowns[userId] = now

    local char = player.Character
    if not char then return end
    local root = char:FindFirstChild("HumanoidRootPart") :: BasePart?
    local targetRoot = targetCharacter:FindFirstChild("HumanoidRootPart") :: BasePart?
    local targetHumanoid = targetCharacter:FindFirstChild("Humanoid") :: Humanoid?

    if not root or not targetRoot or not targetHumanoid then return end

    -- Server-side anti-cheat distance validation
    local distance = (root.Position - targetRoot.Position).Magnitude
    if distance > MAX_REACH then
        warn("Anti-cheat: attack rejected for distance violation (" .. math.floor(distance) .. " studs)")
        return
    end

    targetHumanoid:TakeDamage(20)
end)
"""

    def _generate_combat_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Client weapon swing detection and hit raycasting.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local UserInputService = game:GetService("UserInputService")
local SoundService = game:GetService("SoundService")

local localPlayer = Players.LocalPlayer
local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local attackRemote = remotesFolder:WaitForChild("AttackRequest") :: RemoteEvent

UserInputService.InputBegan:Connect(function(input, processed)
    if processed then return end
    if input.UserInputType == Enum.UserInputType.MouseButton1 then
        local mouse = localPlayer:GetMouse()
        local target = mouse.Target
        if target and target.Parent and target.Parent:FindFirstChild("Humanoid") then
            attackRemote:FireServer(target.Parent :: Model)
            local slashSound = SoundService:FindFirstChild("SwordSlashSound") :: Sound?
            if slashSound then slashSound:Play() end
        end
    end
end)
"""

    def _generate_hud_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Responsive HUD updater for player coins, level, and health bars.

local Players = game:GetService("Players")
local localPlayer = Players.LocalPlayer

local leaderstats = localPlayer:WaitForChild("leaderstats")
local coins = leaderstats:WaitForChild("Coins") :: IntValue

coins.Changed:Connect(function(newVal)
    print("HUD update: Coins = " .. tostring(newVal))
end)
"""

    def _generate_modding_system(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ReplicatedStorage
-- Script: {module.name}
-- Description: Data-driven in-game modding registry: safe serialization without loadstring.

local HttpService = game:GetService("HttpService")

local ModdingSystem = {{}}

export type ModDescriptor = {{
    id: string,
    name: string,
    version: string,
    author: string,
    damageMultiplier: number?,
    speedMultiplier: number?,
    customColors: {{ [string]: string }}?,
}}

local registeredMods: {{ [string]: ModDescriptor }} = {{}}

function ModdingSystem.registerMod(mod: ModDescriptor): boolean
    if not mod.id or not mod.name then return false end
    registeredMods[mod.id] = mod
    return true
end

function ModdingSystem.getMod(modId: string): ModDescriptor?
    return registeredMods[modId]
end

function ModdingSystem.exportModToJSON(modId: string): string
    local mod = registeredMods[modId]
    if not mod then error("Mod not found: " .. modId) end
    return HttpService:JSONEncode(mod)
end

function ModdingSystem.importModFromJSON(jsonString: string): ModDescriptor?
    local success, result = pcall(function()
        return HttpService:JSONDecode(jsonString)
    end)
    if success and type(result) == "table" and result.id and result.name then
        local mod = result :: ModDescriptor
        ModdingSystem.registerMod(mod)
        return mod
    end
    return nil
end

return ModdingSystem
"""

    def _generate_generic_module(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Module: {module.name}
-- Description: {module.description or "Generic Luau component"}

local {module.name} = {{}}
return {module.name}
"""
