"""Reusable ship-section assembly from bounded declarative gameplay rules.

The model chooses which named sections a specific game offers and their resource
costs. The host handles persistent ownership, world Parts, server-only
transactions, proximity and client controls. No success-shaped stub is used.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .spec import ModuleKind
from .host_catalog_purchase import _ID
from .host_ship_currency_sections import (
    eligible_currency_ship_sections, try_currency_ship_sections,
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "slots": {"type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "label": {"type": "string"},
                "cost": {"type": "integer"},
            }, "required": ["id", "label", "cost"]}},
    }, "required": ["slots"],
}


def eligible_ship_sections(module: Any, proposal: Any) -> tuple[str, str] | None:
    currency_sections = eligible_currency_ship_sections(module, proposal)
    if currency_sections is not None:
        return currency_sections
    if not module.module_id.startswith("dyn_") or module.kind not in (
        ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT
    ):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    if (not re.search(r"\b(?:ship|spaceship)\s+assembly\b", prose)
            or not re.search(r"\b(?:section|slot)s?\b", prose)
            or not all(word in prose for word in ("create", "replace", "remove", "upgrade"))
            or not re.search(r"\b(?:resource|inventory|currency)\b", prose)
            or not re.search(r"\b(?:player|owner|owned)\b", prose)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(k, v) for k, v in (design.get("host_actions") or {}).items()
              if isinstance(v, dict) and v.get("service") == server]
    if (len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction"
            or routes[0][1].get("max_args") == 0
            or (design.get("remotes") or {}).get(routes[0][0]) != "RemoteFunction"):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if not module.file_path.startswith("src/client/") or not module.file_path.endswith(".client.luau"):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and routes[0][0] not in linked:
            return None
    return server, routes[0][0]


def _slots(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("slots"), list):
        raise ValueError("Ship assembly needs slots array")
    rows = value["slots"]
    if not 1 <= len(rows) <= 10:
        raise ValueError("Ship assembly requires 1-10 concrete slots")
    result, seen = [], set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("Ship slot must be an object")
        slot, label, cost = item.get("id"), item.get("label"), item.get("cost")
        if (not isinstance(slot, str) or not _ID.fullmatch(slot)
                or slot in seen
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 54
                or type(cost) is not int or not 1 <= cost <= 100000):
            raise ValueError("Ship slot must have unique safe id, label, and positive resource cost")
        result.append({"id": slot, "label": label.strip(), "cost": cost})
        seen.add(slot)
    return result


def _read(proposal: Any, owner: str, router: Any) -> list[dict[str, Any]]:
    catalogs = proposal.game_design.setdefault("_host_ship_section_catalogs", {})
    if owner in catalogs:
        return _slots({"slots": catalogs[owner]})
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("Ship section catalog must be derived from authored game rules")
    server = next(m for m in proposal.modules if m.name == owner)
    prompt = (
        "Return ONLY a short JSON object {slots:[{id,label,cost}]}, with "
        "1-10 actual ship section slots requested for this game. cost is "
        "positive earned resource units required for initial construction. "
        "No Luau, Roblox API, code, Remote, boilerplate, or invented success. "
        "Each id must be ASCII letters/numbers/underscores and start with "
        "a letter. Game-specific server requirement: " + server.description[:1200]
    )
    last = ""
    for _ in range(2):
        try:
            data = router.complete_json(
                prompt + ("\nFix schema: " + last if last else ""),
                role="planner", temperature=0, max_tokens=800,
                json_schema=_SCHEMA,
            )
            rows = _slots(data)
            catalogs[owner] = rows
            return rows
        except Exception as exc:
            last = str(exc)[:300]
    raise ValueError("HOST_DECLARATIVE_SHIP_SECTIONS_EXHAUSTED: " + last)


def try_ship_sections(module: Any, proposal: Any, router: Any = None) -> str | None:
    priced_sections = try_currency_ship_sections(module, proposal, router)
    if priced_sections is not None:
        return priced_sections
    info = eligible_ship_sections(module, proposal)
    if info is None:
        return None
    server, remote = info
    slots = _read(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        rows = ",\n".join("{id = " + json.dumps(r["id"]) + ", label = "
                          + json.dumps(r["label"], ensure_ascii=False) + "}" for r in slots)
        return _CLIENT.replace("__REMOTE__", json.dumps(remote)).replace("__SLOTS__", rows)
    rows = ",\n".join("[" + json.dumps(r["id"]) + "] = {cost = "
                      + str(r["cost"]) + ", order = " + str(i+1) + "}"
                      for i, r in enumerate(slots))
    return _SERVER.replace("__SLOTS__", rows)


_SERVER = r'''--!strict
-- Host-owned persistence, craft cost, ownership and world representation.
local Players = game:GetService("Players")
local Service = {}
local SLOTS = {
__SLOTS__
}
local MAX_LEVEL = 3
local SHIP_DISTANCE = 26
local shipModels = setmetatable({}, {__mode = "k"})

local function createShip(player, services)
    local profile = services.PlayerDataManager.GetState(player, "RMMShipSections")
    if not profile then return nil end
    if type(profile.sections) ~= "table" then profile.sections = {} end
    local root = workspace:FindFirstChild("RMMPlayerShips")
    if not root then
        root = Instance.new("Folder")
        root.Name = "RMMPlayerShips"
        root.Parent = workspace
    end
    local model = Instance.new("Model")
    model.Name = "RMMShip_" .. tostring(player.UserId)
    model:SetAttribute("OwnerUserId", player.UserId)
    model.Parent = root
    local anchor = Instance.new("Part")
    anchor.Name = "AssemblyAnchor"
    anchor.Size = Vector3.new(8, 1, 8)
    anchor.Anchored = true
    anchor.Position = Vector3.new(35 + (player.UserId % 11) * 22, 2, 45
        + (math.floor(player.UserId / 11) % 11) * 22)
    anchor.Parent = model
    model.PrimaryPart = anchor
    shipModels[player] = model
    for id, config in pairs(SLOTS) do
        local state = profile.sections[id]
        if type(state) == "table" and state.owned == true then
            local part = Instance.new("Part")
            part.Name = id
            part.Anchored = true
            part.Size = Vector3.new(4, 2 + math.clamp(state.level or 1, 1, MAX_LEVEL), 4)
            part.Position = anchor.Position + Vector3.new(config.order * 5, 4, 0)
            part.Parent = model
        end
    end
    return model
end
function Service.start(services)
    assert(type(services) == "table" and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Ship assembly requires host profiles")
    services.PlayerDataManager.OnReady(function(player)
        if shipModels[player] then shipModels[player]:Destroy() end
        createShip(player, services)
    end)
    Players.PlayerRemoving:Connect(function(player)
        if shipModels[player] then shipModels[player]:Destroy(); shipModels[player] = nil end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or
        player.Parent ~= Players or select("#", ...) ~= 2 then return false end
    local command, slot = ...
    if type(command) ~= "string" or type(slot) ~= "string" then return false end
    local config = SLOTS[slot]
    if not config or (command ~= "create" and command ~= "replace"
        and command ~= "remove" and command ~= "upgrade") then return false end
    local model = shipModels[player]
    local anchor = model and model.PrimaryPart
    local char = player.Character
    local root = char and char:FindFirstChild("HumanoidRootPart")
    local human = char and char:FindFirstChildOfClass("Humanoid")
    if not anchor or not root or not human or human.Health <= 0 or
        (anchor.Position - root.Position).Magnitude > SHIP_DISTANCE then return false end
    local profile = services.PlayerDataManager.GetState(player, "RMMShipSections")
    local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not profile or not inventory or type(profile.sections) ~= "table" then return false end
    if type(inventory.resources) ~= "number" or inventory.resources ~= inventory.resources
        or inventory.resources % 1 ~= 0 or inventory.resources < 0 then return false end
    local state = profile.sections[slot]
    if state ~= nil and (type(state) ~= "table" or type(state.owned) ~= "boolean"
        or type(state.level) ~= "number") then return false end
    local owned = state ~= nil and state.owned == true
    local level = owned and state.level or 0
    if level % 1 ~= 0 or level < 0 or level > MAX_LEVEL then return false end
    if command == "create" and owned then return false end
    if command ~= "create" and not owned then return false end
    if command == "upgrade" and level >= MAX_LEVEL then return false end
    local newLevel = command == "remove" and 0 or (command == "upgrade" and level + 1 or 1)
    local cost = command == "remove" and 0
        or config.cost * (command == "upgrade" and newLevel or 1)
    if cost > 2147483647 or inventory.resources < cost then return false end
    -- All validations complete. No yielding while updating profile and world.
    inventory.resources -= cost
    profile.sections[slot] = {owned = newLevel > 0, level = newLevel}
    local previous = model:FindFirstChild(slot)
    if previous then previous:Destroy() end
    if newLevel > 0 then
        local part = Instance.new("Part")
        part.Name = slot
        part.Anchored = true
        part.Size = Vector3.new(4, 2 + newLevel, 4)
        part.Position = anchor.Position + Vector3.new(config.order * 5, 4, 0)
        part.Parent = model
    end
    return {success = true, slot = slot, command = command,
        level = newLevel, resources = inventory.resources}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local folder = ReplicatedStorage:WaitForChild("Remotes", 20)
if not folder then error("Missing host Remotes") end
local remote = folder:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Invalid assembly Remote") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipSectionEditor"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("ScrollingFrame")
panel.Name = "Sections"
panel.Size = UDim2.fromOffset(260, 325)
panel.Position = UDim2.new(1, -280, 0, 135)
panel.CanvasSize = UDim2.fromOffset(0, 1400)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 38)
status.Text = "Move near your ship to assemble sections"
status.Parent = panel
local slots = {
__SLOTS__
}
local busy = false
for _, slot in slots do
    local title = Instance.new("TextLabel")
    title.Size = UDim2.new(1, 0, 0, 25)
    title.Text = slot.label
    title.Parent = panel
    for _, command in {"create", "replace", "remove", "upgrade"} do
        local btn = Instance.new("TextButton")
        btn.Name = slot.id .. "_" .. command
        btn.Size = UDim2.new(1, 0, 0, 31)
        btn.Text = command .. " " .. slot.label
        btn.Parent = panel
        btn.Activated:Connect(function()
            if busy then return end
            busy = true
            local ok, result = pcall(function()
                return remote:InvokeServer(command, slot.id)
            end)
            busy = false
            if ok and type(result) == "table" and result.success == true then
                status.Text = result.slot .. " level " .. tostring(result.level)
                    .. "; ore left: " .. tostring(result.resources)
            else
                status.Text = "Rejected: ownership, distance, resources or level"
            end
        end)
    end
end
'''