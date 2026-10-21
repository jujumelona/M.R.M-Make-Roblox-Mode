"""Host-owned ship part installation from a small validated part catalog.

This is a different contract from resource-based ship-section crafting:
the customer spends earned Coins on a part ID in a fixed build slot. The
host owns the currency transaction, durable ownership and visible instances.
No module-specific names or user prompts are used to select this adapter.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_catalog_purchase import _ID
from .spec import ModuleKind

_SCHEMA = {
    "type": "object",
    "properties": {"parts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "label": {"type": "string"},
            "slot": {"type": "string"}, "cost": {"type": "integer"},
            "performance": {"type": "integer"},
            "upgrades": {"type": "array", "items": {"type": "object",
                "properties": {
                    "id": {"type": "string"}, "label": {"type": "string"},
                    "cost": {"type": "integer"}, "bonus": {"type": "integer"},
                }, "required": ["id", "label", "cost", "bonus"]}},
        },
        "required": ["id", "label", "slot", "cost", "performance", "upgrades"],
    }}},
    "required": ["parts"],
}


def eligible_ship_part_catalog(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    description = owner.description.casefold()
    if (not re.search(r"\b(?:spaceship|ship)\s+part\b", description)
            or not re.search(r"\bcatalog\b", description)
            or not re.search(r"\b(?:slot|installed|install)\b", description)
            or not re.search(r"\b(?:currency|coins?|credits?)\b", description)
            or not re.search(r"\b(?:performance|contribution)\b", description)
            or not re.search(r"\b(?:validat|reject|accept)\w*\b", description)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    linked = [(name, action) for name, action in (design.get("host_actions") or {}).items()
              if isinstance(action, dict) and action.get("service") == server]
    if len(linked) != 1:
        return None
    remote, action = linked[0]
    if (action.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (type(action.get("max_args")) is int and action["max_args"] < 3)):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if (not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        client_remotes = (design.get("module_remotes") or {}).get(module.module_id)
        if client_remotes is not None and remote not in client_remotes:
            return None
    return server, remote


def validate_parts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("parts"), list):
        raise ValueError("Expected a short part catalog with parts array")
    rows = value["parts"]
    if not 1 <= len(rows) <= 8:
        raise ValueError("Must have 1-8 purchasable ship parts")
    ids, out = set(), []
    for part in rows:
        if not isinstance(part, dict):
            raise ValueError("Part must be a JSON object")
        part_id, slot = part.get("id"), part.get("slot")
        label, cost, power = part.get("label"), part.get("cost"), part.get("performance")
        if (not isinstance(part_id, str) or not _ID.fullmatch(part_id)
                or part_id in ids or not isinstance(slot, str) or not _ID.fullmatch(slot)
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 60
                or type(cost) is not int or not 1 <= cost <= 1000000
                or type(power) is not int or not 1 <= power <= 1000):
            raise ValueError("Invalid part ID, slot, label, cost or contribution")
        choices = part.get("upgrades")
        if not isinstance(choices, list) or len(choices) > 2:
            raise ValueError("Part must declare 0-2 upgrade choices")
        clean = []
        used_choices = set()
        for choice in choices:
            if not isinstance(choice, dict):
                raise ValueError("Upgrade must be an object")
            uid, title = choice.get("id"), choice.get("label")
            charge, bonus = choice.get("cost"), choice.get("bonus")
            if (not isinstance(uid, str) or not _ID.fullmatch(uid)
                    or uid in used_choices or not isinstance(title, str)
                    or not 1 <= len(title.strip()) <= 50 or type(charge) is not int
                    or not 1 <= charge <= 1000000 or type(bonus) is not int
                    or not 1 <= bonus <= 1000):
                raise ValueError("Invalid upgrade ID, label, price or bonus")
            used_choices.add(uid)
            clean.append({"id": uid, "label": title.strip(), "cost": charge, "bonus": bonus})
        ids.add(part_id)
        out.append({"id": part_id, "slot": slot, "label": label.strip(),
                    "cost": cost, "performance": power, "upgrades": clean})
    return out


def _catalog(proposal: Any, server: str, router: Any) -> list[dict[str, Any]]:
    cache = proposal.game_design.setdefault("_host_ship_part_catalogs", {})
    if server in cache:
        return validate_parts({"parts": cache[server]})
    if not hasattr(router, "complete_json"):
        raise ValueError("A structured part catalog model is required")
    module = next(m for m in proposal.modules if m.name == server)
    prompt = (
        "Return ONLY JSON {parts:[...]}, not Luau. 1-8 ship parts, each "
        "{id,label,slot,cost,performance,upgrades:[{id,label,cost,bonus}]}. "
        "IDs and slots must be stable ASCII identifiers. Costs are POSITIVE "
        "server-owned earned Coins, performance and bonus positive integers. "
        "At most 2 upgrades per part. Do not invent services, Roblox methods, "
        "Remote code, balances or world Parts. Description: " + module.description[:1150]
    )
    reason = ""
    for _ in range(2):
        try:
            raw = router.complete_json(
                prompt + ("\nCorrect these data errors: " + reason if reason else ""),
                role="planner", temperature=0.0, max_tokens=1350,
                json_schema=_SCHEMA,
            )
            rows = validate_parts(raw)
            cache[server] = rows
            return rows
        except Exception as exc:
            reason = str(exc)[:400]
    raise ValueError("HOST_SHIP_PART_CATALOG_EXHAUSTED: " + reason)


def try_ship_part_catalog(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_ship_part_catalog(module, proposal)
    if selected is None:
        return None
    server, remote = selected
    parts = _catalog(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        encoded = ",\n".join(
            "{id = " + json.dumps(p["id"]) + ", label = " +
            json.dumps(p["label"], ensure_ascii=False) + ", slot = " +
            json.dumps(p["slot"]) + ", cost = " + str(p["cost"]) +
            ", upgrades = {" + ", ".join(
                "{id = " + json.dumps(u["id"]) + ", label = " +
                json.dumps(u["label"], ensure_ascii=False) + ", cost = " +
                str(u["cost"]) + "}" for u in p["upgrades"]
            ) + "}}" for p in parts
        )
        return _CLIENT.replace("__REMOTE__", json.dumps(remote)).replace("__PARTS__", encoded)
    encoded = ",\n".join(
        "[" + json.dumps(p["id"]) + "] = {slot = " + json.dumps(p["slot"]) +
        ", cost = " + str(p["cost"]) + ", performance = " +
        str(p["performance"]) + ", ordinal = " + str(i + 1) +
        ", upgrades = {" + ", ".join(
            "[" + json.dumps(u["id"]) + "] = {cost = " + str(u["cost"]) +
            ", bonus = " + str(u["bonus"]) + "}"
            for u in p["upgrades"]
        ) + "}}" for i, p in enumerate(parts)
    )
    return _SERVER.replace("__PARTS__", encoded)


_SERVER = r'''--!strict
-- Host owns the complete transaction, persistent ship state, and visible ship model.
local Players = game:GetService("Players")
local Service = {}
local PARTS = {
__PARTS__
}
local MAX_COINS = 2147483647
-- Assign distinct server-session lots; UserId modulo alone can overlap players.
local lotsByPlayer = {}
local occupiedLots = {}
local function lotOf(player)
    if lotsByPlayer[player] ~= nil then return lotsByPlayer[player] end
    local lot = 0
    while occupiedLots[lot] do lot += 1 end
    occupiedLots[lot] = true
    lotsByPlayer[player] = lot
    return lot
end
local function reject(reason)
    return {success = false, reason = reason}
end
local function shipState(services, player)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then return nil end
    return manager.GetState(player, "RMMShipSections")
end
local function readCoins(player)
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") then return nil end
    if coins.Value < 0 or coins.Value > MAX_COINS then return nil end
    return coins
end
local function recalc(player, profile)
    local performance = 0
    if type(profile.sections) == "table" then
        for slot, state in pairs(profile.sections) do
            if type(slot) == "string" and type(state) == "table" and state.owned == true then
                local part = PARTS[state.partId]
                if part and part.slot == slot then
                    performance += part.performance
                    if type(state.upgrades) == "table" then
                        for upgradeId, active in pairs(state.upgrades) do
                            local upgrade = part.upgrades[upgradeId]
                            if active == true and upgrade then performance += upgrade.bonus end
                        end
                    end
                end
            end
        end
    end
    player:SetAttribute("RMMShipPerformance", performance)
end
local function ensureShip(player)
    local folder = workspace:FindFirstChild("RMMPlayerShips")
    if not folder then
        folder = Instance.new("Folder")
        folder.Name = "RMMPlayerShips"
        folder.Parent = workspace
    end
    local name = "RMMShip_" .. tostring(player.UserId)
    local ship = folder:FindFirstChild(name)
    if not ship then
        ship = Instance.new("Model")
        ship.Name = name
        ship:SetAttribute("OwnerUserId", player.UserId)
        ship.Parent = folder
    end
    return ship
end
local function partVisual(player, partId)
    local definition = PARTS[partId]
    if not definition then return end
    local ship = ensureShip(player)
    local existing = ship:FindFirstChild(definition.slot)
    if existing then existing:Destroy() end
    local part = Instance.new("Part")
    part.Name = definition.slot
    part.Anchored = true
    part.Size = Vector3.new(4, 3, 6)
    local lot = lotOf(player)
    part.Position = Vector3.new(30 + (lot % 12) * 22,
        5 + definition.ordinal * 3, 30 + math.floor(lot / 12) * 28)
    part:SetAttribute("PartId", partId)
    part.Parent = ship
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.OnReady) == "function"
        and type(services.PlayerDataManager.GetState) == "function",
        "Host player profiles required for installing spaceship parts")
    services.PlayerDataManager.OnReady(function(player)
        local profile = shipState(services, player)
        if not profile then return end
        recalc(player, profile)
        if type(profile.sections) ~= "table" then return end
        for slot, state in pairs(profile.sections) do
            if type(slot) == "string" and type(state) == "table"
                and state.owned == true and PARTS[state.partId]
                and PARTS[state.partId].slot == slot then
                partVisual(player, state.partId)
            end
        end
    end)
    Players.PlayerRemoving:Connect(function(player)
        local folder = workspace:FindFirstChild("RMMPlayerShips")
        local ship = folder and folder:FindFirstChild("RMMShip_" .. tostring(player.UserId))
        if ship then ship:Destroy() end
        local lot = lotsByPlayer[player]
        if lot ~= nil then
            occupiedLots[lot] = nil
            lotsByPlayer[player] = nil
        end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or
        player.Parent ~= Players then return reject("invalid_player") end
    local argc = select("#", ...)
    if argc ~= 1 and argc ~= 3 then return reject("bad_arity") end
    local action, partId, optionId = ...
    if type(action) ~= "string" then return reject("bad_action") end
    local mode = argc == 1 and "install" or action
    local requestedId = argc == 1 and action or partId
    local part = PARTS[requestedId]
    if not part then return reject("unknown_part") end
    local profile = shipState(services, player)
    local coins = readCoins(player)
    if not profile or not coins then return reject("profile_loading") end
    if profile.sections == nil then profile.sections = {} end
    if type(profile.sections) ~= "table" then return reject("invalid_ship_state") end
    local existing = profile.sections[part.slot]
    if existing ~= nil and (type(existing) ~= "table" or type(existing.owned) ~= "boolean") then
        return reject("invalid_slot_state")
    end
    local price
    local bonus = nil
    if mode == "install" and argc == 1 then
        if existing and existing.owned then return reject("occupied_slot") end
        price = part.cost
    elseif mode == "upgrade" and argc == 3 then
        if not existing or existing.owned ~= true or existing.partId ~= requestedId then
            return reject("not_owned")
        end
        if type(optionId) ~= "string" then return reject("bad_choice") end
        bonus = part.upgrades[optionId]
        if not bonus then return reject("unknown_upgrade") end
        if existing.upgrades ~= nil and type(existing.upgrades) ~= "table" then
            return reject("invalid_upgrade_state")
        end
        if existing.upgrades and existing.upgrades[optionId] ~= nil then
            return reject("already_upgraded")
        end
        price = bonus.cost
    else
        return reject("invalid_action")
    end
    if coins.Value < price then return reject("insufficient_currency") end
    -- One non-yielding in-server commit; host profile handles persistent saving.
    coins.Value -= price
    if mode == "install" then
        profile.sections[part.slot] = {owned = true, partId = requestedId, level = 1,
            upgrades = {}}
        partVisual(player, requestedId)
    else
        if existing.upgrades == nil then existing.upgrades = {} end
        existing.upgrades[optionId] = true
    end
    recalc(player, profile)
    return {success = true, partId = requestedId, slot = part.slot,
        credits = coins.Value, performance = player:GetAttribute("RMMShipPerformance"),
        action = mode}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local folder = ReplicatedStorage:WaitForChild("Remotes", 20)
if not folder then error("Missing Remotes") end
local remote = folder:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Missing part RemoteFunction") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipPartCatalog"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local scroll = Instance.new("ScrollingFrame")
scroll.Size = UDim2.fromOffset(305, 325)
scroll.Position = UDim2.new(1, -320, 0, 150)
scroll.CanvasSize = UDim2.fromOffset(0, 1900)
scroll.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = scroll
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 40)
status.Text = "Ship part catalog"
status.Parent = scroll
local parts = {
__PARTS__
}
local busy = false
local function request(...)
    if busy then return nil end
    busy = true
    local args = table.pack(...)
    local ok, response = pcall(function()
        return remote:InvokeServer(table.unpack(args, 1, args.n))
    end)
    busy = false
    return ok and type(response) == "table" and response or nil
end
for _, part in parts do
    local button = Instance.new("TextButton")
    button.Name = part.id
    button.Size = UDim2.new(1, 0, 0, 40)
    button.Text = part.label .. " (" .. part.slot .. ") - " .. tostring(part.cost) .. " Coins"
    button.Parent = scroll
    button.Activated:Connect(function()
        local result = request(part.id)
        status.Text = result and (result.success and
            ("Installed " .. result.partId .. "; performance " .. tostring(result.performance))
            or tostring(result.reason)) or "Network failure"
    end)
    for _, choice in part.upgrades do
        local upgrade = Instance.new("TextButton")
        upgrade.Name = part.id .. "_" .. choice.id
        upgrade.Size = UDim2.new(1, 0, 0, 30)
        upgrade.Text = choice.label .. " - " .. tostring(choice.cost) .. " Coins"
        upgrade.Parent = scroll
        upgrade.Activated:Connect(function()
            local result = request("upgrade", part.id, choice.id)
            status.Text = result and (result.success and
                ("Upgraded " .. result.partId .. "; performance " .. tostring(result.performance))
                or tostring(result.reason)) or "Network failure"
        end)
    end
end
'''