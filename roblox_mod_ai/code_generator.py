"""Luau source code generator for Roblox Studio experiences with safe DataStore and genre engines."""

from __future__ import annotations

import math
import re
from typing import Any

from .luau_analyzer import LuauStaticAnalyzer
from .library_adapters import PROFILESTORE_SERVER, FUSION_HUD
from .agent_loop import RobloxCodeRepairAgent
from .economy_core import is_supported_economy_ledger, render_economy_ledger
from .server_modules import render_dynamic_server_bootstrap
from .host_client import render_host_client
from .host_player_data import render_callable_player_data
from .gameplay_round import render_arena_round_service, render_arena_round_controller
from .implementation_blueprint import audit_implementation_blueprint
from .gameplay_onboarding import render_game_objectives
from .model_router import ModelRouter
from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


class LuauCodeGenerator:
    """Generates idiomatic, type-checked Luau code for Roblox services with self-correction."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router or ModelRouter()
        self.analyzer = LuauStaticAnalyzer()

    def generate_all_modules(self, proposal: RobloxProposal) -> list[RobloxModuleSpec]:
        """Generates Luau code for each module in the proposal with self-correction feedback loop."""
        if "implementation_blueprint" in proposal.game_design:
            blueprint_audit = audit_implementation_blueprint(proposal)
            if not blueprint_audit["passed"]:
                raise ValueError(
                    "Blocked incomplete Roblox implementation blueprint before code generation: "
                    + "; ".join(blueprint_audit["errors"])
                )
        completed_modules: list[RobloxModuleSpec] = []
        for mod in proposal.modules:
            dynamic = proposal.game_design.get("dynamic_design") or {}
            host_owned = (
                mod.module_id == "mod_dynamic_server_bootstrap"
                or (mod.module_id.startswith("dyn_")
                    and mod.name in dynamic.get("host_client_actions", {}))
            )
            if host_owned or not mod.code:
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
            report = "\n".join(
                f"{d.file_path}:{d.line_number} [{d.rule}] {d.message}"
                for d in errors
            )
            if module.module_id.startswith("dyn_"):
                # Reflect the *actual* analyzer diagnostic back to the model
                # with its previous code; do not append guessed 'end' tokens.
                print("[RMM coder] repair " + module.name +
                      " after static errors:\n" + report[:1500], flush=True)
                code = RobloxCodeRepairAgent(router=self.router).repair(
                    module, proposal, existing_code=code,
                    diagnostics=report, attempts=2,
                )
                continue
            # Fixed first-party templates should be repaired in source control,
            # not silently rewritten as unrelated model-generated gameplay.
            raise ValueError("First-party Luau template failed static checks: " + report)
        diagnostics = self.analyzer.analyze_source(code, file_path=module.file_path)
        errors = [d for d in diagnostics if d.severity == "ERROR"]
        if errors:
            raise ValueError("Luau source failed after model correction: " +
                             "; ".join(d.message for d in errors))
        return code

    def generate_module_code(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        """Dispatches Luau code generation to specialized genre and subsystem engines."""
        # Authored novel mechanics must NEVER be dispatched to same-name
        # first-party templates whose behavior was not contract-matched.
        if module.module_id == "mod_game_objective":
            return render_game_objectives(proposal)
        if module.module_id == "mod_arena_round":
            return render_arena_round_service()
        if module.module_id == "mod_arena_round_controller":
            return render_arena_round_controller()
        if module.module_id == "mod_dynamic_server_bootstrap":
            return render_dynamic_server_bootstrap(proposal)
        if is_supported_economy_ledger(module) and module.file_path.endswith("/EconomyLedger.luau"):
            return render_economy_ledger(module)
        if (module.module_id.startswith("dyn_")
                and module.name in (
                    (proposal.game_design.get("dynamic_design") or {})
                    .get("host_client_actions", {}))):
            return render_host_client(module, proposal)
        if module.module_id.startswith("dyn_"):
            return RobloxCodeRepairAgent(router=self.router).repair(
                module, proposal,
            )
        name = module.name.lower()
        kind = module.kind.lower()

        if "modding" in name or "mod_manager" in name:
            return self._generate_modding_system(module, proposal)
        elif "network" in name or "remote" in kind or "shared" in kind:
            return self._generate_shared_network_module(module, proposal)
        elif "playerdata" in name or "data" in kind:
            if proposal.game_design.get("storage_backend") == "profilestore":
                return PROFILESTORE_SERVER
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
        elif "coincollector" in name:
            return self._generate_coin_collector(module, proposal)
        elif "hud" in name:
            if proposal.game_design.get("ui_backend") == "fusion":
                return FUSION_HUD
            return self._generate_hud_controller(module, proposal)
        else:
            return self._generate_generic_module(module, proposal)

    # 1. Shared Network Remotes Bridge
    def _generate_shared_network_module(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        dynamic = proposal.game_design.get("dynamic_design") or {}
        declared = dynamic.get("remotes") or {}
        if declared:
            # Do not ship a generic obby/tycoon/combat RPC bridge in a
            # space game that declared its own exact client/server protocol.
            # This same map is installed as Instances by the Rojo project.
            for name, kind in declared.items():
                if not re.fullmatch(r"[A-Z][A-Za-z0-9_]{2,55}", name):
                    raise ValueError("Invalid dynamic Remote name: " + str(name))
                if kind not in ("RemoteEvent", "RemoteFunction"):
                    raise ValueError("Invalid dynamic Remote class for " + name)
            remote_rows = "\n".join(
                '    ' + name + ' = "' + name + '",'
                for name in declared
            )
            type_rows = "\n".join(
                '    ' + name + ' = "' + kind + '",'
                for name, kind in declared.items()
            )
            return (
                "--!strict\n"
                "-- Shared network contract for THIS exact game architecture.\n"
                "local NetworkRemotes = {}\n"
                "NetworkRemotes.Remotes = {\n" + remote_rows + "\n}\n"
                "NetworkRemotes.RemoteTypes = {\n" + type_rows + "\n}\n"
                "return NetworkRemotes\n"
            )
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
    wins: number,
    kos: number,
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
        source = f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Production-grade player data persistence with session locking, exponential backoff, and BindToClose waiting.

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")

-- Do not even resolve a cloud DataStore while loading an unpublished
-- local Studio file. Production calls this lazily and remains fail-closed.
local PlayerDataStore: GlobalDataStore? = nil
local function activeStore(): GlobalDataStore
    if PlayerDataStore then return PlayerDataStore end
    PlayerDataStore = DataStoreService:GetDataStore("RMM_ExperienceData_v1")
    return PlayerDataStore
end

type PlayerData = {{
    coins: number,
    level: number,
    stage: number,
    clicks: number,
    wins: number,
    kos: number,
    inventory: {{ string }},
    lockToken: string?,
    lastSaved: number,
    lockUntil: number?,
}}

local sessionData: {{ [number]: PlayerData }} = {{}}
local sessionLocks: {{ [number]: string }} = {{}}
local isSaving: {{ [number]: boolean }} = {{}}
local studioEphemeral: {{ [number]: boolean }} = {{}}

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

    -- Atomically acquire a lease. An existing active owner blocks this session.
    local lockedByOther = false
    -- An unpublished Studio Place is deliberately isolated from cloud data.
    -- Live servers ALWAYS use DataStore and fail closed on profile errors.
    -- Studio sessions never modify production profiles when the API is blocked.
    local success, rawData, err
    if RunService:IsStudio() and game.GameId == 0 then
        studioEphemeral[userId] = true
        success = true
        rawData = {{ coins = 0, level = 1, stage = 1, clicks = 0, wins = 0, kos = 0,
            inventory = {{}}, lastSaved = os.time() }}
        warn("RMM Studio local preview: using memory-only profile; progress will not persist.")
    else
        success, rawData, err = retryWithBackoff(function()
            return activeStore():UpdateAsync(key, function(current)
                if current and current.lockToken and current.lockToken ~= sessionToken
                    and (current.lockUntil or 0) > os.time() then
                    lockedByOther = true
                    return nil
                end
                lockedByOther = false
                current = current or {{
                    coins = 0, level = 1, stage = 1, clicks = 0, wins = 0, kos = 0,
                    inventory = {{}}, lastSaved = os.time(),
                }}
                current.lockToken = sessionToken
                current.lockUntil = os.time() + 120
                return current
            end)
        end, 4)
        if not success and RunService:IsStudio() then
            studioEphemeral[userId] = true
            success = true
            rawData = {{ coins = 0, level = 1, stage = 1, clicks = 0, wins = 0, kos = 0,
                inventory = {{}}, lastSaved = os.time() }}
            warn("RMM Studio DataStore unavailable: temporary memory-only profile; no cloud data was changed.")
        end
    end
    if not success or lockedByOther or rawData == nil then
        warn("DataStore unavailable or profile locked for " .. player.Name .. ": " .. tostring(err))
        player:Kick("Profile is unavailable or active on another server. Please rejoin later.")
        return
    end
    local data: PlayerData = rawData :: PlayerData
    -- Upgrade existing profiles without erasing earned data.
    data.wins = math.max(0, tonumber(data.wins) or 0)
    data.kos = math.max(0, tonumber(data.kos) or 0)
    data.lockToken = sessionToken
    data.lastSaved = os.time()

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

    local owned = Instance.new("Folder")
    owned.Name = "OwnedItems"
    owned.Parent = player
    for _, id in data.inventory or {{}} do
        if type(id) == "string" then
            local marker = Instance.new("StringValue")
            marker.Name = id
            marker.Value = id
            marker.Parent = owned
        end
    end

    local winsVal = Instance.new("IntValue")
    winsVal.Name = "Wins"
    winsVal.Value = data.wins
    winsVal.Parent = leaderstats
    local kosVal = Instance.new("IntValue")
    kosVal.Name = "KOs"
    kosVal.Value = data.kos
    kosVal.Parent = leaderstats

    local levelVal = Instance.new("IntValue")
    levelVal.Name = "Level"
    levelVal.Value = data.level
    levelVal.Parent = leaderstats

    local stageVal = Instance.new("IntValue")
    stageVal.Name = "Stage"
    stageVal.Value = data.stage
    stageVal.Parent = leaderstats

    -- Renew exclusive session lease for players connected longer than two minutes.
    task.spawn(function()
        while player.Parent == Players and sessionLocks[userId] == sessionToken do
            task.wait(45)
            if player.Parent ~= Players or sessionLocks[userId] ~= sessionToken then break end
            if studioEphemeral[userId] then continue end
            -- Persist live session progress during each lease renewal. The old
            -- template only refreshed lockUntil and lost all coins/inventory
            -- earned since joining if a server crashed before PlayerRemoving.
            local profile = sessionData[userId]
            if not profile then break end
            local stats = player:FindFirstChild("leaderstats")
            if stats then
                local coins = stats:FindFirstChild("Coins")
                local level = stats:FindFirstChild("Level")
                local stage = stats:FindFirstChild("Stage")
                local wins = stats:FindFirstChild("Wins")
                local kos = stats:FindFirstChild("KOs")
                if wins and wins:IsA("IntValue") then profile.wins = wins.Value end
                if kos and kos:IsA("IntValue") then profile.kos = kos.Value end
                if coins and coins:IsA("IntValue") then profile.coins = coins.Value end
                if level and level:IsA("IntValue") then profile.level = level.Value end
                if stage and stage:IsA("IntValue") then profile.stage = stage.Value end
            end
            local ownedInventory = player:FindFirstChild("OwnedItems")
            if ownedInventory then
                local inventory = {{}}
                for _, marker in ownedInventory:GetChildren() do
                    if marker:IsA("StringValue") then
                        table.insert(inventory, marker.Name)
                    end
                end
                profile.inventory = inventory
            end
            local coinsSnapshot = profile.coins
            local levelSnapshot = profile.level
            local stageSnapshot = profile.stage
            local winsSnapshot = profile.wins
            local kosSnapshot = profile.kos
            local inventorySnapshot = profile.inventory
            local renewed, current = retryWithBackoff(function()
                return activeStore():UpdateAsync(key, function(stored)
                    if not stored or stored.lockToken ~= sessionToken then return nil end
                    stored.coins = coinsSnapshot
                    stored.level = levelSnapshot
                    stored.stage = stageSnapshot
                    stored.wins = winsSnapshot
                    stored.kos = kosSnapshot
                    stored.inventory = inventorySnapshot
                    stored.lastSaved = os.time()
                    stored.lockUntil = os.time() + 120
                    return stored
                end)
            end, 3)
            if not renewed or current == nil then
                player:Kick("Your profile session lock could not be renewed.")
                break
            end
        end
    end)
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
        local wins = leaderstats:FindFirstChild("Wins") :: IntValue?
        if wins then data.wins = wins.Value end
        local kos = leaderstats:FindFirstChild("KOs") :: IntValue?
        if kos then data.kos = kos.Value end
    end

    local owned = player:FindFirstChild("OwnedItems")
    if owned then
        data.inventory = {{}}
        for _, marker in owned:GetChildren() do
            if marker:IsA("StringValue") then
                table.insert(data.inventory, marker.Name)
            end
        end
    end
    data.lastSaved = os.time()
    if studioEphemeral[userId] then
        isSaving[userId] = false
        return true -- Preview data is intentionally NOT persisted to Roblox.
    end
    local key = getPlayerKey(userId)

    local success, savedData, err = retryWithBackoff(function()
        return activeStore():UpdateAsync(key, function(current)
            if not current or current.lockToken ~= sessionLocks[userId] then
                return nil -- never overwrite another server's profile
            end
            data.lockToken = nil
            data.lockUntil = nil
            return data
        end)
    end, 4)

    if success and savedData == nil then
        success = false
        err = "Session lease ownership lost"
    end
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
    studioEphemeral[userId] = nil
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
        if module.module_id == "mod_player_data" and module.kind == ModuleKind.SERVER_MODULE:
            return render_callable_player_data(source)
        return source

    # 3. Real Shop & Economy System
    def _generate_shop_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        # Shop weapons must obey the same active-round restrictions as melee.
        # Standalone shops must not inherit a PvP arena that was never requested.
        arena_weapon_guard = ""
        if any(m.module_id == "mod_arena_round" for m in proposal.modules):
            arena_weapon_guard = """
        if game:GetAttribute("ArenaRoundActive") ~= true
            or player:GetAttribute("InArenaRound") ~= true then return end
