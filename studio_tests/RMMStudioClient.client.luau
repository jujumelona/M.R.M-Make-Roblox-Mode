--!strict
-- Only active when a dedicated StudioTestService test is running.
local RunService = game:GetService("RunService")
if not RunService:IsStudio() then return end
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local StudioTestService = game:GetService("StudioTestService")

local ready = ReplicatedStorage:WaitForChild("RMM_E2E_READY", 20)
if not ready then return end
local report = ReplicatedStorage:WaitForChild("RMM_E2E_REPORT", 20)
if not report then return end
local player = Players.LocalPlayer

local function walkToCoin(humanoid, coin)
    humanoid:MoveTo(coin.Position)
    local arrived = false
    local conn = humanoid.MoveToFinished:Connect(function() arrived = true end)
    local deadline = os.clock() + 9
    while not arrived and os.clock() < deadline do task.wait(0.15) end
    conn:Disconnect()
end

ready.OnClientEvent:Connect(function(command)
    if command == "leave" then
        if StudioTestService:CanLeaveTest() then StudioTestService:LeaveTest() end
        return
    end
    if command ~= "run" then return end
    local character = player.Character or player.CharacterAdded:Wait()
    local humanoid = character:WaitForChild("Humanoid", 20)
    if not humanoid then
        report:FireServer({coinsCollected=false})
        return
    end
    local leaderstats = player:WaitForChild("leaderstats", 20)
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins then
        report:FireServer({coinsCollected=false})
        return
    end
    local startCoins = coins.Value
    local folder = workspace:WaitForChild("Coins", 20)
    if not folder then report:FireServer({coinsCollected=false}); return end
    for _, coin in folder:GetChildren() do
        if coins.Value - startCoins >= 50 then break end
        if coin:IsA("BasePart") then walkToCoin(humanoid, coin) end
    end
    local collection = coins.Value - startCoins >= 50
    local purchaseSucceeded, effect, deducted = false, false, false
    if collection then
        local balanceBefore = coins.Value
        local remoteFolder = ReplicatedStorage:WaitForChild("Remotes", 10)
        local purchase = remoteFolder and remoteFolder:FindFirstChild("ShopPurchase")
        if purchase and purchase:IsA("RemoteFunction") then
            local called, success = pcall(function() return purchase:InvokeServer("speed_boots") end)
            purchaseSucceeded = called and success == true
            task.wait(0.5)
            effect = humanoid.WalkSpeed >= 24
            deducted = coins.Value == balanceBefore - 50
        end
    end
    report:FireServer({coinsCollected=collection,
        purchaseSucceeded=purchaseSucceeded, realItemEffect=effect, coinsDeducted=deducted})
end)
