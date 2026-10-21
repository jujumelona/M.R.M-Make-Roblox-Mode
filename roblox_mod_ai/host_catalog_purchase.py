"""Host-owned game catalog purchase from small declarative model data.

The model selects only game-specific catalog items and prices. The host owns
Roblox APIs, currency, profile ownership, the server transaction, and UI.
Never turn a missing owned ship section into a successful purchase.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "cost": {"type": "integer"},
                    "slot": {"type": "string"},
                    "effect": {"type": "string", "enum": ["damage", "capacity", "speed", "shield"]},
                    "bonus": {"type": "integer"},
                },
                "required": ["id", "label", "cost", "slot", "effect", "bonus"],
            },
        },
    },
    "required": ["entries"],
}


def eligible_catalog_purchase(module: Any, proposal: Any) -> tuple[str, str] | None:
    """Require an authored currency purchase and actual ship ownership contract."""
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
    description = owner.description.casefold()
    original_contract = (
        re.search(r"\b(?:purchas(?:e|es|ing)|buy|buying)\b", description)
        and "catalog" in description
        and re.search(r"\b(?:currency|coins?|credits?)\b", description)
        and re.search(r"\b(?:spaceship|ship)\s+(?:parts?|upgrades?)\b", description)
        and re.search(r"\b(?:own|owned|ownership)\b", description)
        and re.search(r"\b(?:validat|verif|check|reject)\w*\b", description)
    )
    # A priced ship upgrade may describe an owned server-side catalog but
    # not explicitly repeat "ship ownership". Require an independently
    # verified host builder instead; its installed slot is checked at runtime.
    from .host_ship_part_catalog import eligible_ship_part_catalog
    builders = [peer for peer in proposal.modules
                if peer is not owner and peer.kind == ModuleKind.SERVER_MODULE
                and eligible_ship_part_catalog(peer, proposal) is not None]
    paired_upgrade = (
        len(builders) == 1
        and re.search(r"\bship\s+upgrades?\b", description)
        and re.search(r"\bcatalog\b", description)
        and re.search(r"\b(?:purchas\w*|deduct\w*)\b", description)
        and re.search(r"\b(?:currency|coins?|credits?)\b", description)
        and re.search(r"\b(?:fixed\s+cost|cost|price)\b", description)
        and re.search(r"\b(?:corresponding\s+part|ship\s+part|owned\s+part)\b", description)
        and re.search(r"\b(?:performance|bonus)\b", description)
        and re.search(r"\b(?:validat|check|reject)\w*\b", description)
    )
    if not (original_contract or paired_upgrade):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    bound = [(k, v) for k, v in (design.get("host_actions") or {}).items()
             if isinstance(v, dict) and v.get("service") == server]
    if (len(bound) != 1 or bound[0][1].get("kind") != "RemoteFunction"
            or bound[0][1].get("max_args") == 0
            or (design.get("remotes") or {}).get(bound[0][0]) != "RemoteFunction"):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if (not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        linked = (design.get("module_remotes") or {}).get(module.module_id)
        if linked is not None and bound[0][0] not in linked:
            return None
    return server, bound[0][0]


def _validated_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise ValueError("Catalog model must return entries array")
    entries = value["entries"]
    if not 1 <= len(entries) <= 6:
        raise ValueError("Catalog needs 1-6 authored items")
    known = set()
    clean = []
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError("Catalog entry must be an object")
        name, label, slot = row.get("id"), row.get("label"), row.get("slot")
        cost, bonus, effect = row.get("cost"), row.get("bonus"), row.get("effect")
        if (not isinstance(name, str) or not _ID.fullmatch(name) or name in known
                or name.casefold() in {"coins", "resources"}
                or not isinstance(label, str) or not 2 <= len(label.strip()) <= 54
                or not isinstance(slot, str) or not _ID.fullmatch(slot)
                or type(cost) is not int or not 1 <= cost <= 1000000
                or type(bonus) is not int or not 1 <= bonus <= 1000
                or effect not in {"damage", "capacity", "speed", "shield"}):
            raise ValueError("Invalid catalog item id, cost, slot, or approved stat effect")
        known.add(name)
        clean.append({"id": name, "label": label.strip(), "slot": slot,
                      "cost": cost, "bonus": bonus, "effect": effect})
    return clean


def _read_catalog(proposal: Any, server: str, router: Any) -> list[dict[str, Any]]:
    # Code generator runs owner before client. Cache the validated game-specific
    # configuration so both modules share exactly the same catalog.
    catalogs = proposal.game_design.setdefault("_host_declarative_catalogs", {})
    # Purchase choices must use installed part slots authored by the build
    # system, not a second set of invented identifiers. This metadata exists
    # when a prior host ship-part service has produced its validated catalog.
    part_catalogs = proposal.game_design.get("_host_ship_part_catalogs") or {}
    actual_slots = sorted({part["slot"] for rows in part_catalogs.values()
                           if isinstance(rows, list) for part in rows
                           if isinstance(part, dict) and isinstance(part.get("slot"), str)})
    # A purchase service can be topologically ordered before its ship
    # constructor. Pre-author exactly the constructor's short *data* catalog,
    # then reuse that cache when the constructor is generated later.
    # This never executes model-authored Luau or creates imaginary owned parts.
    if not actual_slots:
        from .host_ship_part_catalog import eligible_ship_part_catalog, _catalog
        builders = [m for m in proposal.modules
                    if m.kind == ModuleKind.SERVER_MODULE and m.name != server
                    and eligible_ship_part_catalog(m, proposal) is not None]
        if len(builders) == 1 and router is not None:
            parts = _catalog(proposal, builders[0].name, router)
            actual_slots = sorted({part["slot"] for part in parts})
    if server in catalogs:
        cached = _validated_entries({"entries": catalogs[server]})
        if actual_slots and any(item["slot"] not in actual_slots for item in cached):
            raise ValueError("Cached purchase catalog references missing ship section slot")
        return cached
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("A declarative catalog requires small JSON model output")
    owner = next(m for m in proposal.modules if m.name == server)
    # Purchase choices must use installed part slots authored by the build
    # system, not a second set of invented identifiers. This metadata exists
    # when a prior host ship-part service has produced its validated catalog.
    part_catalogs = proposal.game_design.get("_host_ship_part_catalogs") or {}
    actual_slots = sorted({part["slot"] for rows in part_catalogs.values()
                           if isinstance(rows, list) for part in rows
                           if isinstance(part, dict) and isinstance(part.get("slot"), str)})
    # A purchase service can be topologically ordered before its ship
    # constructor. Pre-author exactly the constructor's short *data* catalog,
    # then reuse that cache when the constructor is generated later.
    # This never executes model-authored Luau or creates imaginary owned parts.
    if not actual_slots:
        from .host_ship_part_catalog import eligible_ship_part_catalog, _catalog
        builders = [m for m in proposal.modules
                    if m.kind == ModuleKind.SERVER_MODULE and m.name != server
                    and eligible_ship_part_catalog(m, proposal) is not None]
        if len(builders) == 1 and router is not None:
            parts = _catalog(proposal, builders[0].name, router)
            actual_slots = sorted({part["slot"] for part in parts})
    instructions = (
        "Return ONLY a short JSON list of 1-6 purchasable GAME-SPECIFIC "
        "catalog entries; this is DATA, NOT Luau code. Each entry needs "
        "id (ASCII identifier), label, cost (positive earned game coins), "
        "slot (matching the ship section the player must ALREADY own), "
        "effect (damage, capacity, speed, shield), bonus (positive integer). "
        "Do not invent Roblox methods, code, remotes, game currency grants, "
        "or engine boilerplate. Gameplay requirement: " + owner.description[:900]
        + ("\nApproved actual ship section slot IDs (choose ONLY these): "
           + ", ".join(actual_slots) if actual_slots else "")
    )
    last_error = ""
    for _ in range(2):
        try:
            raw = router.complete_json(
                instructions + ("\nValidation error: " + last_error if last_error else ""),
                role="planner", temperature=0.0, max_tokens=700,
                json_schema=_SCHEMA,
            )
            values = _validated_entries(raw)
            if actual_slots and any(item["slot"] not in actual_slots for item in values):
                raise ValueError("Purchase item refers to a slot never installed by the host ship catalog; "
                                 "approved slots: " + ", ".join(actual_slots))
            catalogs[server] = values
            return values
        except Exception as exc:
            last_error = str(exc)[:350]
    raise ValueError("HOST_DECLARATIVE_CATALOG_EXHAUSTED: " + last_error)


def try_catalog_purchase(module: Any, proposal: Any, router: Any = None) -> str | None:
    route = eligible_catalog_purchase(module, proposal)
    if route is None:
        return None
    server, remote = route
    entries = _read_catalog(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        lua_entries = ",\n".join(
            "{id = " + json.dumps(item["id"]) +
            ", label = " + json.dumps(item["label"], ensure_ascii=False) +
            ", cost = " + str(item["cost"]) + "}"
            for item in entries
        )
        return _CLIENT.replace("__REMOTE__", json.dumps(remote)).replace(
            "__CATALOG__", lua_entries)
    lua_entries = ",\n".join(
        "[" + json.dumps(item["id"]) + "] = {cost = " + str(item["cost"]) +
        ", slot = " + json.dumps(item["slot"]) +
        ", effect = " + json.dumps(item["effect"]) +
        ", bonus = " + str(item["bonus"]) + "}"
        for item in entries
    )
    return _SERVER.replace("__CATALOG__", lua_entries)


_SERVER = r'''--!strict
-- Host-authored catalog transaction and ownership enforcement.
local Players = game:GetService("Players")
local Service = {}
local CATALOG = {
__CATALOG__
}
local recent = setmetatable({}, {__mode = "k"})
local ATTRIBUTE = {
    damage = "RMMWeaponDamageBonus",
    capacity = "RMMCrewCapacityBonus",
    speed = "RMMShipSpeedBonus",
    shield = "RMMShipShieldBonus",
}
function Service.start(services)
    assert(type(services) == "table" and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Catalog purchases require existing host profile")
    services.PlayerDataManager.OnReady(function(player)
        local purchased = services.PlayerDataManager.GetState(player, "RMMCatalogPurchases")
        if not purchased then return end
        for name, entry in pairs(CATALOG) do
            if purchased[name] == true then
                local attr = ATTRIBUTE[entry.effect]
                player:SetAttribute(attr, (player:GetAttribute(attr) or 0) + entry.bonus)
            end
        end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or
        player.Parent ~= Players or select("#", ...) ~= 1 then return false end
    local itemId = ...
    if type(itemId) ~= "string" then return false end
    local item = CATALOG[itemId]
    if not item then return false end
    local profile = services.PlayerDataManager
    local purchased = profile.GetState(player, "RMMCatalogPurchases")
    local ship = profile.GetState(player, "RMMShipSections")
    if not purchased or not ship or type(ship.sections) ~= "table" then return false end
    local section = ship.sections[item.slot]
    if type(section) ~= "table" or section.owned ~= true then return false end
    if purchased[itemId] ~= nil then return false end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value < item.cost
        or coins.Value < 0 then return false end
    local now = os.clock()
    if recent[player] and now - recent[player] < 0.25 then return false end
    recent[player] = now
    -- No yield after checking the real owned section or server currency.
    coins.Value -= item.cost
    purchased[itemId] = true
    local attr = ATTRIBUTE[item.effect]
    player:SetAttribute(attr, (player:GetAttribute(attr) or 0) + item.bonus)
    return {success = true, purchased = itemId, credits = coins.Value}
end
return Service
'''

_CLIENT = r'''--!strict
-- Host-owned presentation; model does not generate Remote or GUI code.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local folder = ReplicatedStorage:WaitForChild("Remotes", 20)
if not folder then error("Missing host Remotes") end
local remote = folder:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Invalid catalog Remote") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMCatalogPurchasePanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.fromOffset(250, 300)
panel.Position = UDim2.new(1, -265, 0, 160)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 38)
status.Text = "Select a purchase"
status.Parent = panel
local catalog = {
__CATALOG__
}
local busy = false
for _, item in catalog do
    local button = Instance.new("TextButton")
    button.Name = item.id
    button.Size = UDim2.new(1, 0, 0, 42)
    button.Text = item.label .. " - " .. tostring(item.cost) .. " Coins"
    button.Parent = panel
    button.Activated:Connect(function()
        if busy then return end
        busy = true
        local ok, result = pcall(function() return remote:InvokeServer(item.id) end)
        busy = false
        if ok and type(result) == "table" and result.success == true then
            button.Active = false
            button.Text = item.label .. " (owned)"
            status.Text = "Purchased; Coins: " .. tostring(result.credits)
        else
            status.Text = "Purchase rejected: currency, ship ownership or duplication"
        end
    end)
end
'''