"""
        weapon_item = ('    magic_staff = {{ name = "Arcane Staff", price = 150, itemType = "Weapon" }},\n'
                       if proposal.game_design.get("features", {}).get("is_combat") else "")
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server-authoritative shop: validates coin balances, prevents duplicates, and delivers items.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")
local EconomyRules = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("EconomyRules"))

local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local purchaseFunction = remotesFolder:WaitForChild("ShopPurchase") :: RemoteFunction
local weaponUse = remotesFolder:WaitForChild("ShopWeaponUse") :: RemoteEvent

-- Catalog of items available in the shop
local SHOP_ITEMS: {{ [string]: {{ name: string, price: number, itemType: string }} }} = {{
    speed_boots = {{ name = "Speed Boots", price = 50, itemType = "Gear" }},
{weapon_item.rstrip()}
    shield = {{ name = "Iron Shield", price = 100, itemType = "Armor" }},
    health_potion = {{ name = "Health Potion", price = 25, itemType = "Consumable" }},
}}

local lastPurchaseByUserId: {{ [number]: number }} = {{}}
local lastCastByUserId: {{ [number]: number }} = {{}}
local MAX_SHOP_DISTANCE = 18
local PURCHASE_COOLDOWN = 0.35

-- Permanent shop items must be restored after a new character spawns.
-- Keep the spell server-owned and exclude the caster from raycasts.
local function grantMagicStaff(player: Player): boolean
    local backpack = player:FindFirstChildOfClass("Backpack")
    if not backpack then return false end
    local character = player.Character
    if backpack:FindFirstChild("Arcane Staff")
        or (character and character:FindFirstChild("Arcane Staff")) then
        return true
    end
    local tool = Instance.new("Tool")
    tool.Name = SHOP_ITEMS.magic_staff.name
    tool.RequiresHandle = false
    -- Client LocalScript owns activation. This server script owns damage.
    tool.Parent = backpack
    return true
end

-- Remote clients can supply only the weapon identifier. The server checks
-- equip state, paid ownership, round membership, cooldown and raycast hit.
weaponUse.OnServerEvent:Connect(function(player: Player, weaponId: any)
    if typeof(weaponId) ~= "string" or weaponId ~= "magic_staff" then return end
    if not SHOP_ITEMS.magic_staff or player.Parent ~= Players then return end
    local owned = player:FindFirstChild("OwnedItems")
    if not owned or not owned:FindFirstChild("magic_staff") then return end
    local caster = player.Character
    local weapon = caster and caster:FindFirstChild("Arcane Staff")
    local humanoid = caster and caster:FindFirstChildOfClass("Humanoid")
    local castRoot = caster and caster:FindFirstChild("HumanoidRootPart")
    if not weapon or not weapon:IsA("Tool") or not humanoid or humanoid.Health <= 0
        or not castRoot or not castRoot:IsA("BasePart") then return end
{arena_weapon_guard}
    local now = os.clock()
    if now - (lastCastByUserId[player.UserId] or -10000) < 1 then return end
    lastCastByUserId[player.UserId] = now
    local params = RaycastParams.new()
    params.FilterType = Enum.RaycastFilterType.Exclude
    params.FilterDescendantsInstances = {{caster}}
    local ray = workspace:Raycast(castRoot.Position, castRoot.CFrame.LookVector * 30, params)
    local targetModel = ray and ray.Instance:FindFirstAncestorOfClass("Model")
    local target = targetModel and targetModel:FindFirstChildOfClass("Humanoid")
    if not target or target.Health <= 0 or targetModel == caster then return end
    if game:GetAttribute("ArenaRoundActive") then
        local opponent = Players:GetPlayerFromCharacter(targetModel)
        if not opponent or opponent:GetAttribute("InArenaRound") ~= true then return end
    end
    local credit = ServerScriptService:FindFirstChild("RMMCombatCredit")
    if credit and credit:IsA("BindableEvent") then credit:Fire(player, target) end
    target:TakeDamage(20)
end)

local function handlePurchase(player: Player, itemId: string): (boolean, string)
    -- Roblox RemoteFunction arguments are UNTRUSTED, regardless of Luau type annotations.
    if typeof(itemId) ~= "string" or #itemId > 48 then
        return false, "Invalid item id"
    end
    local now = os.clock()
    if now - (lastPurchaseByUserId[player.UserId] or -10000) < PURCHASE_COOLDOWN then
        return false, "Purchase cooldown"
    end
    lastPurchaseByUserId[player.UserId] = now
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    local shopFolder = workspace:FindFirstChild("ShopStalls")
    local counter = shopFolder and shopFolder:FindFirstChild("ShopCounter")
    if not humanoid or humanoid.Health <= 0 or not root or not root:IsA("BasePart") then
        return false, "Character unavailable"
    end
    if not counter or not counter:IsA("BasePart") or (root.Position - counter.Position).Magnitude > MAX_SHOP_DISTANCE then
        return false, "You must be near the shop to purchase"
    end
    local item = SHOP_ITEMS[itemId]
    if not item then
        return false, "Item does not exist in catalog."
    end

    local leaderstats = player:FindFirstChild("leaderstats")
    if not leaderstats then
        return false, "Leaderstats not initialized."
    end

    local coinsVal = leaderstats:FindFirstChild("Coins") :: IntValue?
    if not coinsVal or not EconomyRules.canAfford(coinsVal.Value, item.price) then
        return false, "Insufficient coins! You need " .. item.price .. " coins."
    end

    local owned = player:FindFirstChild("OwnedItems")
    if itemId ~= "health_potion" and owned and owned:FindFirstChild(itemId) then
        return false, "Already owned"
    end

    -- Deduct currency server-authoritatively
    coinsVal.Value = EconomyRules.charge(coinsVal.Value, item.price) :: number


    -- Deliver concrete gameplay effects, not empty cosmetic Tools.
    if itemId == "speed_boots" then
        if not humanoid then coinsVal.Value += item.price; return false, "Character unavailable" end
        humanoid.WalkSpeed = math.max(humanoid.WalkSpeed, 24)
    elseif itemId == "shield" then
        if not humanoid then coinsVal.Value += item.price; return false, "Character unavailable" end
        humanoid.MaxHealth += 50
        humanoid.Health += 50
    elseif itemId == "health_potion" then
        if not humanoid then coinsVal.Value += item.price; return false, "Character unavailable" end
        humanoid.Health = math.min(humanoid.Health + 50, humanoid.MaxHealth)
    elseif itemId == "magic_staff" then
        if not grantMagicStaff(player) then
            coinsVal.Value += item.price
            return false, "Backpack unavailable"
        end
    else
        coinsVal.Value += item.price
        return false, "Unimplemented item"
    end

    if itemId ~= "health_potion" then
        local inventory = owned or Instance.new("Folder")
        inventory.Name = "OwnedItems"
        inventory.Parent = player
        local marker = Instance.new("StringValue")
        marker.Name = itemId
        marker.Value = itemId
        marker.Parent = inventory
    end
    return true, "Successfully purchased " .. item.name .. "!"
end

purchaseFunction.OnServerInvoke = handlePurchase
Players.PlayerRemoving:Connect(function(player)
    lastPurchaseByUserId[player.UserId] = nil
    lastCastByUserId[player.UserId] = nil
end)

local function restoreEquipment(player: Player, character: Model)
    local owned = player:WaitForChild("OwnedItems", 10)
    local humanoid = character:WaitForChild("Humanoid", 10)
    if not owned or not humanoid then return end
    if owned:FindFirstChild("speed_boots") then humanoid.WalkSpeed = 24 end
    if owned:FindFirstChild("shield") then
        humanoid.MaxHealth += 50
        humanoid.Health += 50
    end
    if owned:FindFirstChild("magic_staff") then
        player:WaitForChild("Backpack", 10)
        grantMagicStaff(player)
    end
end
local function onAdded(player: Player)
    player.CharacterAdded:Connect(function(char) restoreEquipment(player, char) end)
    if player.Character then task.spawn(restoreEquipment, player, player.Character) end
end
Players.PlayerAdded:Connect(onAdded)
for _, player in Players:GetPlayers() do onAdded(player) end
"""

    def _generate_shop_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: StarterPlayerScripts
