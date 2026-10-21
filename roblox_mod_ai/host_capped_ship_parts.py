"""A generic host builder for capped ship-part assembly paid in earned Coins.

This contract is neither resource-crafted ship sections nor upgraded fixed ship
slots. The small model returns only a short static parts catalog with a cap.
The host owns inventory, Coins, atomic install, persistent part count, world
instances and client-visible server-confirmed results.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_catalog_purchase import _ID
from .spec import ModuleKind

_SCHEMA = {
    "type": "object",
    "properties": {
        "maxParts": {"type": "integer"},
        "parts": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "label": {"type": "string"},
                           "cost": {"type": "integer"}},
            "required": ["id", "label", "cost"],
        }},
    },
    "required": ["maxParts", "parts"],
}


def eligible_capped_ship_parts(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if not owner:
        return None
    desc = owner.description.casefold()
    if (not re.search(r"\b(?:ship|spaceship|vessel)\s+assembly\b", desc)
            or not re.search(r"\bmodular parts?\b|\bpart types?\b", desc)
            or not re.search(r"\bpart cap\b|\bmaximum part count\b", desc)
            or not re.search(r"\b(?:currency|coins?|credits?)\b", desc)
            or not re.search(r"\b(?:deduct|spend|cost)\w*\b", desc)
            or not re.search(r"\b(?:validat|check|reject)\w*\b", desc)):
        return None
    # A scoped route must be explicitly wired and unambiguous.
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(k, v) for k, v in (design.get("host_actions") or {}).items()
              if isinstance(v, dict) and v.get("service") == server]
    if (len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction"
            or routes[0][1].get("max_args") == 0
            or (design.get("remotes") or {}).get(routes[0][0]) != "RemoteFunction"):
        return None
    remote = routes[0][0]
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if (not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    return server, remote


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Capped parts requires JSON object")
    rows, limit = data.get("parts"), data.get("maxParts")
    if (type(limit) is not int or not 1 <= limit <= 8
            or not isinstance(rows, list) or not limit <= len(rows) <= 8):
        raise ValueError("Capped ship catalog needs 1-8 parts and feasible cap")
    output, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Capped ship part must be a JSON record")
        part_id, label, cost = row.get("id"), row.get("label"), row.get("cost")
        if (not isinstance(part_id, str) or not _ID.fullmatch(part_id)
                or part_id.casefold() in seen
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 48
                or type(cost) is not int or not 1 <= cost <= 1000000):
            raise ValueError("Capped part requires safe ID, label and positive coin cost")
        seen.add(part_id.casefold())
        output.append({"id": part_id, "label": label.strip(), "cost": cost})
    return {"maxParts": limit, "parts": output}


def _read(proposal: Any, owner: str, router: Any) -> dict[str, Any]:
    cache = proposal.game_design.setdefault("_host_capped_ship_parts", {})
    if owner in cache:
        return _validate(cache[owner])
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("Part types/cap cannot be invented by host")
    server = next(m for m in proposal.modules if m.name == owner)
    prompt = (
        "Return ONLY JSON {maxParts:integer,parts:[{id,label,cost}]}. "
        "Max 8 parts, maxParts 1-8 and no greater than number of parts. "
        "Each part is a selectable, distinct spacecraft component with a "
        "fixed positive cost in real earned Coins. ID is a short ASCII "
        "identifier. No Luau, player API, data stores, remotes, game name or "
        "unbounded quantities. The host owns the full install transaction. "
        "Game's actual construction requirement: " + server.description[:1000]
    )
    last = ""
    for _ in range(2):
        try:
            data = router.complete_json(prompt + ("\nInvalid JSON data: " + last if last else ""),
                                        role="planner", temperature=0, max_tokens=800,
                                        json_schema=_SCHEMA)
            catalog = _validate(data)
            cache[owner] = catalog
            return catalog
        except Exception as exc:
            last = str(exc)[:240]
    raise ValueError("HOST_CAPPED_SHIP_PARTS_EXHAUSTED: " + last)


def try_capped_ship_parts(module: Any, proposal: Any, router: Any = None) -> str | None:
    found = eligible_capped_ship_parts(module, proposal)
    if found is None:
        return None
    owner, remote = found
    catalog = _read(proposal, owner, router)
    rows = catalog["parts"]
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        lua = ",\n".join("{id = " + json.dumps(x["id"]) +
                         ", label = " + json.dumps(x["label"], ensure_ascii=False) +
                         ", cost = " + str(x["cost"]) + "}" for x in rows)
        return (_CLIENT.replace("__REMOTE__", json.dumps(remote))
                .replace("__PARTS__", lua))
    lua = ",\n".join("[" + json.dumps(x["id"]) + "] = {cost = " +
                     str(x["cost"]) + ", position = " + str(i + 1) + "}"
                     for i, x in enumerate(rows))
    return (_SERVER.replace("__PARTS__", lua)
            .replace("__CAP__", str(catalog["maxParts"])))


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local PARTS = {
__PARTS__
}
local MAX_PARTS = __CAP__
local sessions = {}
local usedLots = {}
local lots = {}
local MAX_COINS = 2147483647

local function getShip(player)
    local folder = workspace:FindFirstChild("RMMPlayerShips")
    if not folder then
        folder = Instance.new("Folder")
        folder.Name = "RMMPlayerShips"
        folder.Parent = workspace
    end
    local name = "RMMShip_" .. tostring(player.UserId)
    local ship = folder:FindFirstChild(name)
    if ship and not ship:IsA("Model") then return nil end
    if not ship then
        ship = Instance.new("Model")
        ship.Name = name
        ship:SetAttribute("OwnerUserId", player.UserId)
        ship.Parent = folder
    end
    if ship:GetAttribute("OwnerUserId") ~= player.UserId then return nil end
    local parts = ship:FindFirstChild("CappedShipParts")
    if parts and not parts:IsA("Folder") then return nil end
    if not parts then
        parts = Instance.new("Folder")
        parts.Name = "CappedShipParts"
        parts.Parent = ship
    end
    sessions[player] = ship
    local anchor = ship:FindFirstChild("AssemblyAnchor")
    if anchor and not anchor:IsA("BasePart") then return nil end
    if not anchor then
        local lot = lots[player]
        if lot == nil then
            lot = 0
            while usedLots[lot] do lot += 1 end
            usedLots[lot] = true
            lots[player] = lot
        end
        anchor = Instance.new("Part")
        anchor.Name = "AssemblyAnchor"
        anchor.Anchored = true
        anchor.Size = Vector3.new(7, 1, 7)
        anchor.Position = Vector3.new(25 + (lot % 10) * 24, 2,
            40 + math.floor(lot / 10) * 25)
        anchor.Parent = ship
    end
    return ship, anchor, parts
end
local function countInstalled(sections)
    local count, totalCost = 0, 0
    for id, definition in pairs(PARTS) do
        local state = sections[id]
        if type(state) == "table" and state.owned == true then
            count += 1
            totalCost += definition.cost
        end
    end
    return count, totalCost
end
local function publish(player, sections)
    local count, totalCost = countInstalled(sections)
    player:SetAttribute("RMMShipPartCount", count)
    player:SetAttribute("RMMShipPartTotalCost", totalCost)
    return count, totalCost
end
local function installWorld(folder, anchor, id)
    if folder:FindFirstChild(id) then return end
    local d = PARTS[id]
    if not d then return end
    local part = Instance.new("Part")
    part.Name = id
    part.Anchored = true
    part.Size = Vector3.new(4, 2, 6)
    part.Position = anchor.Position + Vector3.new(d.position * 5, 4, 0)
    part.Parent = folder
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Ship purchase requires a real persistent profile")
    services.PlayerDataManager.OnReady(function(player)
        local state = services.PlayerDataManager.GetState(player, "RMMShipSections")
        if not state then return end
        if state.sections == nil then state.sections = {} end
        if type(state.sections) ~= "table" then return end
        local ship, anchor, parts = getShip(player)
        if not ship or not anchor or not parts then return end
        for id in pairs(PARTS) do
            local owned = state.sections[id]
            if type(owned) == "table" and owned.owned == true then
                installWorld(parts, anchor, id)
            end
        end
        publish(player, state.sections)
    end)
    Players.PlayerRemoving:Connect(function(player)
        local ship = sessions[player]
        if ship then
            local parts = ship:FindFirstChild("CappedShipParts")
            if parts then parts:Destroy() end
        end
        sessions[player] = nil
        if lots[player] ~= nil then
            usedLots[lots[player]] = nil
            lots[player] = nil
        end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_request"}
    end
    local id = ...
    if type(id) ~= "string" or not PARTS[id] then
        return {success = false, reason = "invalid_part"}
    end
    local state = services.PlayerDataManager.GetState(player, "RMMShipSections")
    if not state then return {success = false, reason = "profile_loading"} end
    if state.sections == nil then state.sections = {} end
    if type(state.sections) ~= "table" then
        return {success = false, reason = "invalid_state"}
    end
    local count = countInstalled(state.sections)
    if count >= MAX_PARTS then
        return {success = false, reason = "part_cap"}
    end
    if state.sections[id] ~= nil then
        return {success = false, reason = "already_owned"}
    end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    local price = PARTS[id].cost
    if not coins or not coins:IsA("IntValue") or coins.Value < price
        or coins.Value < 0 or coins.Value > MAX_COINS then
        return {success = false, reason = "insufficient_currency"}
    end
    local ship, anchor, parts = getShip(player)
    if not ship or not anchor or not parts then
        return {success = false, reason = "ship_unavailable"}
    end
    -- No yield from rechecking balance to committed profile and world changes.
    coins.Value -= price
    state.sections[id] = {owned = true, level = 1, cost = price}
    installWorld(parts, anchor, id)
    local newCount, total = publish(player, state.sections)
    return {success = true, id = id, coins = coins.Value,
        count = newCount, totalCost = total, maxParts = MAX_PARTS}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing Remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Invalid ship build RemoteFunction") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMCappedShipBuilder"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.fromOffset(300, 300)
scroll.Position = UDim2.new(1, -320, 0, 150)
scroll.CanvasSize = UDim2.fromOffset(0, 900)
scroll.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = scroll
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 45)
status.Text = "Spend earned coins to build your spaceship"
status.Parent = scroll
local available = {
__PARTS__
}
local busy = false
for _, item in available do
    local button = Instance.new("TextButton")
    button.Name = item.id
    button.Text = item.label .. " (" .. tostring(item.cost) .. " Coins)"
    button.Size = UDim2.new(1, 0, 0, 36)
    button.Parent = scroll
    button.Activated:Connect(function()
        if busy then return end
        busy = true
        status.Text = "Validating ship part..."
        local ok, result = pcall(function() return remote:InvokeServer(item.id) end)
        busy = false
        if ok and type(result) == "table" and result.success == true then
            button.Active = false
            button.Text = item.label .. " (built)"
            status.Text = "Parts: " .. tostring(result.count) .. "/" .. tostring(result.maxParts)
                .. " | Coins: " .. tostring(result.coins)
                .. " | Total spent: " .. tostring(result.totalCost)
        else
            status.Text = "Rejected: " .. tostring(
                ok and type(result) == "table" and result.reason or "network")
        end
    end)
end
'''