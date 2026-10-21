"""A structural ship-section hierarchy from short, validated game-design data.

The host owns parent validation, finite section capacity, typed configurations,
resource debit, durable installed sections and 3D Parts. The planner provides
only concrete section IDs, parent relationships, costs and allowed options.
No generated module name or sample game title selects this behavior.
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
        "maxSections": {"type": "integer"},
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "label": {"type": "string"},
                "parent": {"type": "string"}, "cost": {"type": "integer"},
                "performance": {"type": "integer"},
                "configurations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id", "label", "parent", "cost", "performance", "configurations"],
        }},
    },
    "required": ["maxSections", "sections"],
}


def eligible_ship_hierarchy(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.name == server and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
    desc = owner.description.casefold()
    if (not re.search(r"\b(?:ship|spaceship|vessel)\s+assembly\b", desc)
            or not re.search(r"\b(?:ship\s+)?sections?\b", desc)
            or not re.search(r"\bparent\s+section\b", desc)
            or not re.search(r"\bsupported\s+section\s+types\b", desc)
            or not re.search(r"\bsection\s+limit\b", desc)
            or not re.search(r"\b(?:configuration\s+change|configure)\b", desc)
            or not re.search(r"\b(?:duplicate|already\s+has\s+a\s+section)\b", desc)
            or not re.search(r"\bserver\b", desc)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(remote, value) for remote, value in (design.get("host_actions") or {}).items()
              if isinstance(value, dict) and value.get("service") == server]
    if len(routes) != 1:
        return None
    remote, route = routes[0]
    max_args = route.get("max_args")
    if (route.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (max_args is not None and
                (type(max_args) is not int or max_args < 2))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
            return None
    else:
        if (module.name != server.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and remote not in linked:
            return None
    return server, remote


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Ship hierarchy needs a bounded catalog")
    maximum, sections = data.get("maxSections"), data.get("sections")
    if (type(maximum) is not int or not 1 <= maximum <= 8
            or not isinstance(sections, list) or not 1 <= len(sections) <= 12):
        raise ValueError("Ship needs 1-8 installed slots and 1-12 available sections")
    cleaned, ids = [], set()
    for row in sections:
        if not isinstance(row, dict):
            raise ValueError("Invalid ship section")
        sid, label, parent = row.get("id"), row.get("label"), row.get("parent")
        cost, power, choices = row.get("cost"), row.get("performance"), row.get("configurations")
        if (not isinstance(sid, str) or not _ID.fullmatch(sid)
                or sid.casefold() == "root" or sid.casefold() in ids
                or not isinstance(parent, str) or not _ID.fullmatch(parent)
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 55
                or type(cost) is not int or not 0 <= cost <= 100000
                or type(power) is not int or not 1 <= power <= 1000
                or not isinstance(choices, list) or not 1 <= len(choices) <= 6
                or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in choices)
                or len(set(choices)) != len(choices)):
            raise ValueError("Unsafe ship ID, parent, cost or configuration choices")
        ids.add(sid.casefold())
        cleaned.append({"id": sid, "label": label.strip(), "parent": parent,
                        "cost": cost, "performance": power, "configurations": choices})
    available = {row["id"] for row in cleaned}
    if not any(row["parent"] == "ROOT" for row in cleaned):
        raise ValueError("Ship must have at least one root-attached section")
    parents = {row["id"]: row["parent"] for row in cleaned}
    for sid, parent in parents.items():
        if parent != "ROOT" and parent not in available:
            raise ValueError("Ship section references unavailable parent")
        chain, current = set(), sid
        while current != "ROOT":
            if current in chain:
                raise ValueError("Ship section ancestry contains a cycle")
            chain.add(current)
            current = parents.get(current, "UNDECLARED")
            if current == "UNDECLARED":
                raise ValueError("Ship parent ancestry broken")
    return {"maxSections": maximum, "sections": cleaned}


def _read(proposal: Any, owner: str, router: Any) -> dict[str, Any]:
    cache = proposal.game_design.setdefault("_host_ship_hierarchy", {})
    if owner in cache:
        return _validate(cache[owner])
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("Missing real bounded ship hierarchy choices")
    requirement = next(m.description for m in proposal.modules if m.name == owner)
    prompt = (
        "Return ONLY JSON {maxSections:integer, sections:[{id,label,parent,"
        "cost,performance,configurations:[string]}]}. 1-12 concrete buildable "
        "sections, maximum 1-8 installed sections. parent must be ROOT or the "
        "ID of another defined part and the parent graph must be acyclic. "
        "At least one part directly requires ROOT. cost is a nonnegative "
        "extracted resource count; performance is a positive integer. "
        "configurations are a nonempty list of 1-6 allowed stable ASCII tokens "
        "for that section type. No Luau, Roblox code, imaginary APIs, remote "
        "definitions or user-chosen costs. Requirements: " + requirement[:1200]
    )
    last_error = ""
    for _ in range(2):
        try:
            row = router.complete_json(
                prompt + ("\nCorrect rejected JSON: " + last_error if last_error else ""),
                role="planner", temperature=0, max_tokens=1400, json_schema=_SCHEMA,
            )
            data = _validate(row)
            cache[owner] = data
            return data
        except Exception as exc:
            last_error = str(exc)[:220]
    raise ValueError("HOST_SHIP_HIERARCHY_SCHEMA_EXHAUSTED: " + last_error)


def try_ship_hierarchy(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_ship_hierarchy(module, proposal)
    if selected is None:
        return None
    owner, remote = selected
    data = _read(proposal, owner, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        rows = ",\n".join(
            "{id = " + json.dumps(x["id"]) + ", label = " +
            json.dumps(x["label"], ensure_ascii=False) + ", parent = " +
            json.dumps(x["parent"]) + ", cost = " + str(x["cost"]) +
            ", choices = {" + ", ".join(json.dumps(opt) for opt in x["configurations"]) +
            "}}" for x in data["sections"]
        )
        return (_CLIENT.replace("__REMOTE__", json.dumps(remote))
                .replace("__SECTIONS__", rows))
    rows = ",\n".join(
        "[" + json.dumps(x["id"]) + "] = {parent = " + json.dumps(x["parent"]) +
        ", cost = " + str(x["cost"]) + ", power = " + str(x["performance"]) +
        ", order = " + str(i+1) + ", options = {" +
        ", ".join("[" + json.dumps(opt) + "] = true" for opt in x["configurations"]) +
        "}}" for i,x in enumerate(data["sections"])
    )
    return (_SERVER.replace("__SECTIONS__", rows)
            .replace("__MAX_SECTIONS__", str(data["maxSections"])))


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local SECTIONS = {
__SECTIONS__
}
local MAX_SECTIONS = __MAX_SECTIONS__
local MAX_RESOURCES = 2147483647
local shipModels = setmetatable({}, {__mode = "k"})
local buildLots = {}
local activeLot = setmetatable({}, {__mode = "k"})

local function reject(reason)
    return {success = false, reason = reason}
end
local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player")
        and player.Parent == Players
end
local function integer(n)
    return type(n) == "number" and n == n and n % 1 == 0
        and n >= 0 and n <= MAX_RESOURCES
end
local function readState(player, services)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil end
    local ship = manager.GetState(player, "RMMShipSections")
    if type(ship) ~= "table" then return nil end
    if ship.sections == nil then ship.sections = {} end
    if type(ship.sections) ~= "table" then return nil end
    return ship.sections
end
local function inspect(sections)
    local n, performance, records = 0, 0, {}
    for id, entry in pairs(sections) do
        local defined = SECTIONS[id]
        if defined and type(entry) == "table" and entry.owned == true then
            n += 1
            performance += defined.power
            table.insert(records, {id = id, parent = defined.parent,
                configuration = entry.configuration})
        end
    end
    table.sort(records, function(a, b) return a.id < b.id end)
    return {partCount = n, performance = performance, sections = records}
end
local function publish(player, sections)
    local status = inspect(sections)
    player:SetAttribute("RMMShipPerformance", status.performance)
    player:SetAttribute("RMMShipAssemblyPerformance", status.performance)
    player:SetAttribute("RMMShipPartCount", status.partCount)
    return status
end
local function shipFor(player)
    local root = workspace:FindFirstChild("RMMPlayerShips")
    if root == nil then
        root = Instance.new("Folder")
        root.Name = "RMMPlayerShips"
        root.Parent = workspace
    end
    if not root:IsA("Folder") then return nil end
    local name = "RMMShip_" .. tostring(player.UserId)
    local model = root:FindFirstChild(name)
    if model and not model:IsA("Model") then return nil end
    if not model then
        model = Instance.new("Model")
        model.Name = name
        model:SetAttribute("OwnerUserId", player.UserId)
        model.Parent = root
    end
    if model:GetAttribute("OwnerUserId") ~= player.UserId then return nil end
    local sections = model:FindFirstChild("HierarchySections")
    if sections and not sections:IsA("Folder") then return nil end
    if not sections then
        sections = Instance.new("Folder")
        sections.Name = "HierarchySections"
        sections.Parent = model
    end
    if activeLot[player] == nil then
        local lot = 0
        while buildLots[lot] do lot += 1 end
        buildLots[lot] = true
        activeLot[player] = lot
    end
    shipModels[player] = model
    return sections
end
local function redraw(player, sections)
    local folder = shipFor(player)
    if not folder then return false end
    for _, child in folder:GetChildren() do
        if child:IsA("BasePart") then child:Destroy() end
    end
    local lot = activeLot[player] or 0
    local base = Vector3.new(30 + (lot % 10) * 80, 8,
        30 + math.floor(lot / 10) * 80)
    -- ROOT is a server-authored structural anchor, not a purchased module.
    local origin = Instance.new("Part")
    origin.Name = "ROOT"
    origin.Anchored = true
    origin.Size = Vector3.new(8, 2, 8)
    origin.Position = base
    origin.Parent = folder
    for id, entry in pairs(sections) do
        local def = SECTIONS[id]
        if def and type(entry) == "table" and entry.owned == true then
            local part = Instance.new("Part")
            part.Name = id
            part.Anchored = true
            part.Size = Vector3.new(6, 2, 8)
            part.Position = base + Vector3.new(def.order * 8, 0, 0)
            part:SetAttribute("ParentSection", def.parent)
            part:SetAttribute("Configuration", entry.configuration)
            part.Parent = folder
        end
    end
    return true
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Hierarchical ship assembly requires host-owned player profiles")
    services.PlayerDataManager.OnReady(function(player)
        local sections = readState(player, services)
        if sections then
            publish(player, sections)
            redraw(player, sections)
        end
    end)
    Players.PlayerRemoving:Connect(function(player)
        if shipModels[player] then
            shipModels[player]:Destroy()
            shipModels[player] = nil
        end
        local lot = activeLot[player]
        if lot ~= nil then
            buildLots[lot] = nil
            activeLot[player] = nil
        end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) then return reject("invalid_player") end
    local argc = select("#", ...)
    if argc < 1 or argc > 2 then return reject("invalid_arity") end
    local action, payload = ...
    local sections = readState(player, services)
    if not sections then return reject("profile_loading") end
    local before = inspect(sections)
    if action == "status" and argc == 1 then
        return {success = true, action = "status",
            partCount = before.partCount, performance = before.performance,
            sections = before.sections}
    end
    if argc ~= 2 then return reject("invalid_arity") end
    if action == "add" then
        if type(payload) ~= "string" then return reject("invalid_part_id") end
        local def = SECTIONS[payload]
        if not def then return reject("unsupported_section") end
        if sections[payload] ~= nil then return reject("duplicate_section") end
        if before.partCount >= MAX_SECTIONS then return reject("max_sections") end
        if def.parent ~= "ROOT" then
            local parent = sections[def.parent]
            if type(parent) ~= "table" or parent.owned ~= true then
                return reject("missing_parent_section")
            end
        end
        local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
        if type(inventory) ~= "table" then return reject("inventory_loading") end
        local resources = inventory.resources
        if resources == nil then resources = 0 end
        if not integer(resources) then return reject("invalid_resources") end
        if resources < def.cost then return reject("insufficient_resources") end
        if not shipFor(player) then return reject("ship_model_unavailable") end
        inventory.resources = resources - def.cost
        local default = nil
        for option in pairs(def.options) do default = option; break end
        sections[payload] = {owned = true, parent = def.parent,
            configuration = default, performance = def.power, level = 1}
        redraw(player, sections)
        local result = publish(player, sections)
        return {success = true, action = "add", added = payload,
            resources = inventory.resources, partCount = result.partCount,
            performance = result.performance, sections = result.sections}
    end
    if action == "configure" then
        if type(payload) ~= "table" then return reject("invalid_config_request") end
        local id, value = payload.id, payload.configuration
        if type(id) ~= "string" or type(value) ~= "string" then
            return reject("invalid_config_request")
        end
        local def = SECTIONS[id]
        local owned = sections[id]
        if not def or type(owned) ~= "table" or owned.owned ~= true then
            return reject("section_not_owned")
        end
        if def.options[value] ~= true then return reject("invalid_configuration") end
        if owned.configuration == value then return reject("already_configured") end
        owned.configuration = value
        redraw(player, sections)
        local result = publish(player, sections)
        return {success = true, action = "configure", partId = id,
            configuration = value, performance = result.performance,
            sections = result.sections}
    end
    return reject("unsupported_action")
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing Remotes folder") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Ship hierarchy route unavailable") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipSections"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.fromOffset(320, 340)
scroll.Position = UDim2.new(1, -335, 0, 165)
scroll.CanvasSize = UDim2.fromOffset(0, 1200)
scroll.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = scroll
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 65)
status.Text = "Ship section assembly"
status.Parent = scroll
local catalog = {
__SECTIONS__
}
local busy = false
local function request(action, data)
    if busy then return nil end
    busy = true
    status.Text = "Server validating " .. action .. "..."
    local ok, result = pcall(function()
        if data == nil then return remote:InvokeServer(action) end
        return remote:InvokeServer(action, data)
    end)
    busy = false
    if ok and type(result) == "table" then
        status.Text = result.success and
            ("Confirmed " .. action .. " | Parts " ..
                tostring(result.partCount or "?") .. " | Power " ..
                tostring(result.performance or "?"))
            or ("Rejected: " .. tostring(result.reason))
        return result
    end
    status.Text = "Server unavailable"
    return nil
end
for _, section in catalog do
    local add = Instance.new("TextButton")
    add.Name = section.id
    add.Size = UDim2.new(1, 0, 0, 36)
    add.Text = section.label .. " (needs " .. section.parent
        .. "; " .. tostring(section.cost) .. " resources)"
    add.Parent = scroll
    add.Activated:Connect(function() request("add", section.id) end)
    for _, choice in section.choices do
        local config = Instance.new("TextButton")
        config.Size = UDim2.new(1, 0, 0, 27)
        config.Text = "Configure " .. section.label .. ": " .. choice
        config.Parent = scroll
        config.Activated:Connect(function()
            request("configure", {id = section.id, configuration = choice})
        end)
    end
end
task.defer(function() request("status", nil) end)
'''