-- Script: {module.name}
-- Description: Client shop interaction handler with ProximityPrompt binding and purchase requests.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
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

-- Shop prompt opens the full catalog UI; no implicit purchase.
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShopGui"
gui.ResetOnSpawn = false
gui.Parent = localPlayer:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Name = "ShopPanel"
panel.Size = UDim2.fromOffset(300, 290)
panel.Position = UDim2.new(0.5, -150, 0.5, -145)
panel.Visible = false
panel.Parent = gui
local items = {{
    {{"speed_boots", "Speed Boots - 50"}},
    {{"magic_staff", "Arcane Staff - 150"}},
    {{"shield", "Iron Shield - 100"}},
    {{"health_potion", "Health Potion - 25"}},
}}
for index, item in items do
    local button = Instance.new("TextButton")
    button.Name = item[1]
    button.Size = UDim2.new(1, -20, 0, 42)
    button.Position = UDim2.fromOffset(10, (index - 1) * 50 + 8)
    button.Text = item[2]
    button.Parent = panel
    button.Activated:Connect(function() requestBuy(item[1]) end)
end
local close = Instance.new("TextButton")
close.Name = "Close"
close.Text = "Close shop"
close.Position = UDim2.fromOffset(10, 213)
close.Size = UDim2.new(1, -20, 0, 42)
close.Parent = panel
close.Activated:Connect(function() panel.Visible = false end)
local function connectPrompt(prompt: ProximityPrompt)
    prompt.Triggered:Connect(function() panel.Visible = true end)
