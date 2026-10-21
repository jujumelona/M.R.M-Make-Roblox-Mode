"""Host-managed configurable spaceship part add/remove/swap and structural gate.

A bounded planner supplies a concrete slot catalog and minimum structure.
Server code owns identity, part ownership, resources, duplicate prevention,
durable sections, physics Parts and a server-calculated ship performance. A
module name or the original user prompt never selects this implementation.
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
        "requiredSlots": {"type": "array", "items": {"type": "string"}},
        "parts": {"type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "string"}, "label": {"type": "string"},
                "slot": {"type": "string"}, "resourceCost": {"type": "integer"},
                "performance": {"type": "integer"},
            }, "required": ["id", "label", "slot", "resourceCost", "performance"],
        }},
    },
    "required": ["maxParts", "requiredSlots", "parts"],
}


def eligible_ship_reconfiguration(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    d = owner.description.casefold()
    if (not re.search(r"\b(?:ship|spaceship|vessel)\s+assembly\b", d)
            or not re.search(r"\bpart(?:s)?\s+addition\b|\badd(?:ing)?\s+(?:a\s+)?part\b", d)
            or not re.search(r"\bpart(?:s)?\s+removal\b|\bremove(?:s|d)?\b", d)
            or not re.search(r"\b(?:swap|replace)\b", d)
            or not re.search(r"\b(?:part\s+catalog|part\s+registry)\b", d)
            or not re.search(r"\bminimum\s+structural\s+requirements\b", d)
            or not re.search(r"\b(?:maximum part count|per[- ]ship limit)\b", d)
            or not re.search(r"\b(?:ship['’]s\s+owner|ship\s+owner|ship['’]s\s+owner|build permission)\b", d)
            or not re.search(r"\b(?:persist|save|record)\w*\b", d)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(name, val) for name, val in (design.get("host_actions") or {}).items()
              if isinstance(val, dict) and val.get("service") == server]
    if (len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(routes[0][0]) != "RemoteFunction"
            or (routes[0][1].get("max_args") is not None
                and (type(routes[0][1]["max_args"]) is not int
                     or routes[0][1]["max_args"] < 3))):
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
    return server, remote


def _validate(value: Any, minimum_performance: int = 0) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Ship catalog needs JSON object")
    parts, required, limit = value.get("parts"), value.get("requiredSlots"), value.get("maxParts")
    if (not isinstance(parts, list) or not 2 <= len(parts) <= 12
            or type(limit) is not int or not 1 <= limit <= 8
            or not isinstance(required, list) or not 1 <= len(required) <= limit):
        raise ValueError("Ship assembly needs a feasible 2-12-part slot catalog and cap")
    ids, slots = set(), {}
    cleaned = []
    for entry in parts:
        if not isinstance(entry, dict):
            raise ValueError("Part must be JSON record")
        pid, slot, label = entry.get("id"), entry.get("slot"), entry.get("label")
        cost, power = entry.get("resourceCost"), entry.get("performance")
        if (not isinstance(pid, str) or not _ID.fullmatch(pid)
                or pid.casefold() in ids
                or not isinstance(slot, str) or not _ID.fullmatch(slot)
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 50
                or type(cost) is not int or not 0 <= cost <= 100000
                or type(power) is not int or not 1 <= power <= 1000):
            raise ValueError("Ship part ID/slot, price or server-owned performance invalid")
        ids.add(pid.casefold())
        slots[slot] = max(slots.get(slot, 0), power)
        cleaned.append({"id":pid, "slot":slot, "label":label.strip(),
                        "resourceCost":cost, "performance":power})
    if (len(slots) < limit
            or any(not isinstance(slot, str) or slot not in slots for slot in required)
            or len(set(required)) != len(required)
            or type(minimum_performance) is not int or minimum_performance < 0
            or sum(sorted(slots.values(), reverse=True)[:limit]) < minimum_performance):
        raise ValueError("Declared essential slots, part cap or mode performance unreachable")
    return {"maxParts":limit, "requiredSlots":required, "parts":cleaned}


def _needed_mode_power(proposal: Any) -> int:
    from .host_performance_mode import eligible_performance_mode
    thresholds = []
    for module in getattr(proposal, "modules", []):
        if module.kind == ModuleKind.SERVER_MODULE:
            candidate = eligible_performance_mode(module, proposal)
            if candidate is not None:
                thresholds.append(candidate[2])
    return max(thresholds, default=0)


def _read(proposal: Any, server: str, router: Any) -> dict[str, Any]:
    minimum = _needed_mode_power(proposal)
    cache = proposal.game_design.setdefault("_host_ship_reconfiguration", {})
    if server in cache:
        return _validate(cache[server], minimum)
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("Missing bounded, actual ship part catalog")
    owner = next(m for m in proposal.modules if m.name == server)
    prompt = (
        "ONLY JSON {maxParts:integer,requiredSlots:[string],parts:[{id,label,"
        "slot,resourceCost,performance}]}. 2-12 actual ship parts in 1-8 "
        "distinct installation slots; at least one required structural slot. "
        "maxParts <= distinct slots. Each part has an ASCII stable ID, an ASCII "
        "stable structural slot, an actual resourceCost integer 0-100000, and "
        "integer ship performance 1-1000. A part may replace a DIFFERENT part "
        "in the same slot; essential slots cannot be removed after the ship "
        "becomes ready. Highest possible performance at cap must be >= " +
        str(minimum) + ". Host implements validation, state changes and Parts. "
        "NO Luau, Roblox APIs, fake inventory, arbitrary grants or code. "
        "Authored requirement: " + owner.description[:900]
    )
    problem = ""
    for _ in range(2):
        try:
            answer = router.complete_json(
                prompt + ("\nFix invalid JSON: " + problem if problem else ""),
                role="planner", temperature=0, max_tokens=1250, json_schema=_SCHEMA,
            )
            result = _validate(answer, minimum)
            cache[server] = result
            return result
        except Exception as exc:
            problem = str(exc)[:250]
    raise ValueError("HOST_SHIP_RECONFIGURATION_DATA_EXHAUSTED: " + problem)


def try_ship_reconfiguration(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_ship_reconfiguration(module, proposal)
    if selected is None:
        return None
    server, remote = selected
    data = _read(proposal, server, router)
    entries = data["parts"]
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        rows = ",\n".join(
            "{id = " + json.dumps(part["id"]) + ", label = " +
            json.dumps(part["label"], ensure_ascii=False) + ", slot = " +
            json.dumps(part["slot"]) + ", cost = " +
            str(part["resourceCost"]) + "}" for part in entries
        )
        return (_CLIENT.replace("__REMOTE__", json.dumps(remote))
                .replace("__PARTS__", rows))
    rows = ",\n".join(
        "[" + json.dumps(part["id"]) + "] = {slot = " +
        json.dumps(part["slot"]) + ", cost = " + str(part["resourceCost"]) +
        ", performance = " + str(part["performance"]) + ", ordinal = " +
        str(i+1) + "}" for i, part in enumerate(entries)
    )
    essentials = ", ".join("[" + json.dumps(slot) + "] = true" for slot in data["requiredSlots"])
    return (_SERVER.replace("__PARTS__", rows)
            .replace("__REQUIRED__", essentials)
            .replace("__CAP__", str(data["maxParts"])))


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local PARTS = {
__PARTS__
}
local REQUIRED = {__REQUIRED__}
local MAX_PARTS = __CAP__
local MAX_VALUE = 2147483647
local ships = {}
local slotsByPlayer = {}
local usedSlots = {}

local function reject(reason)
    return {success = false, reason = reason}
end
local function getState(services, player)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil end
    return manager.GetState(player, "RMMShipSections")
end
local function readInventory(services, player)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil end
    return manager.GetState(player, "RMMInventory")
end
local function collect(sections)
    local count, power, readyCount = 0, 0, 0
    if type(sections) ~= "table" then return nil end
    for slot, saved in pairs(sections) do
        if type(slot) ~= "string" or type(saved) ~= "table"
            or saved.owned ~= true or type(saved.partId) ~= "string" then
            return nil
        end
        local entry = PARTS[saved.partId]
        if not entry or entry.slot ~= slot then return nil end
        count += 1
        power += entry.performance
        if REQUIRED[slot] then readyCount += 1 end
    end
    local requiredCount = 0
    for _ in pairs(REQUIRED) do requiredCount += 1 end
    return {count = count, performance = power, ready = readyCount == requiredCount}
end
local function publish(player, sections)
    local current = collect(sections)
    if not current then return nil end
    player:SetAttribute("RMMShipPerformance", current.performance)
    player:SetAttribute("RMMShipPartCount", current.count)
    player:SetAttribute("RMMShipReady", current.ready)
    return current
end
local function shipFor(player)
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
    local sectionFolder = ship:FindFirstChild("ReconfigurableParts")
    if sectionFolder and not sectionFolder:IsA("Folder") then return nil end
    if not sectionFolder then
        sectionFolder = Instance.new("Folder")
        sectionFolder.Name = "ReconfigurableParts"
        sectionFolder.Parent = ship
    end
    ships[player] = ship
    return sectionFolder
end
local function renderParts(player, sections)
    local folder = shipFor(player)
    if not folder then return false end
    for _, child in folder:GetChildren() do
        if child:IsA("BasePart") then child:Destroy() end
    end
    for slot, saved in pairs(sections) do
        local def = PARTS[saved.partId]
        if def then
            local visual = Instance.new("Part")
            visual.Name = saved.partId
            visual.Anchored = true
            visual.Size = Vector3.new(5, 2, 7)
            visual.Position = Vector3.new(20 + def.ordinal * 5,
                5 + ((player.UserId % 100) * 6), 25)
            visual:SetAttribute("ShipPartSlot", slot)
            visual.Parent = folder
        end
    end
    return true
end

function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Reconfigurable ship requires a real persistent player profile")
    services.PlayerDataManager.OnReady(function(player)
        local state = getState(services,player)
        if not state then return end
        if state.sections == nil then state.sections = {} end
        if type(state.sections) ~= "table" then return end
        local status = publish(player, state.sections)
        if status then renderParts(player,state.sections) end
    end)
    Players.PlayerRemoving:Connect(function(player)
        if ships[player] then ships[player]:Destroy(); ships[player] = nil end
        local slot = slotsByPlayer[player]
        if slot ~= nil then usedSlots[slot] = nil; slotsByPlayer[player] = nil end
    end)
end

function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 3 then
        return reject("invalid_request")
    end
    local action, partId, slot = ...
    if type(action) ~= "string" or type(partId) ~= "string"
        or type(slot) ~= "string" then return reject("invalid_payload") end
    local part = PARTS[partId]
    if not part or part.slot ~= slot then return reject("unknown_part_or_slot") end
    if action ~= "add" and action ~= "remove" and action ~= "swap" then
        return reject("unsupported_action")
    end
    local profile = getState(services,player)
    local inventory = readInventory(services,player)
    if not profile or not inventory then return reject("profile_loading") end
    if profile.sections == nil then profile.sections = {} end
    if type(profile.sections) ~= "table" then return reject("invalid_ship_state") end
    local before = collect(profile.sections)
    if not before then return reject("invalid_ship_state") end
    local existing = profile.sections[slot]
    if (action == "add" and existing ~= nil)
        or (action ~= "add" and
            (type(existing) ~= "table" or existing.owned ~= true)) then
        return reject("slot_ownership")
    end
    if action ~= "add" and existing.partId ~= partId and action == "remove" then
        return reject("wrong_part")
    end
    if action == "swap" and existing.partId == partId then
        return reject("already_installed")
    end
    if action == "add" and before.count >= MAX_PARTS then return reject("part_cap") end
    if action == "remove" and REQUIRED[slot] and before.ready then
        return reject("essential_structure")
    end
    local nextParts = table.clone(profile.sections)
    if action == "remove" then nextParts[slot] = nil
    else nextParts[slot] = {owned = true, partId = partId,
        performance = part.performance, level = 1} end
    local after = collect(nextParts)
    if not after or after.count > MAX_PARTS
        or (before.ready and not after.ready) then
        return reject("structural_requirements")
    end
    local cost = (action == "remove") and 0 or part.cost
    local resources = inventory.resources
    if resources == nil then resources = 0 end
    if type(resources) ~= "number" or resources ~= resources
        or resources % 1 ~= 0 or resources < 0 or resources > MAX_VALUE then
        return reject("invalid_inventory")
    end
    if resources < cost then return reject("insufficient_resources") end
    local folder = shipFor(player)
    if not folder then return reject("ship_unavailable") end
    -- No yield between final validation and authoritative transaction commit.
    inventory.resources = resources - cost
    profile.sections = nextParts
    renderParts(player, nextParts)
    publish(player, nextParts)
    return {success = true, action = action, partId = partId,
        resources = inventory.resources, partCount = after.count,
        performance = after.performance, shipReady = after.ready}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing declared remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Ship remote mismatch") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipConfiguration"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.fromOffset(330, 310)
scroll.Position = UDim2.new(1, -345, 0, 220)
scroll.CanvasSize = UDim2.fromOffset(0, 1300)
scroll.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = scroll
local statusText = Instance.new("TextLabel")
statusText.Size = UDim2.new(1, 0, 0, 50)
statusText.Text = "Select ship parts and configure required slots"
statusText.Parent = scroll
local options = {
__PARTS__
}
local busy = false
local function submit(action, part)
    if busy then return end
    busy = true
    statusText.Text = "Server validating configuration..."
    local ok, result = pcall(function()
        return remote:InvokeServer(action, part.id, part.slot)
    end)
    busy = false
    if ok and type(result) == "table" and result.success == true then
        statusText.Text = "Ship " .. tostring(result.action)
            .. " | Power " .. tostring(result.performance)
            .. " | Parts " .. tostring(result.partCount)
            .. " | Resources " .. tostring(result.resources)
    else
        statusText.Text = "Rejected: " .. tostring(
            ok and type(result) == "table" and result.reason or "network")
    end
end
for _, option in options do
    local add = Instance.new("TextButton")
    add.Text = option.label .. " (" .. tostring(option.cost) .. " ore) Add"
    add.Size = UDim2.new(1, 0, 0, 37)
    add.Parent = scroll
    add.Activated:Connect(function() submit("add", option) end)
    local swap = Instance.new("TextButton")
    swap.Text = "Swap " .. option.label
    swap.Size = UDim2.new(1, 0, 0, 30)
    swap.Parent = scroll
    swap.Activated:Connect(function() submit("swap", option) end)
    local remove = Instance.new("TextButton")
    remove.Text = "Remove " .. option.label
    remove.Size = UDim2.new(1, 0, 0, 30)
    remove.Parent = scroll
    remove.Activated:Connect(function() submit("remove", option) end)
end
'''