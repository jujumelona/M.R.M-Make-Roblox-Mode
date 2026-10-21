"""Host coin-purchased ship upgrades bound to an actually owned ship part.

The small model supplies short item data and stat-effect labels, never code.
The host verifies the prebuilt catalog ID, real saved part ownership, Coins,
single-use purchases, persistent upgrade state and derived gameplay attributes.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_catalog_purchase import _ID
from .host_capped_ship_parts import eligible_capped_ship_parts, _validate as _valid_parts
from .host_ship_hierarchy import eligible_ship_hierarchy, _validate as _valid_hierarchy
from .spec import ModuleKind

_SCHEMA = {
    "type": "object",
    "properties": {"upgrades": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "string"}, "label": {"type": "string"},
            "targetPart": {"type": "string"},
            "effect": {"type": "string", "enum": ["weapon", "crew", "hull", "ship"]},
            "cost": {"type": "integer"}, "bonus": {"type": "integer"},
        },
        "required": ["id", "label", "targetPart", "effect", "cost", "bonus"],
    }}},
    "required": ["upgrades"],
}


def eligible_ship_owned_upgrades(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((m for m in getattr(proposal, "modules", [])
                  if m.name == server and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
    prose = owner.description.casefold()
    general_purchase = (
        re.search(r"\bupgrades?\b", prose)
        and re.search(r"\bpurchas\w*\b", prose)
        and re.search(r"\b(?:ship|spaceship)\b", prose)
        and re.search(r"\b(?:currency|coins?|credits?)\b", prose)
        and re.search(r"\b(?:weapon|crew|hull)\b", prose)
        and re.search(r"\b(?:validat|check|reject)\w*\b", prose)
        and re.search(r"\b(?:persist|save|datastore)\w*\b", prose)
    )
    section_expansion = (
        re.search(r"\b(?:upgrade|expansion)\b", prose)
        and re.search(r"\bship\s+part\b", prose)
        and re.search(r"\b(?:currency|coins?|credits?)\b", prose)
        and re.search(r"\b(?:allow(?:ed)?\s+upgrade\s+list|allowed\s+upgrade)\b", prose)
        and re.search(r"\b(?:duplicate|already-maxed)\b", prose)
        and re.search(r"\b(?:persistent|persist|save)\b", prose)
        and re.search(r"\b(?:validat|reject)\w*\b", prose)
    )
    if not (general_purchase or section_expansion):
        return None
    # Only a real host-produced part catalog may back an upgrade. Never grant
    # a target part because the model invented its ID in this module.
    from .host_ship_hierarchy import eligible_ship_hierarchy
    builders = [
        p for p in getattr(proposal, "modules", ())
        if p.kind == ModuleKind.SERVER_MODULE and p.name != server
        and ((general_purchase and eligible_capped_ship_parts(p, proposal) is not None)
             or (section_expansion and eligible_ship_hierarchy(p, proposal) is not None))
    ]
    if len(builders) != 1:
        return None
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


def _validate(value: Any, actual_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("upgrades"), list):
        raise ValueError("Upgrade catalogue requires upgrades list")
    rows = value["upgrades"]
    if not 1 <= len(rows) <= 8:
        raise ValueError("Upgrade catalogue requires 1-8 choices")
    seen = set()
    output = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid upgrade entry")
        uid, label, target = row.get("id"), row.get("label"), row.get("targetPart")
        effect, price, bonus = row.get("effect"), row.get("cost"), row.get("bonus")
        if (not isinstance(uid, str) or not _ID.fullmatch(uid)
                or uid.casefold() in seen
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 54
                or target not in actual_ids
                or effect not in ("weapon", "crew", "hull", "ship")
                or type(price) is not int or not 1 <= price <= 1000000
                or type(bonus) is not int or not 1 <= bonus <= 100):
            raise ValueError("Upgrade must target a real available part with safe ID, cost and bonus")
        seen.add(uid.casefold())
        output.append({"id": uid, "label": label.strip(), "targetPart": target,
                       "effect": effect, "cost": price, "bonus": bonus})
    return output


def _read(proposal: Any, owner: str, router: Any) -> list[dict[str, Any]]:
    builders = [
        m for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE
        and (eligible_capped_ship_parts(m, proposal) is not None
             or eligible_ship_hierarchy(m, proposal) is not None)
    ]
    if len(builders) != 1:
        raise ValueError("Upgrade requires exactly one real host-owned ship builder")
    builder = builders[0]
    if eligible_capped_ship_parts(builder, proposal) is not None:
        build_data = (proposal.game_design.get("_host_capped_ship_parts") or {}).get(builder.name)
        if build_data is None:
            raise ValueError("HOST_SHIP_UPGRADE_MISSING_PART_CATALOG: generate ship builder first")
        actual = {p["id"] for p in _valid_parts(build_data)["parts"]}
    else:
        build_data = (proposal.game_design.get("_host_ship_hierarchy") or {}).get(builder.name)
        if build_data is None:
            raise ValueError("HOST_SHIP_UPGRADE_MISSING_PART_CATALOG: generate ship hierarchy first")
        actual = {p["id"] for p in _valid_hierarchy(build_data)["sections"]}
    store = proposal.game_design.setdefault("_host_ship_owned_upgrades", {})
    if owner in store:
        return _validate({"upgrades": store[owner]}, actual)
    if router is None or not hasattr(router, "complete_json"):
        raise ValueError("Upgrade data must be supplied as validated game-specific rules")
    requirement = next(m.description for m in proposal.modules if m.name == owner)
    prompt = (
        "Output ONLY JSON {upgrades:[{id,label,targetPart,effect,cost,bonus}]}; "
        "1-8 single-use upgrades. targetPart MUST be one of these actual "
        "host-built ship part IDs: " + json.dumps(sorted(actual)) +
        ". effect is weapon, crew, hull or ship; cost is positive earned Coins, bonus "
        "integer 1-100. Do NOT output Luau, Roblox APIs, code, profiles, "
        "invented parts, or unauthorized purchasing methods. Requirement: " +
        requirement[:900]
    )
    last = ""
    for _ in range(2):
        try:
            answer = router.complete_json(
                prompt + ("\nFix data: " + last if last else ""),
                role="planner",temperature=0,max_tokens=900,json_schema=_SCHEMA,
            )
            data = _validate(answer, actual)
            store[owner] = data
            return data
        except Exception as exc:
            last = str(exc)[:240]
    raise ValueError("HOST_OWNED_SHIP_UPGRADES_EXHAUSTED: " + last)


def try_ship_owned_upgrades(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_ship_owned_upgrades(module, proposal)
    if selected is None:
        return None
    owner, remote = selected
    choices = _read(proposal, owner, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        rows = ",\n".join(
            "{id = " + json.dumps(x["id"]) + ", label = " +
            json.dumps(x["label"], ensure_ascii=False) + ", cost = " +
            str(x["cost"]) + ", bonus = " + str(x["bonus"]) + "}"
            for x in choices
        )
        return _CLIENT.replace("__REMOTE__",json.dumps(remote)).replace("__UPGRADES__",rows)
    rows = ",\n".join(
        "[" + json.dumps(x["id"]) + "] = {part = " + json.dumps(x["targetPart"]) +
        ", effect = " + json.dumps(x["effect"]) + ", cost = " + str(x["cost"]) +
        ", bonus = " + str(x["bonus"]) + "}" for x in choices
    )
    return _SERVER.replace("__UPGRADES__",rows)


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local CHOICES = {
__UPGRADES__
}
local ATTRIBUTES = {
    weapon = "RMMWeaponDamageBonus",
    crew = "RMMCrewCapacityBonus",
    hull = "RMMShipShieldBonus",
    ship = "RMMShipPurchasedPerformanceBonus",
}
local LIMIT = 2147483647
local function report(player, purchases)
    local weapon, crew, hull, ship = 0, 0, 0, 0
    local present = {}
    for id, item in pairs(CHOICES) do
        present[item.effect] = true
        local saved = purchases[id]
        if type(saved) == "table" and saved.owned == true
            and saved.targetPart == item.part then
            if item.effect == "weapon" then weapon += item.bonus
            elseif item.effect == "crew" then crew += item.bonus
            elseif item.effect == "hull" then hull += item.bonus
            elseif item.effect == "ship" then ship += item.bonus end
        end
    end
    if present.weapon then player:SetAttribute(ATTRIBUTES.weapon, weapon) end
    if present.crew then player:SetAttribute(ATTRIBUTES.crew, crew) end
    if present.hull then player:SetAttribute(ATTRIBUTES.hull, hull) end
    if present.ship then player:SetAttribute(ATTRIBUTES.ship, ship) end
    player:SetAttribute("RMMShipUpgradeScore", weapon + crew + hull + ship)
    return weapon + crew + hull + ship
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Ship upgrade purchase requires host profile")
    services.PlayerDataManager.OnReady(function(player)
        local owned = services.PlayerDataManager.GetState(player, "RMMUpgradePurchases")
        if type(owned) == "table" then report(player, owned) end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_player"}
    end
    local id = ...
    if type(id) ~= "string" then return {success = false, reason = "invalid_choice"} end
    local item = CHOICES[id]
    if not item then return {success = false, reason = "invalid_choice"} end
    local manager = services.PlayerDataManager
    local parts = manager.GetState(player, "RMMShipSections")
    local purchases = manager.GetState(player, "RMMUpgradePurchases")
    if not parts or not purchases then return {success = false, reason = "profile_loading"} end
    if type(parts.sections) ~= "table" then
        return {success = false, reason = "ship_not_built"}
    end
    local installed = parts.sections[item.part]
    if type(installed) ~= "table" or installed.owned ~= true then
        return {success = false, reason = "part_not_owned"}
    end
    if purchases[id] ~= nil then
        return {success = false, reason = "already_purchased"}
    end
    local stats = player:FindFirstChild("leaderstats")
    local coins = stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value < item.cost
        or coins.Value < 0 or coins.Value > LIMIT then
        return {success = false, reason = "insufficient_currency"}
    end
    -- Single-use, non-yielding server-authoritative spend/ownership transition.
    coins.Value -= item.cost
    purchases[id] = {owned = true, targetPart = item.part,
        effect = item.effect, bonus = item.bonus}
    local score = report(player, purchases)
    return {success = true, purchased = id,
        coins = coins.Value, bonus = item.bonus, upgradeScore = score}
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
if not remote or not remote:IsA("RemoteFunction") then
    error("Ship upgrade RemoteFunction unavailable")
end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMOwnedShipUpgrades"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("ScrollingFrame")
panel.Size = UDim2.fromOffset(290, 290)
panel.Position = UDim2.new(1, -310, 0, 170)
panel.CanvasSize = UDim2.fromOffset(0, 900)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local resultText = Instance.new("TextLabel")
resultText.Size = UDim2.new(1, 0, 0, 40)
resultText.Text = "Choose an upgrade for an owned ship part"
resultText.Parent = panel
local catalog = {
__UPGRADES__
}
local busy = false
for _, upgrade in catalog do
    local btn = Instance.new("TextButton")
    btn.Name = upgrade.id
    btn.Size = UDim2.new(1, 0, 0, 40)
    btn.Text = upgrade.label .. " +" .. tostring(upgrade.bonus)
        .. " | " .. tostring(upgrade.cost) .. " Coins"
    btn.Parent = panel
    btn.Activated:Connect(function()
        if busy then return end
        busy = true
        resultText.Text = "Checking ship part and currency..."
        local ok, response = pcall(function()
            return remote:InvokeServer(upgrade.id)
        end)
        busy = false
        if ok and type(response) == "table" and response.success == true then
            btn.Active = false
            btn.Text = upgrade.label .. " (owned)"
            resultText.Text = "Upgrade score: " .. tostring(response.upgradeScore)
                .. " | Coins: " .. tostring(response.coins)
        else
            resultText.Text = "Rejected: " .. tostring(
                ok and type(response) == "table" and response.reason or "network")
        end
    end)
end
'''