end
local shops = workspace:WaitForChild("ShopStalls")
for _, obj in shops:GetDescendants() do
    if obj:IsA("ProximityPrompt") then connectPrompt(obj) end
end
shops.DescendantAdded:Connect(function(obj)
    if obj:IsA("ProximityPrompt") then connectPrompt(obj) end
end)
"""

    # 4. Real Obby / Parkour System
    def _generate_obby_service(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server-authoritative parkour manager: tracks checkpoints and handles hazard collisions.

local Players = game:GetService("Players")
local lastStage = {max(1, min(int(proposal.game_design.get("requested_counts", {}).get("stages", 5)), 128))}

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

                    if stageVal and (padStage == stageVal.Value + 1
                        or (padStage == lastStage and stageVal.Value == lastStage)) then
                        stageVal.Value = padStage
                        pad.Color = Color3.fromRGB(0, 255, 100)
                        if padStage == lastStage and not player:GetAttribute("ObbyComplete") then
                            player:SetAttribute("ObbyComplete", true)
                        end
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

local gui = Instance.new("ScreenGui")
gui.Name = "RMMStageStatus"
gui.ResetOnSpawn = false
gui.Parent = localPlayer:WaitForChild("PlayerGui")
local completion = Instance.new("TextLabel")
completion.Name = "StageCompletion"
completion.Size = UDim2.fromOffset(260, 48)
completion.Position = UDim2.fromOffset(16, 122)
completion.TextScaled = true
completion.Parent = gui
local function refreshCompletion()
    completion.Text = localPlayer:GetAttribute("ObbyComplete")
        and "Course completed! Replay anytime."
        or ("Checkpoint " .. tostring(stageVal.Value))
end
localPlayer:GetAttributeChangedSignal("ObbyComplete"):Connect(refreshCompletion)
stageVal.Changed:Connect(refreshCompletion)
refreshCompletion()

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
        arena_guard = ""
        if proposal is not None and any(m.module_id == "mod_arena_round" for m in proposal.modules):
            arena_guard = """
    -- Arena PvP is legal only for two active server-enrolled contestants.
    if not game:GetAttribute("ArenaRoundActive")
        or not player:GetAttribute("InArenaRound") then return end
    local opponent = Players:GetPlayerFromCharacter(targetCharacter)
    if not opponent or not opponent:GetAttribute("InArenaRound") then return end
