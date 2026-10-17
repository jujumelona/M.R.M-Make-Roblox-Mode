--!strict
-- Actual standalone Luau execution via Lune; no Roblox DataModel required.
local EconomyRules = require("../roblox_mod_ai/economy_rules")
assert(EconomyRules.canAfford(50, 50) == true)
assert(EconomyRules.canAfford(49, 50) == false)
assert(EconomyRules.canAfford(-10, 5) == false)
assert(EconomyRules.canAfford(100, -25) == false)
assert(EconomyRules.canAfford(1, 0) == false)
assert(EconomyRules.canAfford(100, math.huge) == false)
assert(EconomyRules.canAfford(100, 0 / 0) == false)
assert(EconomyRules.canAfford(10.5, 5) == false)
assert(EconomyRules.charge(75, 50) == 25)
assert(EconomyRules.charge(0, 50) == nil)
print("LUNE ECONOMY TESTS PASSED")
