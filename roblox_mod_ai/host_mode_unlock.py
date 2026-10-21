"""Declarative, profile-backed conditional game-mode switching.

The model supplies only bounded unlock criteria; the host owns authority,
state transitions, remote ABI, and UI. A mode switch is not a launch/teleport:
an independently verified flight state must already be present.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind


_SCHEMA = {
    "type": "object",
    "properties": {
        "minimumCoins": {"type": "integer"},
        "minimumOwnedParts": {"type": "integer"},
        "minimumPurchasedUpgrades": {"type": "integer"},
    },
    "required": ["minimumCoins", "minimumOwnedParts", "minimumPurchasedUpgrades"],
}


def eligible_mode_unlock(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not getattr(module, "module_id", "").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    modules = getattr(proposal, "modules", ())
    owner = next((m for m in modules if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    # Match a complete authored unlock/return state contract, not a particular
    # prompt, module name, hash or the accidental order of generated modules.
    required = (
        r"\bspace[- ]mode\s+state\b",
        r"\bunlock\s+threshold\b",
        r"\b(?:game\s+)?currency\b",
        r"\b(?:ship|spaceship)\s+upgrades?\b",
        r"\b(?:ground|surface)\b",
        r"\b(?:return|restore)\b",
        r"\b(?:validat|reject)\w*\b",
        r"\b(?:server[- ]authoritative|server\s+owns|server\s+records)\b",
    )
    if not all(re.search(expression, prose) for expression in required):
        return None
    # Authored upstream sources must be present, though their state ABI is not
    # assumed to be verified merely because their descriptions look plausible.
    def describes_source(regex: str) -> bool:
        return any(m.kind == ModuleKind.SERVER_MODULE and m.name != server
                   and re.search(regex, m.description.casefold()) is not None
                   for m in modules)
    if (not describes_source(r"\b(?:ship|spaceship).{0,150}(?:parts?|assembly|builder)\b")
            or not describes_source(r"\b(?:upgrade|purchase)\w*.{0,180}\b(?:ship|spaceship|weapon)\b")
            or not describes_source(r"\b(?:launch|depart)\w*.{0,160}\bspace\b")):
        return None
    dynamic = proposal.game_design.get("dynamic_design") or {}
    routes = [(name, rule) for name, rule in (dynamic.get("host_actions") or {}).items()
              if isinstance(rule, dict) and rule.get("service") == server]
    if len(routes) != 1:
        return None
    remote, rule = routes[0]
    maximum = rule.get("max_args")
    if (rule.get("kind") != "RemoteFunction"
            or (dynamic.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (maximum is not None and (type(maximum) is not int or maximum < 1))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
            return None
    else:
        if (not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (dynamic.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    return server, remote


def _validate(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("MODE_UNLOCK_RULES_NOT_OBJECT")
    limits = {"minimumCoins": (1, 1000000),
              "minimumOwnedParts": (1, 8),
              "minimumPurchasedUpgrades": (1, 8)}
    rules = {}
    for key, (minimum, maximum) in limits.items():
        value = raw.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("MODE_UNLOCK_INVALID_" + key)
        rules[key] = value
    return rules


def _read(proposal: Any, server: str, router: Any) -> dict[str, int]:
    saved = proposal.game_design.setdefault("_host_mode_unlock_rules", {})
    if server in saved:
        return _validate(saved[server])
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("HOST_MODE_UNLOCK_MISSING_RULES")
    description = next(m.description for m in proposal.modules if m.name == server)
    prompt = (
        "Return ONLY JSON {minimumCoins,minimumOwnedParts,minimumPurchasedUpgrades}. "
        "Pick positive unlock criteria: coins 1-1000000, owned ship parts 1-8, "
        "purchased ship/weapon/crew upgrades 1-8. This defines a game's rules, "
        "NOT source code. The host will check real server-owned saved profiles "
        "and will NEVER invent a built ship or a completed flight. "
        "Do not output any Luau, Roblox APIs, code, wallet mutations, or claims "
        "about DataStore or launch behavior. Authored design: " + description[:1100]
    )
    diagnostic = ""
    for _ in range(2):
        try:
            answer = router.complete_json(
                prompt + ("\nRule error: " + diagnostic if diagnostic else ""),
                role="planner", temperature=0.0, max_tokens=350, json_schema=_SCHEMA,
            )
            result = _validate(answer)
            saved[server] = result
            return result
        except Exception as exc:
            diagnostic = str(exc)[:230]
    raise ValueError("HOST_MODE_UNLOCK_RULE_EXHAUSTED: " + diagnostic)


def try_mode_unlock(module: Any, proposal: Any, router: Any = None) -> str | None:
    route = eligible_mode_unlock(module, proposal)
    if route is None:
        return None
    server, remote = route
    rules = _read(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        return _CLIENT.replace("__REMOTE__", json.dumps(remote))
    return (_SERVER.replace("__COINS__", str(rules["minimumCoins"]))
            .replace("__PARTS__", str(rules["minimumOwnedParts"]))
            .replace("__UPGRADES__", str(rules["minimumPurchasedUpgrades"])))


_SERVER = r'''--!strict
-- Mode state only. This cannot launch, teleport, fabricate parts or grant coins.
local Players = game:GetService("Players")
local Service = {}
local MIN_COINS = __COINS__
local MIN_PARTS = __PARTS__
local MIN_UPGRADES = __UPGRADES__
local MODE = "Space Mode"
local GROUND = "Ground"
local LIMIT = 2147483647

local function inspect(player, manager)
    local mode = manager.GetState(player, "RMMGameMode")
    local flight = manager.GetState(player, "RMMTravelProgress")
    local ship = manager.GetState(player, "RMMShipSections")
    local upgrades = manager.GetState(player, "RMMUpgradePurchases")
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if type(mode) ~= "table" or type(flight) ~= "table" or
        type(ship) ~= "table" or type(upgrades) ~= "table" or
        not coins or not coins:IsA("IntValue") or coins.Value < 0
        or coins.Value > LIMIT then
        return {success = false, reason = "profile_unavailable"}
    end
    local parts = 0
    if type(ship.sections) == "table" then
        for _, part in pairs(ship.sections) do
            if type(part) == "table" and part.owned == true then parts += 1 end
        end
    end
    local purchased = 0
    for _, record in pairs(upgrades) do
        if type(record) == "table" and record.owned == true then purchased += 1 end
    end
    local eligible = coins.Value >= MIN_COINS and parts >= MIN_PARTS
        and purchased >= MIN_UPGRADES
    local active = mode.activeMode == MODE and flight.inSpace == true
    return {success = true, currentMode = active and MODE or GROUND,
        eligible = eligible, currency = coins.Value, parts = parts,
        upgrades = purchased, requiredCoins = MIN_COINS,
        requiredParts = MIN_PARTS, requiredUpgrades = MIN_UPGRADES,
        flightConfirmed = flight.inSpace == true,
        mode = mode, flight = flight}
end
local function publicStatus(value)
    return {success = value.success, reason = value.reason,
        currentMode = value.currentMode, eligible = value.eligible,
        currency = value.currency, parts = value.parts, upgrades = value.upgrades,
        requiredCoins = value.requiredCoins, requiredParts = value.requiredParts,
        requiredUpgrades = value.requiredUpgrades,
        flightConfirmed = value.flightConfirmed}
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Mode requires session-locked saved state")
    services.PlayerDataManager.OnReady(function(player)
        local result = inspect(player, services.PlayerDataManager)
        if result.success then
            player:SetAttribute("RMMActiveGameMode", result.currentMode)
            player:SetAttribute("RMMModeUnlocked", result.eligible)
        end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_request"}
    end
    local action = ...
    if action ~= "status" and action ~= "enter" and action ~= "return" then
        return {success = false, reason = "invalid_action"}
    end
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return {success = false, reason = "profile_unavailable"}
    end
    local state = inspect(player, manager)
    if not state.success then return publicStatus(state) end
    if action == "status" then return publicStatus(state) end
    if action == "enter" then
        if not state.eligible then
            return {success = false, reason = "ship_not_unlocked"}
        end
        -- Only a launch service can set the flight ledger. Entering a mode
        -- NEVER fakes this proof or moves the character.
        if not state.flightConfirmed then
            return {success = false, reason = "launch_not_confirmed"}
        end
        if state.mode.activeMode == MODE then
            return {success = false, reason = "already_in_mode"}
        end
        state.mode.activeMode = MODE
    else
        -- Return flight must already have been completed by the travel owner.
        if state.mode.activeMode ~= MODE then
            return {success = false, reason = "not_in_mode"}
        end
        if state.flightConfirmed then
            return {success = false, reason = "return_flight_not_confirmed"}
        end
        state.mode.activeMode = GROUND
    end
    local result = inspect(player, manager)
    player:SetAttribute("RMMActiveGameMode", result.currentMode)
    player:SetAttribute("RMMModeUnlocked", result.eligible)
    return publicStatus(result)
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local folder = ReplicatedStorage:WaitForChild("Remotes", 20)
if not folder then error("Missing declared Remotes") end
local remote = folder:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Invalid mode remote") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMModeUnlockPanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(295, 177)
panel.Position = UDim2.new(1, -310, 0, 130)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local label = Instance.new("TextLabel")
label.Size = UDim2.fromOffset(290, 70)
label.TextWrapped = true
label.Text = "Mode status loading"
label.Parent = panel
local busy = false
local function request(kind)
    if busy then return end
    busy = true
    local ok, response = pcall(function() return remote:InvokeServer(kind) end)
    busy = false
    if not ok or type(response) ~= "table" then
        label.Text = "Mode server unavailable"
        return
    end
    if response.success == true then
        label.Text = tostring(response.currentMode) .. " | Coins " ..
            tostring(response.currency) .. "/" .. tostring(response.requiredCoins) ..
            " | Parts " .. tostring(response.parts) .. "/" ..
            tostring(response.requiredParts) .. " | Upgrades " ..
            tostring(response.upgrades) .. "/" .. tostring(response.requiredUpgrades)
    else
        label.Text = "Mode request rejected: " .. tostring(response.reason)
    end
end
for _, kind in {"status", "enter", "return"} do
    local button = Instance.new("TextButton")
    button.Name = kind
    button.Text = kind
    button.Size = UDim2.fromOffset(280, 33)
    button.Parent = panel
    button.Activated:Connect(function() request(kind) end)
end
request("status")
'''