"""
        return f"""--!strict
-- Service: ServerScriptService
-- Script: {module.name}
-- Description: Server-authoritative combat: reach sanity checks, cooldown enforcement, and damage calculation.

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local ServerScriptService = game:GetService("ServerScriptService")

local remotesFolder = ReplicatedStorage:WaitForChild("Remotes")
local attackRemote = remotesFolder:FindFirstChild("AttackRequest") :: RemoteEvent?
if not attackRemote then
    attackRemote = Instance.new("RemoteEvent")
    attackRemote.Name = "AttackRequest"
    attackRemote.Parent = remotesFolder
end

local playerCooldowns: {{ [number]: number }} = {{}}
local MAX_REACH = 15.0
local KNOCKOUT_REWARD_COINS = 25
local knockoutCredits: {{ [Humanoid]: {{ player: Player, time: number }} }} = {{}}
local deathMonitored: {{ [Humanoid]: boolean }} = {{}}
local combatCredit = Instance.new("BindableEvent")
combatCredit.Name = "RMMCombatCredit"
combatCredit.Parent = ServerScriptService

local function trackKnockout(targetHumanoid: Humanoid, attacker: Player)
    knockoutCredits[targetHumanoid] = {{ player = attacker, time = os.clock() }}
    if deathMonitored[targetHumanoid] then return end
    deathMonitored[targetHumanoid] = true
    targetHumanoid.Died:Connect(function()
        local credit = knockoutCredits[targetHumanoid]
        knockoutCredits[targetHumanoid] = nil
        deathMonitored[targetHumanoid] = nil
        if not credit or os.clock() - credit.time > 8 then return end
        if credit.player.Parent ~= Players then return end
        local leaderstats = credit.player:FindFirstChild("leaderstats")
        local coins = leaderstats and leaderstats:FindFirstChild("Coins")
        if coins and coins:IsA("IntValue") then
            coins.Value += KNOCKOUT_REWARD_COINS
        end
        local kos = leaderstats and leaderstats:FindFirstChild("KOs")
        if kos and kos:IsA("IntValue") then kos.Value += 1 end
    end)
    targetHumanoid.Destroying:Connect(function()
        knockoutCredits[targetHumanoid] = nil
        deathMonitored[targetHumanoid] = nil
    end)
