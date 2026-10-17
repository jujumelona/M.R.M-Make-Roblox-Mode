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

local authorizedToPurchase = false
ready.OnClientEvent:Connect(function(command)
    if command == "buy" then
        authorizedToPurchase = true
        return
    end
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
    if coins.Value - startCoins < 50 then
        report:FireServer({phase="purchased", purchaseSucceeded=false})
        return
    end

    -- Synchronize with the test server so it snapshots actual Coins before purchase.
    report:FireServer({phase="collected"})
    local deadline = os.clock() + 12
    while not authorizedToPurchase and os.clock() < deadline do task.wait(0.1) end
    if not authorizedToPurchase then return end

    local remoteFolder = ReplicatedStorage:WaitForChild("Remotes", 10)
    local purchase = remoteFolder and remoteFolder:FindFirstChild("ShopPurchase")
    local called, success = false, false
    if purchase and purchase:IsA("RemoteFunction") then
        called, success = pcall(function() return purchase:InvokeServer("speed_boots") end)
    end
    report:FireServer({phase="purchased", purchaseSucceeded=called and success == true})
end)
