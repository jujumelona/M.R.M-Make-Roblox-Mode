"""Host-owned purchase facade for a shared ship-section authority.

A separately authored part-market service must never write a second ship
ledger or mint parts through the generic upgrade purchases catalog. Its only
state-changing operation delegates to the one verified section builder.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_ship_currency_sections import eligible_currency_ship_sections, _read
from .spec import ModuleKind


def eligible_ship_purchase_facade(module: Any, proposal: Any) -> tuple[str, str, str] | None:
    if (not getattr(module, "module_id", "").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    modules = getattr(proposal, "modules", ())
    owner = next((m for m in modules if m.kind == ModuleKind.SERVER_MODULE
                  and m.name == server), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    # Match intent to pay for and INSTALL a tangible ship part, rather than
    # treating this as a standalone weapon/crew/ship upgrade purchase.
    requirements = (
        r"\b(?:ship|spaceship)\s+assembly\s+state\b",
        r"\bparts?\s+purchas\w*\b",
        r"\b(?:currency|coins?|credits?)\b",
        r"\b(?:validat|check|reject)\w*\b",
        r"\b(?:deduct|charge|spend)\w*\b",
        r"\b(?:owned|owns?|ownership)\b",
        r"\b(?:assembl\w*|install\w*)\b",
        r"\b(?:performance|expansion)\b",
    )
    if not all(re.search(p, prose) for p in requirements):
        return None
    # Exactly one separate builder owns the common saved RMMShipSections state.
    builders = [m for m in modules if m.kind == ModuleKind.SERVER_MODULE
                and m.name != server
                and eligible_currency_ship_sections(m, proposal) is not None]
    if len(builders) != 1:
        return None
    dynamic = getattr(proposal, "game_design", {}).get("dynamic_design") or {}
    routes = [(name, rule) for name, rule in (dynamic.get("host_actions") or {}).items()
              if isinstance(rule, dict) and rule.get("service") == server]
    if len(routes) != 1:
        return None
    remote, route = routes[0]
    max_args = route.get("max_args")
    if (route.get("kind") != "RemoteFunction"
            or (dynamic.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (max_args is not None and (type(max_args) is not int or max_args < 2))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if (not module.file_path.startswith("src/server/")
                or not module.file_path.endswith(".luau")):
            return None
    else:
        if (module.name != server.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (dynamic.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    return server, remote, builders[0].name


def try_ship_purchase_facade(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_ship_purchase_facade(module, proposal)
    if selected is None:
        return None
    _server, remote, builder = selected
    # The physical builder owns the only catalog and all future persistence.
    # This may run before the builder in topological order; _read caches it
    # against the builder's identity and validates cached data on every use.
    slots = _read(proposal, builder, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        return _CLIENT.replace("__REMOTE__", json.dumps(remote))
    rows = ",\n".join(
        "[" + json.dumps(slot["id"] + "/" + option["id"]) + "] = {"
        + "slot = " + json.dumps(slot["id"])
        + ", variant = " + json.dumps(option["id"])
        + ", label = " + json.dumps(slot["label"] + " / " + option["label"], ensure_ascii=False)
        + ", price = " + str(option["cost"])
        + ", performance = " + str(option["performance"]) + "}"
        for slot in slots for option in slot["options"]
    )
    return (_SERVER.replace("__BUILDER__", json.dumps(builder))
            .replace("__PARTS__", rows))


_SERVER = r'''--!strict
-- No separate purchases registry: delegate to the one host section builder.
local Players = game:GetService("Players")
local Service = {}
local BUILDER_NAME = __BUILDER__
local MARKET = {
__PARTS__
}
local function reject(reason)
    return {success = false, reason = reason}
end
local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player")
        and player.Parent == Players
end
local function builderOf(services)
    local builder = services[BUILDER_NAME]
    if type(builder) ~= "table" or type(builder.handleAction) ~= "function" then
        return nil
    end
    return builder
end
function Service.start(services)
    assert(type(services) == "table" and builderOf(services) ~= nil
        and type(services.PlayerDataManager) == "table",
        "Part market must share an existing authoritative ship builder")
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) then return reject("invalid_player") end
    local count = select("#", ...)
    local command, id = ...
    if command == "list" and count == 1 then
        local manager = services.PlayerDataManager
        if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
            return reject("profile_loading")
        end
        local profile = manager.GetState(player, "RMMShipSections")
        local stats = player:FindFirstChild("leaderstats")
        local coins = stats and stats:FindFirstChild("Coins")
        if type(profile) ~= "table" or type(profile.sections) ~= "table"
            or not coins or not coins:IsA("IntValue") or coins.Value < 0 then
            return reject("profile_loading")
        end
        local available = {}
        for key, row in pairs(MARKET) do
            local entry = profile.sections[row.slot]
            table.insert(available, {id = key, label = row.label,
                cost = row.price, performance = row.performance,
                owned = type(entry) == "table" and entry.owned == true})
        end
        table.sort(available, function(a, b) return a.id < b.id end)
        return {success = true, items = available, coins = coins.Value}
    end
    if command == "buy" and count == 2 and type(id) == "string" then
        local part = MARKET[id]
        if not part then return reject("unknown_part") end
        local builder = builderOf(services)
        if not builder then return reject("builder_unavailable") end
        -- One state writer: the builder revalidates the current balance,
        -- owned slot, authoritative price and ship geometry before charging.
        return builder.handleAction(player, services, "create", part.slot, part.variant)
    end
    return reject("invalid_action")
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing host Remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Wrong part-market remote") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipPartMarket"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("ScrollingFrame")
panel.Size = UDim2.fromOffset(315, 345)
panel.Position = UDim2.new(0, 15, 0, 165)
panel.CanvasSize = UDim2.fromOffset(0, 1500)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 48)
status.Text = "Loading ship parts"
status.Parent = panel
local busy = false
local refresh
refresh = function()
    if busy then return end
    busy = true
    local ok, data = pcall(function() return remote:InvokeServer("list") end)
    busy = false
    if not ok or type(data) ~= "table" or data.success ~= true
        or type(data.items) ~= "table" then
        status.Text = "Ship market unavailable"
        return
    end
    status.Text = "Coins: " .. tostring(data.coins)
    for _, child in ipairs(panel:GetChildren()) do
        if child:IsA("TextButton") then child:Destroy() end
    end
    for _, part in ipairs(data.items) do
        local button = Instance.new("TextButton")
        button.Size = UDim2.new(1, 0, 0, 30)
        button.Text = tostring(part.label) .. " (" .. tostring(part.cost) .. ")"
            .. (part.owned and " [Installed]" or "")
        button.Active = not part.owned
        button.Parent = panel
        button.Activated:Connect(function()
            if busy or part.owned then return end
            busy = true
            local success, answer = pcall(function()
                return remote:InvokeServer("buy", part.id)
            end)
            busy = false
            if success and type(answer) == "table" and answer.success == true then
                refresh()
            else
                status.Text = "Rejected: " .. tostring(success
                    and type(answer) == "table" and answer.reason or "network")
            end
        end)
    end
end
refresh()
'''