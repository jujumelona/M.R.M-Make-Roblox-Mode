"""Host-owned currency-paid modular ship sections.

The authored plan determines the mechanic and bounded slot/variant data.
The host owns durable state, per-slot transactions, server pricing, refunds,
world components and performance. No free-form model Luau is requested.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_catalog_purchase import _ID
from .spec import ModuleKind

_SCHEMA = {
    "type": "object",
    "properties": {"slots": {
        "type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "label": {"type": "string"},
            "options": {"type": "array", "items": {"type": "object",
                "properties": {"id": {"type": "string"}, "label": {"type": "string"},
                               "cost": {"type": "integer"}, "performance": {"type": "integer"}},
                "required": ["id", "label", "cost", "performance"]}},
        }, "required": ["id", "label", "options"]},
    }},
    "required": ["slots"],
}


def eligible_currency_ship_sections(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not getattr(module, "module_id", "").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    owner_name = (module.name if module.kind == ModuleKind.SERVER_MODULE
                  else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in getattr(proposal, "modules", ())
                  if m.name == owner_name and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    # Semantic contract, never a module ID, user prompt substring or example
    # game. Resource-paid, upgrade-only and non-mutating ships belong elsewhere.
    if (not re.search(r"\b(?:ship|spaceship|vessel)\s+assembly\b", prose)
            or not re.search(r"\bsection\s+slots?\b|\bsections?\b.{0,40}\bslots?\b", prose)
            or not re.search(r"\bcreat\w*\b", prose)
            or not re.search(r"\breplac\w*\b", prose)
            or not re.search(r"\bremov\w*\b", prose)
            or not re.search(r"\b(?:currency|coins?|credits?)\b", prose)
            or not re.search(r"\b(?:cost|price)\b", prose)
            or not re.search(r"\b(?:refund|return|value|delta)\b", prose)
            or not re.search(r"\bperformance\b", prose)
            or not re.search(r"\b(?:persist|save|record)\w*\b", prose)):
        return None
    design = getattr(proposal, "game_design", {}).get("dynamic_design") or {}
    routes = [(name, val) for name, val in (design.get("host_actions") or {}).items()
              if isinstance(val, dict) and val.get("service") == owner_name]
    if len(routes) != 1:
        return None
    name, action = routes[0]
    max_args = action.get("max_args")
    if (action.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(name) != "RemoteFunction"
            or (max_args is not None
                and (type(max_args) is not int or max_args < 3))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
            return None
    else:
        if (module.name != owner_name.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and name not in linked:
            return None
    return owner_name, name


def _validate_currency_slots(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("slots"), list):
        raise ValueError("CURRENCY_SHIP_SLOTS_REQUIRED")
    slots = value["slots"]
    if not 1 <= len(slots) <= 10:
        raise ValueError("CURRENCY_SHIP_SLOT_COUNT_INVALID")
    result, ids = [], set()
    for row in slots:
        if not isinstance(row, dict):
            raise ValueError("CURRENCY_SHIP_SLOT_INVALID")
        sid, label, options = row.get("id"), row.get("label"), row.get("options")
        if (not isinstance(sid, str) or not _ID.fullmatch(sid)
                or sid.casefold() in ids
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 52
                or not isinstance(options, list) or not 1 <= len(options) <= 4):
            raise ValueError("CURRENCY_SHIP_SLOT_INVALID")
        ids.add(sid.casefold())
        choices, option_ids = [], set()
        for choice in options:
            if not isinstance(choice, dict):
                raise ValueError("CURRENCY_SHIP_OPTION_INVALID")
            cid, cname = choice.get("id"), choice.get("label")
            cost, power = choice.get("cost"), choice.get("performance")
            if (not isinstance(cid, str) or not _ID.fullmatch(cid)
                    or cid.casefold() in option_ids
                    or not isinstance(cname, str) or not 1 <= len(cname.strip()) <= 52
                    or type(cost) is not int or not 1 <= cost <= 100000
                    or type(power) is not int or not 1 <= power <= 1000):
                raise ValueError("CURRENCY_SHIP_OPTION_INVALID")
            option_ids.add(cid.casefold())
            choices.append({"id": cid, "label": cname.strip(),
                            "cost": cost, "performance": power})
        result.append({"id": sid, "label": label.strip(), "options": choices})
    return result


def _read(proposal: Any, owner: str, router: Any) -> list[dict[str, Any]]:
    catalogs = proposal.game_design.setdefault("_host_currency_ship_sections", {})
    if owner in catalogs:
        return _validate_currency_slots({"slots": catalogs[owner]})
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("CURRENCY_SHIP_CATALOG_UNAVAILABLE")
    server = next(m for m in proposal.modules if m.name == owner)
    prompt = (
        "Return ONLY a short JSON object {slots:[{id,label,options:"
        "[{id,label,cost,performance}]}]} with 1-10 independent ship slots "
        "and 1-4 variant options per slot. Each id is a stable ASCII "
        "identifier starting with a letter; costs are positive earned "
        "in-game currency, not server-side resource numbers. Performance "
        "is a positive integer contribution from installed variants. "
        "The host owns all create/replace/remove transactions and refunds: "
        "NO Luau, APIs, methods, remotes, player-controlled costs, or code. "
        "Required game behavior: " + server.description[:1250]
    )
    problem = ""
    for _ in range(2):
        try:
            raw = router.complete_json(
                prompt + ("\nFix invalid options: " + problem if problem else ""),
                role="planner", temperature=0, max_tokens=1100, json_schema=_SCHEMA,
            )
            validated = _validate_currency_slots(raw)
            catalogs[owner] = validated
            return validated
        except Exception as exc:
            problem = str(exc)[:240]
    raise ValueError("HOST_CURRENCY_SHIP_CATALOG_EXHAUSTED: " + problem)


def try_currency_ship_sections(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_currency_ship_sections(module, proposal)
    if selected is None:
        return None
    owner, remote = selected
    slots = _read(proposal, owner, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        rows = ",\n".join(
            "{id = " + json.dumps(slot["id"]) + ", label = " +
            json.dumps(slot["label"], ensure_ascii=False) + ", options = {" +
            ", ".join("{id = " + json.dumps(v["id"]) + ", label = " +
                      json.dumps(v["label"], ensure_ascii=False) + ", cost = " +
                      str(v["cost"]) + "}" for v in slot["options"]) + "}}"
            for slot in slots
        )
        return (_CLIENT.replace("__REMOTE__", json.dumps(remote))
                .replace("__SLOTS__", rows))
    rows = ",\n".join(
        "[" + json.dumps(slot["id"]) + "] = {order = " + str(i+1)
        + ", options = {" + ", ".join(
            "[" + json.dumps(v["id"]) + "] = {cost = " + str(v["cost"]) +
            ", performance = " + str(v["performance"]) + "}"
            for v in slot["options"]
        ) + "}}"
        for i, slot in enumerate(slots)
    )
    return _SERVER.replace("__SLOTS__", rows)


_SERVER = r'''--!strict
-- Server owns the price catalog and paidPrice: client supplies identifiers ONLY.
local Players = game:GetService("Players")
local Service = {}
local SLOTS = {
__SLOTS__
}
local INT_MAX = 2147483647
local shipParts = setmetatable({}, {__mode = "k"})
local buildLots = {}
local playerLots = setmetatable({}, {__mode = "k"})

local function reject(reason)
    return {success = false, reason = reason}
end
local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player")
        and player.Parent == Players
end
local function finiteInt(v)
    return type(v) == "number" and v == v and v % 1 == 0
        and v >= 0 and v <= INT_MAX
end
local function getSections(player, services)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return nil
    end
    local state = manager.GetState(player, "RMMShipSections")
    if type(state) ~= "table" then return nil end
    if state.sections == nil then state.sections = {} end
    if type(state.sections) ~= "table" then return nil end
    return state.sections
end
local function inspect(sections)
    local performance, count = 0, 0
    for slotId, installed in pairs(sections) do
        local def = SLOTS[slotId]
        if not def or type(installed) ~= "table" or installed.owned ~= true
            or type(installed.variantId) ~= "string"
            or not finiteInt(installed.paidPrice) then return nil end
        local option = def.options[installed.variantId]
        if not option or installed.paidPrice ~= option.cost then return nil end
        count += 1
        performance += option.performance
    end
    return {partCount = count, performance = performance}
end
local function publish(player, sections)
    local result = inspect(sections)
    if not result then return nil end
    player:SetAttribute("RMMShipPerformance", result.performance)
    player:SetAttribute("RMMShipAssemblyPerformance", result.performance)
    player:SetAttribute("RMMShipPartCount", result.partCount)
    return result
end
local function getFolder(player)
    local root = workspace:FindFirstChild("RMMPlayerShips")
    if not root then
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
    local folder = model:FindFirstChild("CurrencySections")
    if folder and not folder:IsA("Folder") then return nil end
    if not folder then
        folder = Instance.new("Folder")
        folder.Name = "CurrencySections"
        folder.Parent = model
    end
    local lot = playerLots[player]
    if lot == nil then
        lot = 0
        while buildLots[lot] do lot += 1 end
        buildLots[lot] = true
        playerLots[player] = lot
    end
    shipParts[player] = folder
    return folder, lot
end
local function redraw(player, sections)
    local folder, lot = getFolder(player)
    if not folder or lot == nil then return false end
    for _, child in folder:GetChildren() do
        if child:IsA("BasePart") then child:Destroy() end
    end
    local origin = Vector3.new(30 + (lot % 10) * 85,
        7, 30 + math.floor(lot / 10) * 85)
    for id, installed in pairs(sections) do
        local def = SLOTS[id]
        if def then
            local part = Instance.new("Part")
            part.Name = id
            part.Anchored = true
            part.Size = Vector3.new(6, 3, 7)
            part.Position = origin + Vector3.new(def.order * 8, 0, 0)
            part:SetAttribute("ShipSectionVariant", installed.variantId)
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
        "Currency ship builder requires real host profile")
    services.PlayerDataManager.OnReady(function(player)
        local sections = getSections(player, services)
        if sections and inspect(sections) then
            redraw(player, sections)
            publish(player, sections)
        end
    end)
    Players.PlayerRemoving:Connect(function(player)
        local folder = shipParts[player]
        if folder then folder:Destroy(); shipParts[player] = nil end
        local lot = playerLots[player]
        if lot ~= nil then buildLots[lot] = nil; playerLots[player] = nil end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) or select("#", ...) ~= 3 then
        return reject("invalid_request")
    end
    local action, slotId, variantId = ...
    if type(action) ~= "string" or type(slotId) ~= "string"
        or type(variantId) ~= "string" then return reject("invalid_payload") end
    local slot = SLOTS[slotId]
    local option = slot and slot.options[variantId]
    if not slot or not option then return reject("unknown_slot_or_variant") end
    if action ~= "create" and action ~= "replace" and action ~= "remove" then
        return reject("unsupported_action")
    end
    local sections = getSections(player, services)
    if not sections or not inspect(sections) then
        return reject("invalid_ship_state")
    end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue")
        or not finiteInt(coins.Value) then return reject("currency_unavailable") end
    local existing = sections[slotId]
    if action == "create" and existing ~= nil then return reject("already_owned") end
    if action ~= "create" and existing == nil then return reject("not_owned") end
    if action == "replace" and existing.variantId == variantId then
        return reject("same_variant")
    end
    if action == "remove" and existing.variantId ~= variantId then
        return reject("stale_variant")
    end
    local oldPaid = existing and existing.paidPrice or 0
    local targetPaid = action == "remove" and 0 or option.cost
    local netCharge = targetPaid - oldPaid
    if netCharge > coins.Value then return reject("insufficient_currency") end
    if netCharge < 0 and coins.Value > INT_MAX + netCharge then
        return reject("currency_overflow")
    end
    if not getFolder(player) then return reject("ship_unavailable") end
    -- No yielding after validation and before mutations.
    coins.Value -= netCharge
    if action == "remove" then
        sections[slotId] = nil
    else
        sections[slotId] = {owned = true, variantId = variantId,
            paidPrice = targetPaid, performance = option.performance}
    end
    redraw(player, sections)
    local result = publish(player, sections)
    player:SetAttribute("RMMCurrencyBalance", coins.Value)
    return {success = true, action = action, slot = slotId, variant = variantId,
        currency = coins.Value, charged = netCharge,
        performance = result.performance, partCount = result.partCount}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing declared Remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then
    error("Wrong ship-section Remote")
end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMCurrencyShipSectionEditor"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("ScrollingFrame")
panel.Size = UDim2.fromOffset(320, 335)
panel.Position = UDim2.new(1, -336, 0, 135)
panel.CanvasSize = UDim2.fromOffset(0, 1650)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 45)
status.Text = "Server-priced ship section assembly"
status.Parent = panel
local slots = {
__SLOTS__
}
local busy = false
local function request(action, slotId, optionId)
    if busy then return end
    busy = true
    status.Text = "Validating " .. action .. "..."
    local ok, result = pcall(function()
        return remote:InvokeServer(action, slotId, optionId)
    end)
    busy = false
    if ok and type(result) == "table" and result.success == true then
        status.Text = action .. " " .. tostring(result.slot)
            .. " | Coins " .. tostring(result.currency)
            .. " | Ship power " .. tostring(result.performance)
    else
        status.Text = "Rejected: " .. tostring(
            ok and type(result) == "table" and result.reason or "network")
    end
end
for _, slot in slots do
    for _, option in slot.options do
        for _, action in {"create", "replace", "remove"} do
            local button = Instance.new("TextButton")
            button.Name = slot.id .. "_" .. option.id .. "_" .. action
            button.Size = UDim2.new(1, 0, 0, 31)
            button.Text = action .. " " .. slot.label .. " / " .. option.label
                .. " (" .. tostring(option.cost) .. " coins)"
            button.Parent = panel
            button.Activated:Connect(function()
                request(action, slot.id, option.id)
            end)
        end
    end
end
'''