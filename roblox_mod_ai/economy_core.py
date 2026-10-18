"""Host-owned shared economy primitive for generated experiences.

A model must not invent a second incompatible ledger: PlayerDataManager owns
persistence and publishes player.leaderstats.Coins. This ModuleScript owns
synchronous server-authoritative balance mutations; caller scripts may require
it via ServerScriptService.EconomyLedger. This is *not* a complete trading
system, player-to-player escrow, or an engine-playtested implementation.
"""
from __future__ import annotations

from .spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


def is_supported_economy_ledger(module: RobloxModuleSpec) -> bool:
    # Do not replace arbitrary gameplay simply because the word "economy"
    # appears. This adapter covers one narrow first-party ledger contract.
    desc = module.description.lower()
    return (module.module_id.startswith("dyn_")
            and module.name == "EconomyLedger"
            and ("ledger" in desc or "balance" in desc)
            and any(word in desc for word in ("credits", "currency", "coins"))
            and ("server" in desc or "authorit" in desc))


def normalize_economy_ledger(proposal: RobloxProposal) -> bool:
    """Upgrade the known ledger service from an unrequireable Script to a ModuleScript.

    Applies to saved proposals created before the role existed as well as new
    proposals; does not alter feature IDs or author unrequested mechanics.
    """
    if not proposal.game_design.get("dynamic_design"):
        return False
    changed = False
    for module in proposal.modules:
        if not is_supported_economy_ledger(module):
            continue
        # If a model bound a remote directly to its ledger, do not silently
        # discard that handler during conversion.
        owners = (proposal.game_design["dynamic_design"].get("module_remotes") or {})
        if owners.get(module.module_id):
            continue
        if module.file_path == "src/server/EconomyLedger.server.luau":
            module.file_path = "src/server/EconomyLedger.luau"
            module.kind = ModuleKind.SHARED_MODULE
            module.roblox_service = RobloxService.SERVER_SCRIPT_SERVICE
            module.depends_on = []
            changed = True
    return changed


def render_economy_ledger(module: RobloxModuleSpec) -> str:
    if not is_supported_economy_ledger(module):
        raise ValueError("No inspected first-party EconomyLedger behavior match")
    if module.file_path != "src/server/EconomyLedger.luau":
        raise ValueError("EconomyLedger must be a server ModuleScript (.luau)")
    return '''--!strict
-- First-party server-only balance API. PlayerDataManager persists leaderstats.Coins.
-- Use require(game:GetService("ServerScriptService"):WaitForChild("EconomyLedger"))
local Players = game:GetService("Players")

local EconomyLedger = {}

local function getCoins(player: Player): IntValue?
    if typeof(player) ~= "Instance" or not player:IsA("Player") then
        return nil
    end
    if player.Parent ~= Players then
        return nil
    end
    local stats = player:FindFirstChild("leaderstats")
    local coins = nil
    if stats then
        coins = stats:FindFirstChild("Coins")
    end
    if coins and coins:IsA("IntValue") then
        return coins
    end
    return nil
end

local function validAmount(amount: number): boolean
    return type(amount) == "number"
        and amount == amount
        and amount >= 0
        and amount < math.huge
        and amount % 1 == 0
end

function EconomyLedger.GetBalance(player: Player): number?
    local coins = getCoins(player)
    if coins then
        return coins.Value
    end
    return nil
end

-- All balance changes are server-side synchronous and cannot yield.
-- No client-supplied price or reward may be trusted by the calling service.
function EconomyLedger.TrySpend(player: Player, amount: number): boolean
    if not validAmount(amount) then
        return false
    end
    local coins = getCoins(player)
    if not coins or coins.Value < amount then
        return false
    end
    coins.Value -= amount
    return true
end

function EconomyLedger.Grant(player: Player, amount: number): boolean
    if not validAmount(amount) then
        return false
    end
    local coins = getCoins(player)
    if not coins or amount > 2147483647 - coins.Value then
        return false
    end
    coins.Value += amount
    return true
end

-- Convenience for refunding a failed purchase; same validated server rules.
EconomyLedger.Refund = EconomyLedger.Grant

return EconomyLedger
'''
