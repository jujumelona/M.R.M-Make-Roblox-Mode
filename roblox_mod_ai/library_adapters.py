"""Opt-in, upstream-compatible gameplay library adapters.

ProfileStore: lm-loleris/profilestore@1.0.3 (Apache-2.0)
Fusion: elttob/fusion@0.3.0 (MIT)
Install via Wally. Never report runtime verified without Studio.
"""
PROFILESTORE_SERVER = """--!strict
-- ProfileStore owns autosave, lease conflict handling and session closing.
local Players = game:GetService("Players")
local ProfileStore = require(game:GetService("ServerScriptService"):WaitForChild("ServerPackages"):WaitForChild("ProfileStore"))
local template = {coins=0, level=1, stage=1, clicks=0, wins=0, kos=0, inventory={}}
local store = ProfileStore.New("RMM_ExperienceData_ProfileStore_v1", template)
local profiles = {}

local function loadPlayer(player: Player)
    local profile = store:StartSessionAsync("Player_" .. tostring(player.UserId), {
        Cancel = function() return player.Parent ~= Players end,
    })
    if not profile then player:Kick("Profile session unavailable; reconnect later"); return end
    profile:AddUserId(player.UserId)
    profile:Reconcile()
    profile.OnSessionEnd:Connect(function()
        profiles[player] = nil
        if player.Parent then player:Kick("Profile session closed; reconnect") end
    end)
    if player.Parent ~= Players then profile:EndSession(); return end
    profiles[player] = profile

    local stats = Instance.new("Folder")
    stats.Name = "leaderstats"
    stats.Parent = player
    for _, entry in {{"Coins", "coins"}, {"Level", "level"}, {"Stage", "stage"}, {"Wins", "wins"}, {"KOs", "kos"}} do
        local value = Instance.new("IntValue")
        value.Name = entry[1]
        value.Value = profile.Data[entry[2]]
        value.Parent = stats
        value.Changed:Connect(function(nextValue)
            if profiles[player] == profile then
                profile.Data[entry[2]] = nextValue
            end
        end)
    end
    local owned = Instance.new("Folder")
    owned.Name = "OwnedItems"
    owned.Parent = player
    for _, item in profile.Data.inventory do
        if type(item) == "string" then
            local marker = Instance.new("StringValue")
            marker.Name = item
            marker.Value = item
            marker.Parent = owned
        end
    end
    local function syncInventory()
        if profiles[player] ~= profile then return end
        local inventory = {}
        for _, item in owned:GetChildren() do
            if item:IsA("StringValue") then table.insert(inventory, item.Name) end
        end
        profile.Data.inventory = inventory
    end
    owned.ChildAdded:Connect(syncInventory)
    owned.ChildRemoved:Connect(syncInventory)
end

Players.PlayerAdded:Connect(loadPlayer)
for _, player in Players:GetPlayers() do task.spawn(loadPlayer, player) end
Players.PlayerRemoving:Connect(function(player)
    local profile = profiles[player]
    if profile then
        profiles[player] = nil
        local stats = player:FindFirstChild("leaderstats")
        if stats then
            for name, field in {Coins="coins", Level="level", Stage="stage", Wins="wins", KOs="kos"} do
                local val = stats:FindFirstChild(name)
                if val then profile.Data[field] = val.Value end
            end
        end
        local owned = player:FindFirstChild("OwnedItems")
        if owned then
            local inventory = {}
            for _, item in owned:GetChildren() do
                if item:IsA("StringValue") then table.insert(inventory, item.Name) end
            end
            profile.Data.inventory = inventory
        end
        profile:EndSession()
    end
end)

game:BindToClose(function()
    for _, profile in profiles do
        if profile then profile:EndSession() end
    end
end)
"""

FUSION_HUD = """--!strict
-- Fusion reactive HUD: Wally elttob/fusion@0.3.0
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Fusion = require(ReplicatedStorage:WaitForChild("Packages"):WaitForChild("Fusion"))
local scope = Fusion.scoped({})
local localPlayer = Players.LocalPlayer
local stats = localPlayer:WaitForChild("leaderstats")
local coins = stats:WaitForChild("Coins") :: IntValue
local coinState = scope:Value(coins.Value)
scope:New("ScreenGui")({
    Name = "RMMHUD",
    ResetOnSpawn = false,
    Parent = localPlayer:WaitForChild("PlayerGui"),
    [Fusion.Children] = {
        scope:New("TextLabel")({
            Name = "CoinsDisplay",
            Size = UDim2.fromOffset(190, 44),
            Position = UDim2.fromOffset(16, 16),
            TextScaled = true,
            Text = scope:Computed(function(use)
                return "Coins: " .. tostring(use(coinState))
            end),
        }),
    },
})
coins.Changed:Connect(function() coinState:set(coins.Value) end)
"""
