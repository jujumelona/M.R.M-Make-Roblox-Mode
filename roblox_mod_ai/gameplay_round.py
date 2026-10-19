"""Host-owned Roblox arena round implementation for explicit round-based games.

A solo player waits for another contestant; there are no invented NPCs.
Only server-side health, participation and departure decide the round result.
"""
from __future__ import annotations


def render_arena_round_service() -> str:
    return '''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local statusRemote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("RoundStatus") :: RemoteEvent

local MIN_PLAYERS = 2
local COUNTDOWN = 5
local ROUND_DURATION = 120
local INTERMISSION = 8
local VICTORY_REWARD = 100

local phase = "Waiting"
local message = "Waiting for another fighter"
local timeLeft = 0

local function announce(nextPhase: string, text: string, remaining: number)
    phase, message, timeLeft = nextPhase, text, remaining
    statusRemote:FireAllClients(phase, message, timeLeft)
end
local function eligible(): {Player}
    local roster: {Player} = {}
    for _, player in Players:GetPlayers() do
        local char = player.Character
        local humanoid = char and char:FindFirstChildOfClass("Humanoid")
        if humanoid and humanoid.Health > 0 then
            table.insert(roster, player)
        end
    end
    return roster
end

Players.PlayerAdded:Connect(function(player)
    task.defer(function()
        if player.Parent == Players then
            statusRemote:FireClient(player, phase, message, timeLeft)
        end
    end)
end)

task.spawn(function()
    while true do
        local ready = eligible()
        if #ready < MIN_PLAYERS then
            announce("Waiting", "Need at least 2 fighters", 0)
            task.wait(2)
            continue
        end
        local cancelled = false
        for remaining = COUNTDOWN, 1, -1 do
            if #eligible() < MIN_PLAYERS then
                cancelled = true
                break
            end
            announce("Starting", "Arena battle begins soon", remaining)
            task.wait(1)
        end
        if cancelled then continue end
        ready = eligible()
        if #ready < MIN_PLAYERS then continue end
        local fighters: {[Player]: Humanoid} = {}
        local connections: {RBXScriptConnection} = {}
        local alive: {[Player]: boolean} = {}
        for _, player in ready do
            local character = player.Character
            local humanoid = character and character:FindFirstChildOfClass("Humanoid")
            if humanoid and humanoid.Health > 0 then
                fighters[player] = humanoid
                alive[player] = true
                table.insert(connections, humanoid.Died:Connect(function()
                    alive[player] = false
                end))
            end
        end
        if #ready < MIN_PLAYERS then continue end
        local winner: Player? = nil
        for remaining = ROUND_DURATION, 0, -1 do
            local survivors: {Player} = {}
            for player, humanoid in fighters do
                if alive[player] and player.Parent == Players
                    and player.Character == humanoid.Parent and humanoid.Health > 0 then
                    table.insert(survivors, player)
                end
            end
            if #survivors <= 1 then
                winner = survivors[1]
                break
            end
            announce("Active", "Fight! Last fighter standing wins", remaining)
            task.wait(1)
        end
        for _, conn in connections do conn:Disconnect() end
        if winner and winner.Parent == Players then
            local leaderstats = winner:FindFirstChild("leaderstats")
            local coins = leaderstats and leaderstats:FindFirstChild("Coins")
            if coins and coins:IsA("IntValue") then
                coins.Value += VICTORY_REWARD
            end
            announce("Winner", winner.DisplayName .. " wins! +" .. VICTORY_REWARD .. " coins", INTERMISSION)
        else
            announce("Draw", "No winner this round", INTERMISSION)
        end
        task.wait(INTERMISSION)
        for player in fighters do
            if player.Parent == Players then
                task.spawn(function()
                    local ok, err = pcall(function()
                        player:LoadCharacterAsync()
                    end)
                    if not ok then warn("Could not restore fighter: " .. tostring(err)) end
                end)
            end
        end
        announce("Cooldown", "Preparing the next round", 3)
        task.wait(3)
    end
end)
'''


def render_arena_round_controller() -> str:
    return '''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local localPlayer = Players.LocalPlayer
local event = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("RoundStatus") :: RemoteEvent

local gui = Instance.new("ScreenGui")
gui.Name = "RMMRoundStatus"
gui.ResetOnSpawn = false
gui.Parent = localPlayer:WaitForChild("PlayerGui")
local label = Instance.new("TextLabel")
label.Name = "RoundStatusLabel"
label.Size = UDim2.fromOffset(320, 56)
label.Position = UDim2.fromOffset(16, 120)
label.TextScaled = true
label.BackgroundTransparency = 0.25
label.Text = "Waiting for arena contestants..."
label.Parent = gui
event.OnClientEvent:Connect(function(phase: string, message: string, seconds: number)
    label.Text = "[" .. phase .. "] " .. message ..
        (seconds > 0 and (" (" .. seconds .. "s)") or "")
end)
'''