end

-- A BindableEvent is server-only; client RemoteEvents cannot forge staff credits.
combatCredit.Event:Connect(function(player: Player, target: Humanoid)
    if not player or player.Parent ~= Players or not target or not target:IsA("Humanoid") then return end
    if game:GetAttribute("ArenaRoundActive") then
        local victim = Players:GetPlayerFromCharacter(target.Parent)
        if not victim or not victim:GetAttribute("InArenaRound")
            or not player:GetAttribute("InArenaRound") then return end
    end
    trackKnockout(target, player)
end)

attackRemote.OnServerEvent:Connect(function(player, targetCharacter: Model?)
    if not targetCharacter or not targetCharacter:IsA("Model") then return end
{arena_guard}
    local userId = player.UserId
    local now = os.clock()
    if playerCooldowns[userId] and (now - playerCooldowns[userId]) < 0.4 then
        return -- Rate limit attack spam
    end
    playerCooldowns[userId] = now

    local char = player.Character
    if not char or targetCharacter == char then return end
    local attacker = char:FindFirstChildOfClass("Humanoid")
    if not attacker or attacker.Health <= 0 then return end
    local root = char:FindFirstChild("HumanoidRootPart") :: BasePart?
    local targetRoot = targetCharacter:FindFirstChild("HumanoidRootPart") :: BasePart?
    local targetHumanoid = targetCharacter:FindFirstChild("Humanoid") :: Humanoid?

    if not root or not targetRoot or not targetHumanoid or targetHumanoid.Health <= 0 then return end
    if not targetCharacter:IsDescendantOf(workspace) then return end

    -- Server-side anti-cheat distance validation
    local distance = (root.Position - targetRoot.Position).Magnitude
    if distance > MAX_REACH then
        warn("Anti-cheat: attack rejected for distance violation (" .. math.floor(distance) .. " studs)")
        return
    end

    -- Client chooses a candidate, but server independently checks line of sight.
    local params = RaycastParams.new()
    params.FilterType = Enum.RaycastFilterType.Exclude
    params.FilterDescendantsInstances = {{char}}
    local ray = workspace:Raycast(root.Position, targetRoot.Position - root.Position, params)
    if not ray or not ray.Instance:IsDescendantOf(targetCharacter) then return end
    trackKnockout(targetHumanoid, player)
    targetHumanoid:TakeDamage(20)
end)
"""

    def _generate_combat_controller(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        return f"""--!strict
