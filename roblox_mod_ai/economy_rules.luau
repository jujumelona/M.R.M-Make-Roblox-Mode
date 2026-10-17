--!strict
-- Roblox-independent economy checks shared by the game and Lune tests.
local EconomyRules = {}

function EconomyRules.canAfford(balance: number, price: number): boolean
    if type(balance) ~= "number" or type(price) ~= "number" then return false end
    if balance ~= balance or price ~= price then return false end
    if price < 1 or math.floor(price) ~= price then return false end
    if balance < 0 or math.floor(balance) ~= balance then return false end
    return balance >= price
end

function EconomyRules.charge(balance: number, price: number): number?
    if not EconomyRules.canAfford(balance, price) then return nil end
    return balance - price
end

return EconomyRules
