"""Declarative earned-currency upgrade catalog with host-owned transactions.

Covers independent weapon/crew/vehicle upgrade purchases, not section assembly
or level/capacity expansion. The tiny model supplies bounded catalog data, not
Luau, player data access or purchase handlers.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_catalog_purchase import _ID
from .spec import ModuleKind


_SCHEMA = {
    "type": "object", "properties": {
        "upgrades": {"type": "array", "items": {"type": "object",
            "properties": {
                "id": {"type": "string"}, "label": {"type": "string"},
                "category": {"type": "string", "enum": ["weapon", "crew", "ship"]},
                "cost": {"type": "integer"}, "bonus": {"type": "integer"},
            }, "required": ["id", "label", "category", "cost", "bonus"]}},
    }, "required": ["upgrades"],
}


def eligible_declarative_upgrade(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    owner_name = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", ())
                  if m.name == owner_name and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
    desc = owner.description.casefold()
    if (not re.search(r"\bpurchas\w*\b", desc)
            or not re.search(r"\bupgrades?\b", desc)
            or not re.search(r"\bweapon\b", desc)
            or not re.search(r"\bcrew\b", desc)
            or not re.search(r"\b(?:ship|spaceship)\b", desc)
            or not re.search(r"\bperformance\b", desc)
            or not re.search(r"\b(?:currency|coins?|credits?)\b", desc)
            or not re.search(r"\b(?:validat|check)\w*\b", desc)
            or not re.search(r"\b(?:deduct|spend|cost)\w*\b", desc)
            or not re.search(r"\b(?:owned|record|persistent|session)\w*\b", desc)):
        return None
    # The existing ship-specific part-upgrade renderer takes precedence if
    # it owns exactly the required part source and purchase transport.
    from .host_ship_owned_upgrades import eligible_ship_owned_upgrades
    if eligible_ship_owned_upgrades(module, proposal) is not None:
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(key, value) for key, value in (design.get("host_actions") or {}).items()
              if isinstance(value, dict) and value.get("service") == owner_name]
    if len(routes) != 1:
        return None
    remote, action = routes[0]
    max_args = action.get("max_args")
    if (action.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (max_args is not None and
                (type(max_args) is not int or max_args < 1))):
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
        if linked is not None and remote not in linked:
            return None
    return owner_name, remote


def _validate(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("upgrades"), list):
        raise ValueError("DECLARATIVE_UPGRADE_LIST_REQUIRED")
    choices = value["upgrades"]
    if not 1 <= len(choices) <= 8:
        raise ValueError("DECLARATIVE_UPGRADE_COUNT_INVALID")
    result, known = [], set()
    for choice in choices:
        if not isinstance(choice, dict):
            raise ValueError("DECLARATIVE_UPGRADE_INVALID")
        uid, label = choice.get("id"), choice.get("label")
        kind, cost, bonus = choice.get("category"), choice.get("cost"), choice.get("bonus")
        if (not isinstance(uid, str) or not _ID.fullmatch(uid)
                or uid.casefold() in known
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 55
                or kind not in ("weapon", "crew", "ship")
                or type(cost) is not int or not 1 <= cost <= 1000000
                or type(bonus) is not int or not 1 <= bonus <= 1000):
            raise ValueError("DECLARATIVE_UPGRADE_INVALID")
        known.add(uid.casefold())
        result.append({"id": uid, "label": label.strip(), "category": kind,
                       "cost": cost, "bonus": bonus})
    return result


def _read(proposal: Any, owner: str, router: Any) -> list[dict[str, Any]]:
    cache = proposal.game_design.setdefault("_host_general_upgrades", {})
    if owner in cache:
        return _validate({"upgrades": cache[owner]})
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("DECLARATIVE_UPGRADE_CATALOG_UNAVAILABLE")
    description = next(m.description for m in proposal.modules if m.name == owner)
    prompt = (
        "Return ONLY JSON {upgrades:[{id,label,category,cost,bonus}]}. "
        "1-8 actual purchasable independent upgrades. category is one of "
        "weapon, crew, ship; cost is a positive integer in the game's earned "
        "currency; bonus is a positive integer 1-1000. Keep stable ASCII IDs. "
        "These purchases are ONE TIME per profile and may only be applied "
        "by the server after balance/ownership validation. NO Lua/Luau, "
        "Roblox APIs, invented server methods, Remote handlers or extra state "
        "types. Authored upgrade requirement: " + description[:1000]
    )
    problem = ""
    for _ in range(2):
        try:
            data = router.complete_json(prompt + (
                "\nFix rejected JSON: " + problem if problem else ""),
                role="planner", temperature=0, max_tokens=850, json_schema=_SCHEMA,
            )
            rows = _validate(data)
            cache[owner] = rows
            return rows
        except Exception as exc:
            problem = str(exc)[:210]
    raise ValueError("DECLARATIVE_UPGRADE_CATALOG_EXHAUSTED: " + problem)


def try_declarative_upgrade(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_declarative_upgrade(module, proposal)
    if selected is None:
        return None
    owner, remote = selected
    rows = _read(proposal, owner, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        entries = ",\n".join(
            "{id = " + json.dumps(item["id"]) + ", label = " +
            json.dumps(item["label"], ensure_ascii=False) + ", cost = " +
            str(item["cost"]) + "}" for item in rows
        )
        return _CLIENT.replace("__REMOTE__", json.dumps(remote)).replace("__UPGRADES__", entries)
    entries = ",\n".join(
        "[" + json.dumps(item["id"]) + "] = {kind = " +
        json.dumps(item["category"]) + ", cost = " + str(item["cost"]) +
        ", bonus = " + str(item["bonus"]) + "}" for item in rows
    )
    return _SERVER.replace("__UPGRADES__", entries)


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local CATALOG = {
__UPGRADES__
}
local LIMIT = 2147483647
local PROJECTION = {
    weapon = "RMMWeaponDamageBonus",
    crew = "RMMCrewCapacityBonus",
    ship = "RMMGeneralPurchasedShipPower",
}
local function reject(reason) return {success = false, reason = reason} end
local function validPlayer(player)
    return typeof(player) == "Instance" and player:IsA("Player")
        and player.Parent == Players
end
local function getPurchases(player, services)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return nil
    end
    local rows = manager.GetState(player, "RMMUpgradePurchases")
    if type(rows) ~= "table" then return nil end
    return rows
end
local function publish(player, purchases)
    local totals = {weapon = 0, crew = 0, ship = 0}
    for id, item in pairs(CATALOG) do
        local record = purchases[id]
        if type(record) == "table" and record.owned == true
            and record.kind == item.kind and record.bonus == item.bonus then
            totals[item.kind] = math.min(LIMIT, totals[item.kind] + item.bonus)
        end
    end
    for kind, attribute in pairs(PROJECTION) do
        player:SetAttribute(attribute, totals[kind])
    end
    player:SetAttribute("RMMGeneralPurchasedUpgradeCount", 0)
    local count = 0
    for id in pairs(CATALOG) do
        local record = purchases[id]
        if type(record) == "table" and record.owned == true then count += 1 end
    end
    player:SetAttribute("RMMGeneralPurchasedUpgradeCount", count)
    return totals
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Purchases require authoritative persistent currency profile")
    services.PlayerDataManager.OnReady(function(player)
        local purchases = getPurchases(player, services)
        if purchases then publish(player, purchases) end
    end)
end
function Service.handleAction(player, services, ...)
    if not validPlayer(player) or select("#", ...) ~= 1 then
        return reject("invalid_request")
    end
    local id = ...
    if type(id) ~= "string" then return reject("invalid_item") end
    local item = CATALOG[id]
    if not item then return reject("unknown_upgrade") end
    local purchases = getPurchases(player, services)
    if not purchases then return reject("profile_loading") end
    if purchases[id] ~= nil then return reject("already_purchased") end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue")
        or coins.Value < 0 or coins.Value > LIMIT then return reject("invalid_currency") end
    if coins.Value < item.cost then return reject("insufficient_currency") end
    -- Final validation and saved purchase mutation occur without yielding.
    coins.Value -= item.cost
    purchases[id] = {owned = true, kind = item.kind, bonus = item.bonus}
    local totals = publish(player, purchases)
    player:SetAttribute("RMMCurrencyBalance", coins.Value)
    return {success = true, purchased = id, currency = coins.Value,
        category = item.kind, bonus = item.bonus,
        resultingBonus = totals[item.kind]}
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
if not remote or not remote:IsA("RemoteFunction") then
    error("Wrong purchase Remote")
end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMGeneralUpgradeCatalog"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("ScrollingFrame")
panel.Size = UDim2.fromOffset(280, 300)
panel.Position = UDim2.new(1, -296, 0, 150)
panel.CanvasSize = UDim2.fromOffset(0, 650)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 45)
status.Text = "Server-confirmed weapon, crew and ship upgrades"
status.Parent = panel
local catalog = {
__UPGRADES__
}
local busy = false
for _, upgrade in catalog do
    local button = Instance.new("TextButton")
    button.Name = upgrade.id
    button.Size = UDim2.new(1, 0, 0, 40)
    button.Text = upgrade.label .. " / " .. tostring(upgrade.cost) .. " Coins"
    button.Parent = panel
    button.Activated:Connect(function()
        if busy then return end
        busy = true
        status.Text = "Server validating purchase..."
        local ok, result = pcall(function()
            return remote:InvokeServer(upgrade.id)
        end)
        busy = false
        if ok and type(result) == "table" and result.success == true then
            button.Active = false
            button.Text = upgrade.label .. " (owned)"
            status.Text = "Confirmed " .. result.purchased
                .. " | Coins " .. tostring(result.currency)
                .. " | Category bonus " .. tostring(result.resultingBonus)
        else
            status.Text = "Rejected: " .. tostring(
                ok and type(result) == "table" and result.reason or "network")
        end
    end)
end
'''