-- Roblox cross-platform combat: mouse, touch and gamepad actions.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ContextActionService = game:GetService("ContextActionService")
local SoundService = game:GetService("SoundService")

local localPlayer = Players.LocalPlayer
local attackRemote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("AttackRequest") :: RemoteEvent

local function attack(_actionName: string, state: Enum.UserInputState, _input: InputObject)
    if state ~= Enum.UserInputState.Begin then return Enum.ContextActionResult.Pass end
    local camera = workspace.CurrentCamera
    if not camera then return Enum.ContextActionResult.Pass end
    local viewport = camera.ViewportSize
    local ray = camera:ViewportPointToRay(viewport.X * 0.5, viewport.Y * 0.5)
    local params = RaycastParams.new()
    local character = localPlayer.Character
    if character then
        params.FilterType = Enum.RaycastFilterType.Exclude
        params.FilterDescendantsInstances = {{character}}
    end
    local hit = workspace:Raycast(ray.Origin, ray.Direction * 100, params)
    local model = hit and hit.Instance:FindFirstAncestorOfClass("Model")
    if model and model:FindFirstChildOfClass("Humanoid") then
        attackRemote:FireServer(model)
        local sound = SoundService:FindFirstChild("SwordSlashSound") :: Sound?
        if sound then sound:Play() end
    end
    return Enum.ContextActionResult.Sink
