--!strict
-- Execute actual first-party generated EconomyLedger Luau in Lune.
-- Mock only Roblox engine objects; the ledger source is NOT a fake.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local process = require("@lune/process")

local file = process.env.RMM_ECONOMY_SOURCE
assert(type(file) == "string" and #file > 0, "Missing RMM_ECONOMY_SOURCE")
local source = fs.readFile(file)
assert(#source > 100, "Ledger source missing")

local players = {}
local otherParent = {}
local gameMock = {}
function gameMock:GetService(name)
    assert(name == "Players", "Unexpected Roblox service " .. tostring(name))
    return players
end
local function typeOf(value)
    if type(value) == "table" and value.__robloxInstance == true then
        return "Instance"
    end
    return type(value)
end

local environment = {game = gameMock, typeof = typeOf}
local ledger = luau.load(source, {
    environment = environment, injectGlobals = true
})()
assert(type(ledger) == "table")
assert(type(ledger.TrySpend) == "function")
assert(type(ledger.Grant) == "function")
assert(type(ledger.GetBalance) == "function")

local coins = {__robloxInstance = true, Value = 100}
function coins:IsA(kind)
    return kind == "IntValue"
end
local stats = {__robloxInstance = true}
function stats:FindFirstChild(name)
    if name == "Coins" then return coins end
    return nil
end
local player = {__robloxInstance = true, Parent = players}
function player:IsA(kind)
    return kind == "Player"
end
function player:FindFirstChild(name)
    if name == "leaderstats" then return stats end
    return nil
end

-- Every mutation has to fail one of the checks below.
assert(ledger.GetBalance(player) == 100, "Initial balance")
assert(ledger.TrySpend(player, 45), "Valid purchase rejected")
assert(coins.Value == 55, "Valid purchase must deduct exactly once")
assert(not ledger.TrySpend(player, 56), "Insufficient funds must reject")
assert(coins.Value == 55, "Insufficient funds must not deduct")
assert(ledger.Grant(player, 60), "Valid reward rejected")
assert(coins.Value == 115, "Reward must credit correct value")
assert(ledger.Refund(player, 5), "Refund should be supported")
assert(coins.Value == 120)

for _, badAmount in {-1, 0.5, math.huge, -math.huge, 0 / 0, "10", {}} do
    assert(not ledger.Grant(player, badAmount), "Invalid reward amount accepted")
    assert(not ledger.TrySpend(player, badAmount), "Invalid spend amount accepted")
    assert(coins.Value == 120, "Invalid input mutated balance")
end

local stranger = {__robloxInstance = true, Parent = otherParent}
function stranger:IsA(kind) return kind == "Player" end
function stranger:FindFirstChild(name) return stats end
assert(not ledger.Grant(stranger, 10), "Outside player rewarded")
assert(not ledger.TrySpend(stranger, 10), "Outside player charged")
assert(ledger.GetBalance(stranger) == nil)
assert(coins.Value == 120)

player.Parent = otherParent
assert(not ledger.Grant(player, 1), "Disconnected player rewarded")
player.Parent = players
coins.Value = 2147483645
assert(not ledger.Grant(player, 3), "IntValue overflow must reject")
assert(coins.Value == 2147483645, "Overflow changed balance")
assert(ledger.Grant(player, 2), "Boundary-value reward should pass")
assert(coins.Value == 2147483647)
assert(not ledger.Grant(player, 1), "Over maximum IntValue boundary")
assert(coins.Value == 2147483647)
print("ECONOMY E2E PASS: actual Luau ledger prevents overspend, forged player, bad amount, overflow")
