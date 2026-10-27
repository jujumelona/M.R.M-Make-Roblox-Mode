"""Typed-contract weapon performance compiler; no 9B-authored Luau.

This adapter does not mint a weapon/registry, assume a nonexistent Service,
or trust a client-supplied weapon object. It only upgrades a real equipped or
backpack Tool owned by the authenticated player. Purchased/traded weapons
must actually exist in Roblox before upgrades may be performed.
"""
from __future__ import annotations

import re
from typing import Any
from .spec import ModuleKind


def eligible_owned_weapon_performance(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (module.kind != ModuleKind.SERVER_MODULE
            or not module.module_id.startswith("dyn_")
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    owner = module
    description = owner.description.casefold()
    required = (
        r"\bweapon\b",
        r"\b(?:damage|fire\s*rate|cooldown)\b",
        r"\b(?:registry|server[- ]owned)\b",
        r"\b(?:validat|reject|check)\w*\b",
        r"\b(?:mutat|upgrad|improv|increas)\w*\b",
        r"\b(?:persist|sav|record)\w*\b",
    )
    if not all(re.search(pattern, description) for pattern in required):
        return None
    if not (re.search(r"\b(?:ownership|owned|player|local)\b", description)
            and re.search(r"\b(?:weapon\s+(?:instance|performance)|"
                          r"performance\s+state)\b", description)):
        return None
    dynamic = (proposal.game_design or {}).get("dynamic_design") or {}
    routes = [(key, row) for key, row in (dynamic.get("host_actions") or {}).items()
              if isinstance(row, dict) and row.get("service") == owner.name]
    if len(routes) != 1:
        return None
    remote, action = routes[0]
    if (action.get("kind") != "RemoteFunction" or action.get("max_args") != 1
            or (dynamic.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (dynamic.get("module_remotes") or {}).get(owner.module_id) != [remote]):
        return None
    contract = (dynamic.get("host_typed_actions") or {}).get(remote)
    if (not isinstance(contract, dict)
            or contract.get("transport_only") is not True
            or contract.get("server") != owner.name
            or contract.get("target") not in (None, {"kind": "none"})
            or not isinstance(contract.get("contract"), dict)):
        return None
    pair = owner.name.removesuffix("Server") + "Client"
    if contract.get("client") != pair:
        return None
    clients = [m for m in proposal.modules
               if m.kind == ModuleKind.CLIENT_SCRIPT and m.name == pair
               and m.file_path.startswith("src/client/")
               and m.file_path.endswith(".client.luau")
               and (dynamic.get("module_remotes") or {}).get(m.module_id) == [remote]]
    if len(clients) != 1:
        return None
    manifest = contract["contract"]
    if manifest.get("state_changes") != [] or manifest.get("target") != {"kind": "none"}:
        return None
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 2:
        return None
    try:
        fields = {row["id"]: row for row in inputs}
    except (KeyError, TypeError):
        return None
    if (len(fields) != 2
            or fields["selection"].get("type") != "text"
            or fields["quantity"].get("type") != "integer"
            or fields["quantity"].get("min") != 1
            or fields["quantity"].get("max") != 10000):
        return None
    if not any(m.name == "PlayerDataManager" for m in proposal.modules):
        return None
    return owner.name, remote


def render_owned_weapon_performance(module: Any, proposal: Any) -> str | None:
    selected = eligible_owned_weapon_performance(module, proposal)
    if selected is None:
        return None
    return _SERVER


_SERVER = r'''--!strict
-- Fixed first-party defaults, not prices/levels authored by the model.
-- Player selects a real owned Tool; no remote can send a mutable Instance.
local Players = game:GetService("Players")
local Service = {}
local MAX_LEVEL = 5
local BASE_COST = 25
local COOLDOWN = 0.35
local recent = setmetatable({}, {__mode = "k"})
local function validNumber(value)
    return type(value) == "number" and value == value
        and value % 1 == 0 and value >= 0 and value <= 2147483647
end
local function ownedTool(player, name)
    if type(name) ~= "string" or #name < 1 or #name > 120 then return nil end
    local backpack = player:FindFirstChildOfClass("Backpack")
    local character = player.Character
    for _, container in {backpack, character} do
        if container then
            local tool = container:FindFirstChild(name)
            if tool and tool:IsA("Tool") and tool.Parent == container then
                return tool
            end
        end
    end
    return nil
end
local function setStats(tool, level)
    tool:SetAttribute("RMMWeaponLevel", level)
    tool:SetAttribute("RMMDamageMultiplier", 1 + 0.2 * level)
    tool:SetAttribute("RMMFireRateMultiplier", 1 + 0.1 * level)
    tool:SetAttribute("RMMCooldownMultiplier", 1 / (1 + 0.1 * level))
end
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function",
        "Weapon performance requires persisted owned state")
    Players.PlayerRemoving:Connect(function(player) recent[player] = nil end)
    -- Re-apply persisted stats to actual tools; never spawn free equipment.
    local function bindPlayer(player)
        local saved = services.PlayerDataManager.GetState(player, "RMMWeaponPerformance")
        if type(saved) ~= "table" then return end
        local function refresh(container)
            for _, tool in container:GetChildren() do
                if tool:IsA("Tool") and type(saved[tool.Name]) == "table" then
                    local entry = saved[tool.Name]
                    if validNumber(entry.level) and entry.level <= MAX_LEVEL then
                        setStats(tool, entry.level)
                    end
                end
            end
            container.ChildAdded:Connect(function(tool)
                local entry = saved[tool.Name]
                if tool:IsA("Tool") and type(entry) == "table"
                    and validNumber(entry.level) and entry.level <= MAX_LEVEL then
                    setStats(tool, entry.level)
                end
            end)
        end
        local backpack = player:FindFirstChildOfClass("Backpack")
        if backpack then refresh(backpack) end
        if player.Character then refresh(player.Character) end
        player.CharacterAdded:Connect(refresh)
    end
    if type(services.PlayerDataManager.OnReady) == "function" then
        services.PlayerDataManager.OnReady(bindPlayer)
    end
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_player_or_args"}
    end
    local args = ...
    if type(args) ~= "table" or type(args.selection) ~= "string"
        or args.quantity ~= 1 then
        return {success = false, reason = "invalid_selection_or_quantity"}
    end
    for key in pairs(args) do
        if key ~= "selection" and key ~= "quantity" then
            return {success = false, reason = "unknown_input"}
        end
    end
    local tool = ownedTool(player, args.selection)
    if not tool then return {success = false, reason = "weapon_not_owned"} end
    local now = os.clock()
    if recent[player] and now - recent[player] < COOLDOWN then
        return {success = false, reason = "cooldown"}
    end
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return {success = false, reason = "profile_missing"}
    end
    local saved = manager.GetState(player, "RMMWeaponPerformance")
    local entitlements = manager.GetState(player, "RMMTradeEntitlements")
    if type(saved) ~= "table" or type(entitlements) ~= "table" then
        return {success = false, reason = "profile_not_ready"}
    end
    -- A real Tool alone is not sufficient to buy gameplay power: verify
    -- that the server has also recorded this player's weapon entitlement.
    local licensed = false
    for _, entry in pairs(entitlements) do
        if type(entry) == "table" and entry.purchased == true
            and entry.kind == "weapon"
            and (entry.label == tool.Name or entry.id == tool.Name) then
            licensed = true
            break
        end
    end
    if not licensed then return {success = false, reason = "weapon_not_licensed"} end
    local previous = saved[tool.Name]
    if previous ~= nil and type(previous) ~= "table" then
        return {success = false, reason = "invalid_saved_record"}
    end
    local level = previous and previous.level or 0
    if not validNumber(level) or level >= MAX_LEVEL then
        return {success = false, reason = "max_level_or_corrupted_state"}
    end
    local coinsFolder = player:FindFirstChild("leaderstats")
    local coins = coinsFolder and coinsFolder:FindFirstChild("Coins")
    local price = BASE_COST * (level + 1)
    if not coins or not coins:IsA("IntValue")
        or not validNumber(coins.Value) or coins.Value < price then
        return {success = false, reason = "insufficient_coins"}
    end
    -- Do not yield between checking the item, spending Coins and persisting.
    coins.Value -= price
    saved[tool.Name] = {level = level + 1}
    setStats(tool, level + 1)
    recent[player] = now
    return {success = true, weapon = tool.Name, level = level + 1,
        cost = price, damageMultiplier = tool:GetAttribute("RMMDamageMultiplier")}
end
return Service
'''
