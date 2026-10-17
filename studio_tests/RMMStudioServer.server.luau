--!strict
-- Injected ONLY into a Studio E2E test place, never production Rojo builds.
local RunService = game:GetService("RunService")
if not RunService:IsStudio() then return end

local StudioTestService = game:GetService("StudioTestService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local DataStoreService = game:GetService("DataStoreService")
local args = StudioTestService:GetTestArgs()
if type(args) ~= "table" or args.suite ~= "RMM_E2E_V1" then return end

local status = Instance.new("RemoteEvent")
status.Name = "RMM_E2E_READY"
status.Parent = ReplicatedStorage
local report = Instance.new("RemoteEvent")
report.Name = "RMM_E2E_REPORT"
report.Parent = ReplicatedStorage

local function finish(value)
    StudioTestService:EndTest(value)
end

local function getCoins(player)
    local ls = player:WaitForChild("leaderstats", 20)
    if not ls then return nil end
    return ls:FindFirstChild("Coins")
end

local deadline = os.clock() + 50
while #Players:GetPlayers() < (args.phase == "play" and 2 or 1) and os.clock() < deadline do
    task.wait(0.2)
end
local members = Players:GetPlayers()
local p = members[1]
if not p then
    finish({ok=false, reason="No simulated players"})
    return
end

local coins = getCoins(p)
if not coins or not coins:IsA("IntValue") then
    finish({ok=false, reason="Leaderstats missing (DataStore load may have failed)"})
    return
end

if args.phase == "restore" then
    if p.UserId ~= args.userId then
        finish({ok=false, reason="Simulated userId changed: cannot claim same-user restore"})
        return
    end
    local owned = p:WaitForChild("OwnedItems", 15)
    local restored = coins.Value == args.coins and owned and owned:FindFirstChild("speed_boots") ~= nil
    finish({ok=restored == true, coins=coins.Value,
        reason=restored and "same simulated UserId restored data" or "Coins/items did not restore"})
    return
end

if args.phase ~= "play" then finish({ok=false, reason="Unknown phase"}); return end
if not workspace:FindFirstChild("Coins") or not workspace:FindFirstChild("ShopStalls") then
    finish({ok=false, reason="Missing coin/shop world"})
    return
end
if #members < 2 then
    finish({ok=false, reason="Expected two simulated clients"})
    return
end

local startingCoins = coins.Value
local secondClient = members[2]
local secondCoins = getCoins(secondClient)
if not secondCoins then
    finish({ok=false, reason="Second client lacks replicated leaderstats"})
    return
end
local secondStartingCoins = secondCoins.Value
local beforePurchaseCoins = nil
local clientReport = nil

report.OnServerEvent:Connect(function(sender, payload)
    if sender ~= p or type(payload) ~= "table" then return end
    if payload.phase == "collected" and beforePurchaseCoins == nil then
        local collected = coins.Value - startingCoins
        if collected >= 50 then
            beforePurchaseCoins = coins.Value
            status:FireClient(p, "buy")
        else
            clientReport = {phase="rejected", reason="server observed insufficient collected coins"}
        end
    elseif payload.phase == "purchased" and beforePurchaseCoins ~= nil then
        clientReport = payload
    end
end)

status:FireClient(p, "run")
deadline = os.clock() + 95
while not clientReport and os.clock() < deadline do task.wait(0.2) end
if not clientReport then
    finish({ok=false, reason="Client did not finish coin pickup + shop purchase"})
    return
end

local character = p.Character
local humanoid = character and character:FindFirstChildOfClass("Humanoid")
local owned = p:FindFirstChild("OwnedItems")
local effectOnServer = humanoid and humanoid.WalkSpeed >= 24
local ownedOnServer = owned and owned:FindFirstChild("speed_boots") ~= nil
local chargedCorrectly = beforePurchaseCoins ~= nil and coins.Value == beforePurchaseCoins - 50
local independentSecondClient = secondCoins.Value == secondStartingCoins
local ok = (
    clientReport.phase == "purchased"
    and clientReport.purchaseSucceeded == true
    and beforePurchaseCoins ~= nil
    and beforePurchaseCoins - startingCoins >= 50
    and effectOnServer
    and ownedOnServer
    and chargedCorrectly
    and independentSecondClient
)
local expectedCoins = coins.Value
local userId = p.UserId
if not ok then
    finish({
        ok=false,
        reason="Server-authoritative coin/shop checks failed",
        collectedBeforePurchase = beforePurchaseCoins,
        initialBalance=startingCoins, finalBalance=coins.Value,
        realEffect=effectOnServer, itemOwned=ownedOnServer,
        charged=chargedCorrectly, secondClientUnchanged=independentSecondClient,
    })
    return
end
-- A client disconnect must invoke PlayerRemoving and persist profile.
status:FireClient(p, "leave")
deadline = os.clock() + 40
while p.Parent == Players and os.clock() < deadline do task.wait(0.2) end
if p.Parent == Players then
    finish({ok=false, reason="Client did not disconnect"})
    return
end
local key = "Player_" .. tostring(userId)
local store = DataStoreService:GetDataStore("RMM_ExperienceData_v1")
local persisted = nil
deadline = os.clock() + 30
repeat
    task.wait(1)
    local loaded, data = pcall(function() return store:GetAsync(key) end)
    if loaded and data and data.lockToken == nil then
        persisted = data
        break
    end
until os.clock() > deadline
local saved = persisted and persisted.coins == expectedCoins and table.find(persisted.inventory or {}, "speed_boots") ~= nil
finish({
    ok = saved == true,
    client_server = ok and independentSecondClient,
    coin_pickup = beforePurchaseCoins - startingCoins >= 50,
    shop_purchase = chargedCorrectly and effectOnServer and ownedOnServer,
    persisted = saved == true,
    userId = userId,
    coins = expectedCoins,
    reason = saved and "Saved data matched coin/shop state after simulated disconnect" or "Profile save did not roundtrip",
})
