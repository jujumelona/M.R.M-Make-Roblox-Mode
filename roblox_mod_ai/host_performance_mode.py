"""Host-owned server performance gate for a declarative game mode transition.

The gate derives the numeric threshold from the *accepted module contract*,
never from a particular game prompt or module hash. Client-supplied performance
and currency cannot unlock a mode. It only transitions saved mode state;
actual flight/teleport remains owned by the separate travel service.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind

_MODE = re.compile(r"\b([a-z][a-z0-9_-]{1,22})[- ]mode\s+state\s+machine\b", re.I)
_POWER = re.compile(
    r"\b(?:ship|spaceship|vessel)(?:'s)?\s+performance\s+"
    r"(?:value|score|rating)?\s*(?:is\s+)?(?:at\s+least|>=|minimum(?:\s+of)?)\s*(\d+)\b",
    re.I,
)
_OTHER_POWER = re.compile(
    r"\bperformance\s+(?:value|score|rating)\s+(?:is\s+)?"
    r"(?:at\s+least|>=|minimum(?:\s+of)?)\s*(\d+)\b", re.I,
)


def eligible_performance_mode(module: Any, proposal: Any) -> tuple[str, str, int, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    mode_match = _MODE.search(prose)
    power_match = _POWER.search(prose) or _OTHER_POWER.search(prose)
    if (not mode_match or not power_match
            or not re.search(r"\b(?:enter|transition|switch)\w*\b", prose)
            or not re.search(r"\b(?:server[- ]authoritative|server[- ]owned)\b", prose)
            or not re.search(r"\breject\w*\b", prose)):
        return None
    threshold = int(power_match.group(1))
    if not 1 <= threshold <= 100000:
        return None
    # A performance gate without an authored ship builder is not a real game
    # dependency. Do not invent progression or a free starter performance.
    ship_sources = [
        m for m in getattr(proposal, "modules", [])
        if m is not owner and m.kind == ModuleKind.SERVER_MODULE
        and re.search(r"\b(?:ship|spaceship|vessel)\s+(?:assembly|construction|build)\b",
                      m.description.casefold())
        and re.search(r"\bparts?\b|\bsections?\b", m.description.casefold())
    ]
    if not ship_sources:
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(name, val) for name, val in (design.get("host_actions") or {}).items()
              if isinstance(val, dict) and val.get("service") == server]
    if (len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(routes[0][0]) != "RemoteFunction"
            or (routes[0][1].get("max_args") is not None
                and (type(routes[0][1]["max_args"]) is not int
                     or routes[0][1]["max_args"] < 1))):
        return None
    remote = routes[0][0]
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
            return None
    else:
        if not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    mode = mode_match.group(1).replace("_", "-").replace("-", " ").title() + " Mode"
    return server, remote, threshold, mode


def render_host_performance_mode(module: Any, proposal: Any) -> str | None:
    selected = eligible_performance_mode(module, proposal)
    if selected is None:
        return None
    _server, remote, threshold, mode = selected
    if module.kind == ModuleKind.SERVER_MODULE:
        return (_SERVER.replace("__THRESHOLD__", str(threshold))
                .replace("__MODE__", json.dumps(mode)))
    return (_CLIENT.replace("__REMOTE__", json.dumps(remote))
            .replace("__THRESHOLD__", str(threshold))
            .replace("__MODE__", json.dumps(mode)))


_SERVER = r'''--!strict
-- Server-only mode transition. Never trust the client for ship power or Coins.
local Players = game:GetService("Players")
local Service = {}
local REQUIRED_PERFORMANCE = __THRESHOLD__
local MODE = __MODE__
local MAX_VALUE = 2147483647

local function finiteNonnegative(value)
    return type(value) == "number" and value == value
        and value ~= math.huge and value >= 0 and value <= MAX_VALUE
end

local function verifiedShipPerformance(player, manager)
    local saved = manager.GetState(player, "RMMShipSections")
    local classic = manager.GetState(player, "RMMShipBuild")
    if not saved or not classic then return nil, "profile_loading" end
    local count, fromProfile = 0, 0
    if type(saved.sections) == "table" then
        for _, part in pairs(saved.sections) do
            if type(part) == "table" and part.owned == true then
                count += 1
                local contribution = part.performance
                if finiteNonnegative(contribution) and contribution % 1 == 0 then
                    fromProfile = math.min(MAX_VALUE, fromProfile + contribution)
                end
            end
        end
    end
    if type(classic.sections) == "table" then
        for _, part in pairs(classic.sections) do
            if part == true then count += 1 end
        end
    end
    if count == 0 then return nil, "ship_not_built" end
    -- Host ship catalog/assembly code publishes these player attributes from
    -- real server-owned installed parts. Client input is never accepted.
    local published = player:GetAttribute("RMMShipPerformance")
    local assembly = player:GetAttribute("RMMShipAssemblyPerformance")
    local score = fromProfile
    if finiteNonnegative(published) and published % 1 == 0 then
        score = math.max(score, published)
    end
    if finiteNonnegative(assembly) and assembly % 1 == 0 then
        score = math.max(score, assembly)
    end
    if score == 0 then return nil, "ship_performance_unavailable" end
    return score, nil
end

local function status(player, manager)
    local state = manager.GetState(player, "RMMGameMode")
    if not state then return {success = false, reason = "profile_loading"} end
    local score, reason = verifiedShipPerformance(player, manager)
    local unlocked = score ~= nil and score >= REQUIRED_PERFORMANCE
    local active = unlocked and state.currentMode == MODE
    player:SetAttribute("RMMModeRequiredPerformance", REQUIRED_PERFORMANCE)
    player:SetAttribute("RMMModeShipPerformance", score or 0)
    player:SetAttribute("RMMModeUnlocked", unlocked)
    player:SetAttribute("RMMActiveGameMode", active and MODE or "Surface")
    local coins = player:FindFirstChild("leaderstats")
    local balance = coins and coins:FindFirstChild("Coins")
    return {
        success = true,
        currentMode = active and MODE or "Surface",
        performance = score or 0,
        requiredPerformance = REQUIRED_PERFORMANCE,
        currency = balance and balance:IsA("IntValue") and balance.Value or nil,
        unlocked = unlocked,
        reason = reason,
    }
end

function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.OnReady) == "function"
        and type(services.PlayerDataManager.GetState) == "function",
        "Ship-gated mode needs authoritative host profile")
    services.PlayerDataManager.OnReady(function(player)
        status(player, services.PlayerDataManager)
    end)
end

function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_request"}
    end
    local request = ...
    if request ~= "enter" and request ~= "status" then
        return {success = false, reason = "invalid_action"}
    end
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return {success = false, reason = "profile_unavailable"}
    end
    local before = status(player, manager)
    if request == "status" or before.success ~= true then return before end
    if not before.unlocked then
        return {
            success = false,
            reason = before.reason or "insufficient_ship_performance",
            performance = before.performance,
            requiredPerformance = REQUIRED_PERFORMANCE,
        }
    end
    local state = manager.GetState(player, "RMMGameMode")
    if type(state) ~= "table" then
        return {success = false, reason = "profile_loading"}
    end
    if state.currentMode == MODE then
        return {success = false, reason = "already_in_mode"}
    end
    state.currentMode = MODE
    local result = status(player, manager)
    result.transitioned = result.currentMode == MODE
    return result
end

-- This mode is a gameplay state, not a launch/teleport authorization.
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing declared Remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Wrong mode remote") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipModeGate"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(290, 135)
panel.Position = UDim2.new(1, -310, 0, 185)
panel.Parent = gui
local statusText = Instance.new("TextLabel")
statusText.Size = UDim2.fromOffset(275, 72)
statusText.Text = "Checking ship performance..."
statusText.Parent = panel
local button = Instance.new("TextButton")
button.Size = UDim2.fromOffset(275, 38)
button.Position = UDim2.fromOffset(0, 76)
button.Text = "Enter " .. __MODE__
button.Parent = panel
local busy = false
local function display(answer)
    if type(answer) ~= "table" then
        statusText.Text = "Mode status unavailable"
        return
    end
    local level = tonumber(answer.performance) or 0
    local required = tonumber(answer.requiredPerformance) or __THRESHOLD__
    statusText.Text = "Mode: " .. tostring(answer.currentMode or "Surface")
        .. " | Ship: " .. tostring(level) .. "/" .. tostring(required)
        .. (answer.reason and " | " .. tostring(answer.reason) or "")
    button.Active = answer.unlocked == true
        and answer.currentMode ~= __MODE__
end
local function call(action)
    if busy then return end
    busy = true
    local ok, response = pcall(function() return remote:InvokeServer(action) end)
    busy = false
    if ok then display(response)
    else statusText.Text = "Server unavailable"; button.Active = false end
end
button.Activated:Connect(function() call("enter") end)
player:GetAttributeChangedSignal("RMMModeShipPerformance"):Connect(function()
    local score = player:GetAttribute("RMMModeShipPerformance")
    if type(score) == "number" then
        statusText.Text = "Ship performance: " .. tostring(score) .. "/" .. tostring(__THRESHOLD__)
    end
end)
-- Builder/upgrade services change only server-owned attributes; refresh the
-- validated mode state when real installed-part performance changes.
player:GetAttributeChangedSignal("RMMShipPerformance"):Connect(function()
    task.defer(function() call("status") end)
end)
player:GetAttributeChangedSignal("RMMShipAssemblyPerformance"):Connect(function()
    task.defer(function() call("status") end)
end)
task.defer(function() call("status") end)
'''