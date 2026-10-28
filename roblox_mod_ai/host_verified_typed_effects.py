"""Fail-closed host compiler for three bounded typed server effects.

This adapter is selected by a validated Remote contract, source-owned world
binding, and an explicit behavioral signature. The small coder never writes
Luau for a recognized effect. This is intentionally not a general-purpose
claim that arbitrary natural-language behavior has been implemented.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind
from .typed_action_contract import validate_contract, lua_server_guard


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.casefold())


def _selected_world(module: Any, design: dict, descriptions: list[str]) -> str | None:
    """Resolve exactly one physical Part from the source-owned world contract."""
    owned = (design.get("module_world_objects") or {}).get(module.module_id, [])
    matches = []
    for item in design.get("world_objects") or []:
        if not isinstance(item, dict) or item.get("class") != "Part":
            continue
        name = item.get("name")
        if not isinstance(name, str) or name not in owned:
            continue
        normalized = _normalized(name)
        if any(len(_normalized(alias)) >= 12
               and (normalized.startswith(_normalized(alias)[:12])
                    or _normalized(alias).startswith(normalized[:12]))
               for alias in descriptions):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


def eligible_verified_effect(module: Any, proposal: Any) -> tuple[str, str, str | None, str | None] | None:
    """Match only typed one-remote actions with real owned runtime dependencies."""
    if (module.kind != ModuleKind.SERVER_MODULE
            or not module.module_id.startswith("dyn_")
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    design = (proposal.game_design or {}).get("dynamic_design") or {}
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if not isinstance(linked, list) or len(linked) != 1:
        return None
    remote = linked[0]
    route = (design.get("host_actions") or {}).get(remote)
    typed = (design.get("host_typed_actions") or {}).get(remote)
    if (not isinstance(route, dict) or route.get("service") != module.name
            or route.get("kind") != "RemoteFunction" or route.get("max_args") != 1
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or not isinstance(typed, dict) or typed.get("server") != module.name
            or typed.get("transport_only") is not True):
        return None
    clients = [m for m in proposal.modules
               if m.kind == ModuleKind.CLIENT_SCRIPT
               and m.name == typed.get("client")
               and (design.get("module_remotes") or {}).get(m.module_id) == [remote]
               and m.file_path.startswith("src/client/")
               and m.file_path.endswith(".client.luau")]
    if len(clients) != 1:
        return None
    contract = validate_contract(typed.get("contract"),
                                 world_entities=typed.get("world_entities") or [],
                                 transport_only=True)
    if (contract["target"] != {"kind": "none"}
            or contract["state_changes"]
            or [(field["id"], field["type"]) for field in contract["inputs"]]
            != [("selection", "text"), ("quantity", "integer")]):
        return None
    if not any(m.name == "PlayerDataManager" and m.kind in
               (ModuleKind.DATA_STORE, ModuleKind.SERVER_MODULE)
               and m.file_path.startswith("src/server/")
               and m.file_path.endswith(".luau")
               and not m.file_path.endswith(".server.luau")
               for m in proposal.modules):
        return None
    description = str(module.description or "").casefold()
    if all(part in description for part in
           ("purchase record", "weapon upgrade", "currency", "upgrade state")):
        return ("owned_tool_purchase", remote, None, None)
    if all(part in description for part in ("alien", "combat", "target", "damage")):
        role = "world_damage"
    elif all(part in description for part in
             ("mineral", "deposit", "quantity", "inventory")):
        role = "world_harvest"
    else:
        return None

    world_name = _selected_world(module, design, typed.get("world_entities") or [])
    if not world_name:
        return None
    # A matching decorative Part on the ground is not a traversable planet:
    # it must be connected to the same constructed ship's orbit arrival.
    bindings = design.get("host_vehicle_identity_bindings") or []
    arrivals = design.get("host_arrival_materializations") or []
    if not isinstance(bindings, list) or len(bindings) != 1:
        return None
    binding = bindings[0]
    if not isinstance(binding, dict):
        return None
    arrival_names = [
        a.get("arrival") for a in arrivals if isinstance(a, dict)
        and a.get("server") == binding.get("server")
        and a.get("builder") == binding.get("builder")
    ]
    if len(arrival_names) != 1 or not isinstance(arrival_names[0], str):
        return None
    destination = arrival_names[0]
    if not any(isinstance(obj, dict) and obj.get("name") == destination
               and obj.get("class") == "Part"
               for obj in design.get("world_objects") or []):
        return None
    if not any(m.kind == ModuleKind.SERVER_MODULE
               and m.name == binding.get("builder")
               for m in proposal.modules):
        return None
    if not any(m.kind == ModuleKind.SERVER_MODULE
               and m.name == binding.get("server")
               for m in proposal.modules):
        return None
    return role, remote, world_name, destination


_COMMON = r'''--!strict
-- Authenticated, typed transport and authoritative gameplay effect.
local Players = game:GetService("Players")
local Service = {}
local recent = setmetatable({}, {__mode = "k"})
local function input(...)
__GUARD__
    return true, args
end
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function",
        "Player profiles must be loaded before actions")
__START__
    Players.PlayerRemoving:Connect(function(player) recent[player] = nil end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players then
        return {success = false, reason = "invalid_player"} end
    local valid, args = input(...)
    if not valid then return {success = false, reason = "invalid_input"} end
__BODY__
end
return Service
'''

_WORLD_START = r'''    local arrival = workspace:FindFirstChild(__DESTINATION__, true)
    local marker = workspace:FindFirstChild(__WORLD__, true)
    assert(arrival and arrival:IsA("BasePart")
        and marker and marker:IsA("BasePart"),
        "World action requires a real orbit marker and target")
    marker.Anchored = true
    marker.CFrame = arrival.CFrame * CFrame.new(__OFFSET__, 6, 0)
    if marker:GetAttribute(__STATE_KEY__) == nil then
        marker:SetAttribute(__STATE_KEY__, 100)
    end'''

_WORLD_BODY = r'''    if player:GetAttribute("RMMFlightState") ~= "arrived" then
        return {success = false, reason = "not_in_space"} end
    if args.selection ~= __WORLD__ then
        return {success = false, reason = "invalid_target"} end
    local character = player.Character
    local root = character and character:FindFirstChild("HumanoidRootPart")
    local target = workspace:FindFirstChild(__WORLD__, true)
    if not root or not root:IsA("BasePart")
        or not target or not target:IsA("BasePart")
        or (root.Position - target.Position).Magnitude > 80 then
        return {success = false, reason = "target_out_of_range"} end
    local now = os.clock()
    if recent[player] and now - recent[player] < 0.3 then
        return {success = false, reason = "cooldown"} end
__EFFECT__'''

_DAMAGE = r'''    if args.quantity ~= 1 then
        return {success = false, reason = "one_attack_per_request"} end
    local hp = target:GetAttribute("RMMAlienHealth")
    if type(hp) ~= "number" or hp % 1 ~= 0 or hp <= 0
        or hp > 100 then return {success = false, reason = "target_defeated"} end
    local remaining = math.max(0, hp - 20)
    target:SetAttribute("RMMAlienHealth", remaining)
    recent[player] = now
    return {success = true, remainingHealth = remaining, defeated = remaining == 0}'''

_HARVEST = r'''    if args.quantity > 10 then
        return {success = false, reason = "max_ten_per_action"} end
    local stock = target:GetAttribute("RMMSpecialMineralStock")
    if type(stock) ~= "number" or stock % 1 ~= 0
        or stock < args.quantity or stock > 100 then
        return {success = false, reason = "deposit_empty"} end
    local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
    if type(inventory) ~= "table" then
        return {success = false, reason = "profile_not_ready"} end
    local owned = inventory.specialMinerals or 0
    if type(owned) ~= "number" or owned % 1 ~= 0 or owned < 0
        or owned > 1000000 - args.quantity then
        return {success = false, reason = "inventory_limit"} end
    -- Both state changes occur without yielding.
    target:SetAttribute("RMMSpecialMineralStock", stock - args.quantity)
    inventory.specialMinerals = owned + args.quantity
    recent[player] = now
    return {success = true, owned = inventory.specialMinerals,
        remainingDeposit = stock - args.quantity}'''

_PURCHASE = r'''    if args.quantity ~= 1 then
        return {success = false, reason = "one_purchase_per_request"} end
    local backpack = player:FindFirstChildOfClass("Backpack")
    local character = player.Character
    local tool = (backpack and backpack:FindFirstChild(args.selection))
        or (character and character:FindFirstChild(args.selection))
    if not tool or not tool:IsA("Tool")
        or (tool.Parent ~= backpack and tool.Parent ~= character) then
        return {success = false, reason = "weapon_not_owned"} end
    local saved = services.PlayerDataManager.GetState(player, "RMMWeaponPurchases")
    local licenses = services.PlayerDataManager.GetState(player, "RMMTradeEntitlements")
    if type(saved) ~= "table" or type(licenses) ~= "table" then
        return {success = false, reason = "profile_not_ready"} end
    local key = "weapon/" .. tool.Name
    if saved[tool.Name] ~= nil or licenses[key] ~= nil then
        return {success = false, reason = "already_purchased"} end
    -- The offer is server-authored and linked to a real owned Tool, not
    -- a client-supplied price or a fabricated PlayerDataManager method.
    local offer = {cost = 75, expiresAt = nil}
    if offer.expiresAt and os.time() > offer.expiresAt then
        return {success = false, reason = "expired_offer"} end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue")
        or coins.Value < offer.cost or coins.Value < 0 then
        return {success = false, reason = "insufficient_currency"} end
    local now = os.clock()
    if recent[player] and now - recent[player] < 0.3 then
        return {success = false, reason = "cooldown"} end
    -- Cost deduction, persistent record and entitlement have no yield.
    coins.Value -= offer.cost
    saved[tool.Name] = {purchased = true, cost = offer.cost}
    licenses[key] = {purchased = true, kind = "weapon"}
    tool:SetAttribute("RMMWeaponUpgradeLicensed", true)
    recent[player] = now
    return {success = true, weapon = tool.Name, cost = offer.cost,
        credits = coins.Value}'''


def render_verified_effect(module: Any, proposal: Any) -> str | None:
    selected = eligible_verified_effect(module, proposal)
    if selected is None:
        return None
    role, remote, world_name, destination = selected
    design = (proposal.game_design or {}).get("dynamic_design") or {}
    typed = design["host_typed_actions"][remote]
    contract = validate_contract(typed["contract"],
                                 world_entities=typed.get("world_entities") or [],
                                 transport_only=True)
    start = ""
    if role == "owned_tool_purchase":
        body = _PURCHASE
    else:
        assert world_name is not None and destination is not None
        state_key = ("RMMAlienHealth" if role == "world_damage"
                     else "RMMSpecialMineralStock")
        start = (_WORLD_START
                 .replace("__DESTINATION__", json.dumps(destination))
                 .replace("__WORLD__", json.dumps(world_name))
                 .replace("__STATE_KEY__", json.dumps(state_key))
                 .replace("__OFFSET__", "28" if role == "world_damage" else "-28"))
        effect = _DAMAGE if role == "world_damage" else _HARVEST
        body = (_WORLD_BODY.replace("__EFFECT__", effect)
                .replace("__WORLD__", json.dumps(world_name)))
    return (_COMMON.replace("__GUARD__", lua_server_guard(contract).rstrip())
            .replace("__START__", start)
            .replace("__BODY__", body))
