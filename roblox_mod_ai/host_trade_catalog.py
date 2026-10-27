"""Host-owned bounded catalog trading, including part entitlements.

The user specifies items/prices via tiny validated JSON, NOT executable Luau.
All offered categories share one profile ledger and serial server currency
transaction. A ship-section entitlement is a purchased item, not a fabricated
installed hull; actual placement remains the separately verified ship builder.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind
from .host_catalog_purchase import _ID
from .host_upgrade_declarative import _CLIENT as _CATALOG_UI

_SCHEMA = {"type": "object", "properties": {"items": {
    "type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "label": {"type": "string"},
        "category": {"type": "string", "enum": ["section", "weapon", "crew", "ship"]},
        "cost": {"type": "integer"}, "bonus": {"type": "integer"},
    }, "required": ["id", "label", "category", "cost", "bonus"]},
}}, "required": ["items"]}


def eligible_trade_catalog(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not getattr(module, "module_id", "").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    owner = next((row for row in getattr(proposal, "modules", ())
                  if row.kind == ModuleKind.SERVER_MODULE
                  and row.name == server), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    # Generic authorial obligations, never a filename, game title or name hash.
    required = (
        r"\bcatalog\b",
        r"\b(?:trade|trading|purchase|buy)\b",
        r"\b(?:currency|coins?|credits?)\b",
        r"\b(?:fixed|server[- ]priced|price|cost)\b",
        r"\b(?:validat|check|reject)\w*\b",
        r"\b(?:deduct|spend|charge)\w*\b",
        r"\b(?:grant|add|appl)\w*\b",
        r"\b(?:inventor|own|record|persist)\w*\b",
    )
    if not all(re.search(pattern, prose) for pattern in required):
        return None
    # Level-changing per-part transactions, inventories of actually INSTALLED
    # components and two-person trading have distinct protocols. Never
    # silently reinterpret them as a one-time item entitlement.
    if (re.search(r"\b(?:peer[- ]to[- ]peer|player[- ]to[- ]player)\b", prose)
            or re.search(r"\b(?:increment|decrement)\w*\s+(?:the\s+)?(?:ship|part)\s+level\b", prose)
            or re.search(r"\b(?:attach|install)\w*\s+(?:the\s+)?(?:section|part)\b", prose)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(remote, route) for remote, route in
              (design.get("host_actions") or {}).items()
              if isinstance(route, dict) and route.get("service") == server]
    if len(routes) != 1:
        return None
    remote, binding = routes[0]
    max_args = binding.get("max_args")
    if (binding.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (max_args is not None and (type(max_args) is not int or max_args < 1))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
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


def _required_categories(prose: str) -> set[str]:
    prose = prose.casefold()
    required = set()
    if re.search(r"\b(?:ship|spaceship)\s+sections?\b", prose):
        required.add("section")
    if re.search(r"\bweapons?\b", prose):
        required.add("weapon")
    if re.search(r"\bcrew\b", prose):
        required.add("crew")
    if re.search(r"\b(?:ship[- ]performance|ship\s+performance|ship\s+upgrades?)\b", prose):
        required.add("ship")
    return required


def _validate(raw: Any, required: set[str]) -> list[dict[str, Any]]:
    rows = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
        raise ValueError("TRADE_CATALOG_ITEMS_INVALID")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("TRADE_CATALOG_ITEM_INVALID")
        name, label = row.get("id"), row.get("label")
        category, cost, bonus = row.get("category"), row.get("cost"), row.get("bonus")
        if (not isinstance(name, str) or not _ID.fullmatch(name)
                or name.casefold() in seen or name.lower() in {"coins", "resources"}
                or not isinstance(label, str) or not 2 <= len(label.strip()) <= 52
                or category not in {"section", "weapon", "crew", "ship"}
                or type(cost) is not int or not 1 <= cost <= 1000000
                or type(bonus) is not int or not 0 <= bonus <= 1000):
            raise ValueError("TRADE_CATALOG_ITEM_FIELDS_INVALID")
        seen.add(name.casefold())
        result.append({"id": name, "label": label.strip(),
                       "category": category, "cost": cost, "bonus": bonus})
    if not required.issubset({row["category"] for row in result}):
        raise ValueError("TRADE_CATALOG_MISSING_REQUESTED_CATEGORIES: " +
                         ", ".join(sorted(required)))
    return result


def _read(proposal: Any, server: str, router: Any) -> list[dict[str, Any]]:
    cache = proposal.game_design.setdefault("_host_trade_catalogs", {})
    prose = next(module.description for module in proposal.modules if module.name == server)
    required = _required_categories(prose)
    if server in cache:
        return _validate({"items": cache[server]}, required)
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("TRADE_CATALOG_NEEDS_DECLARATIVE_MODEL")
    prompt = (
        "Return ONLY JSON {items:[{id,label,category,cost,bonus}]}, 1-8 entries. "
        "No code, Roblox API, free money, user-selected prices or remotes. "
        "Category: section (purchased entitlement, NOT installed ship part), "
        "weapon, crew, ship. Cost is positive integer earned game Coins, bonus "
        "is integer 0-1000. Each ID is an ASCII identifier, label 2-52 chars. "
        "Include at least one entry from EACH required category: "
        + ", ".join(sorted(required)) + ". Authored behavior: " + prose[:1100]
    )
    error = ""
    for _ in range(2):
        try:
            raw = router.complete_json(
                prompt + ("\nFix: " + error if error else ""),
                role="planner", temperature=0, max_tokens=1100,
                json_schema=_SCHEMA,
            )
            rows = _validate(raw, required)
            cache[server] = rows
            return rows
        except Exception as exc:
            error = str(exc)[:220]
    raise ValueError("TRADE_CATALOG_DATA_EXHAUSTED: " + error)


def try_trade_catalog(module: Any, proposal: Any, router: Any = None) -> str | None:
    route = eligible_trade_catalog(module, proposal)
    if route is None:
        return None
    server, remote = route
    rows = _read(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        entries = ",\n".join(
            "{id = " + json.dumps(row["id"]) + ", label = " +
            json.dumps(row["label"], ensure_ascii=False) +
            ", cost = " + str(row["cost"]) + "}" for row in rows
        )
        return _CATALOG_UI.replace("__REMOTE__", json.dumps(remote)).replace(
            "__UPGRADES__", entries)
    entries = ",\n".join(
        "[" + json.dumps(server + "/" + row["id"]) + "] = {kind = "
        + json.dumps(row["category"]) + ", cost = " + str(row["cost"])
        + ", bonus = " + str(row["bonus"]) + "}" for row in rows
    )
    # Preserve client-local item IDs. Server namespacing prevents accidental
    # cross-catalog collisions but cannot replace the actual ship builder ABI.
    aliases = ",\n".join(
        "[" + json.dumps(row["id"]) + "] = " +
        json.dumps(server + "/" + row["id"]) for row in rows)
    return _SERVER.replace("__ITEMS__", entries).replace("__ALIASES__", aliases)


_SERVER = r'''--!strict
-- One authoritative saved entitlement ledger across every trade catalog.
-- No source from the small model is compiled as Luau.
local Players = game:GetService("Players")
local Service = {}
local ITEMS = {
__ITEMS__
}
local ALIASES = {
__ALIASES__
}
local LIMIT = 2147483647
local function reject(reason)
    return {success = false, reason = reason}
end
local function purchases(player, services)
    local manager = services.PlayerDataManager
    if type(manager) ~= "table" or type(manager.GetState) ~= "function" then
        return nil
    end
    local owned = manager.GetState(player, "RMMTradeEntitlements")
    if type(owned) ~= "table" then return nil end
    return owned
end
local function publish(player, owned)
    local totals = {section = 0, weapon = 0, crew = 0, ship = 0}
    local count = 0
    -- Count saved entitlements across ALL host trade catalogs, not just this
    -- service. No other service may overwrite a category projection with a
    -- partial sum from its own item table.
    for _, item in pairs(owned) do
        if type(item) == "table" and item.purchased == true
            and type(item.kind) == "string"
            and type(item.bonus) == "number"
            and item.bonus % 1 == 0 and item.bonus >= 0
            and item.bonus <= 1000 and totals[item.kind] ~= nil then
            local contribution = item.bonus
            if item.kind == "section" then
                contribution = 1
            end
            totals[item.kind] = math.min(
                LIMIT, totals[item.kind] + contribution
            )
            count += 1
        end
    end
    player:SetAttribute("RMMTradeWeaponBonus", totals.weapon)
    player:SetAttribute("RMMTradeCrewBonus", totals.crew)
    player:SetAttribute("RMMTradeShipBonus", totals.ship)
    player:SetAttribute("RMMShipSectionLicenseCount", totals.section)
    player:SetAttribute("RMMTradePurchasedCount", count)
end
function Service.start(services)
    assert(type(services) == "table" and
        type(services.PlayerDataManager) == "table" and
        type(services.PlayerDataManager.GetState) == "function" and
        type(services.PlayerDataManager.OnReady) == "function",
        "Catalog trade needs the verified host profile")
    services.PlayerDataManager.OnReady(function(player)
        local owned = purchases(player, services)
        if owned then publish(player, owned) end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return reject("invalid_request")
    end
    local choice = ...
    if type(choice) ~= "string" then return reject("invalid_item") end
    local canonical = ALIASES[choice]
    if not canonical then return reject("unknown_item") end
    local item = ITEMS[canonical]
    if not item then return reject("unknown_item") end
    local owned = purchases(player, services)
    if not owned then return reject("profile_loading") end
    if owned[canonical] ~= nil then return reject("already_owned") end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value < 0
        or coins.Value > LIMIT then return reject("invalid_currency") end
    if coins.Value < item.cost then return reject("insufficient_currency") end
    -- No yield between authentic coin validation, debit and durable ownership.
    coins.Value -= item.cost
    owned[canonical] = {purchased = true, kind = item.kind, bonus = item.bonus}
    publish(player, owned)
    player:SetAttribute("RMMCurrencyBalance", coins.Value)
    return {success = true, purchased = choice, category = item.kind,
        currency = coins.Value, resultingBonus = item.bonus}
end
return Service
'''