end

ContextActionService:BindAction(
    "RMM_Attack", attack, true,
    Enum.UserInputType.MouseButton1, Enum.KeyCode.ButtonR2
)
ContextActionService:SetTitle("RMM_Attack", "Attack")
"""

    def _generate_coin_collector(self, module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
        """Server-owned physical coin pickup; depends on Rojo-created Workspace Coins."""
        return """--!strict
local Players = game:GetService("Players")
local coinsFolder = workspace:WaitForChild("Coins")

local function bindCoin(coin: Instance)
    if not coin:IsA("BasePart") then return end
    local available = true
    coin.Touched:Connect(function(hit: BasePart)
        if not available then return end
        local character = hit:FindFirstAncestorOfClass("Model")
        if not character then return end
        local player = Players:GetPlayerFromCharacter(character)
        if not player then return end
        local leaderstats = player:FindFirstChild("leaderstats")
        local coins = leaderstats and leaderstats:FindFirstChild("Coins")
        if not coins or not coins:IsA("IntValue") then return end
        available = false
        coins.Value += 10
        coin.Transparency = 1
        coin.CanTouch = false
        task.delay(8, function()
            if not coin.Parent then return end
            coin.Transparency = 0
            coin.CanTouch = true
            available = true
        end)
    end)
end

for _, coin in coinsFolder:GetChildren() do bindCoin(coin) end
coinsFolder.ChildAdded:Connect(bindCoin)
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

local gui = Instance.new("ScreenGui")
gui.Name = "RMMHUD"
gui.ResetOnSpawn = false
gui.Parent = localPlayer:WaitForChild("PlayerGui")
local label = Instance.new("TextLabel")
label.Name = "CoinsDisplay"
label.Size = UDim2.fromOffset(190, 44)
label.Position = UDim2.fromOffset(16, 16)
label.TextScaled = true
label.Parent = gui
local function updateCoins()
    label.Text = "Coins: " .. tostring(coins.Value)
end
coins.Changed:Connect(updateCoins)
updateCoins()

-- Follow the current Humanoid across respawns; the HUD must not freeze on
-- the first character's health or accumulate duplicate event connections.
local health = Instance.new("TextLabel")
health.Name = "HealthDisplay"
health.Size = UDim2.fromOffset(190, 44)
health.Position = UDim2.fromOffset(16, 66)
health.TextScaled = true
health.Parent = gui
local healthChanged: RBXScriptConnection? = nil
local maxHealthChanged: RBXScriptConnection? = nil

local function bindCharacter(character: Model)
    if healthChanged then healthChanged:Disconnect() end
    if maxHealthChanged then maxHealthChanged:Disconnect() end
    local humanoid = character:WaitForChild("Humanoid") :: Humanoid
    local function updateHealth()
        health.Text = "HP: " .. tostring(math.ceil(math.max(0, humanoid.Health)))
            .. "/" .. tostring(math.ceil(humanoid.MaxHealth))
    end
    healthChanged = humanoid.HealthChanged:Connect(updateHealth)
    maxHealthChanged = humanoid:GetPropertyChangedSignal("MaxHealth"):Connect(updateHealth)
    updateHealth()
end
localPlayer.CharacterAdded:Connect(bindCharacter)
if localPlayer.Character then task.spawn(bindCharacter, localPlayer.Character) end
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
        """Never return an empty Lua table and pretend an unknown game was implemented."""
        return RobloxCodeRepairAgent(router=self.router).repair(module, proposal)
