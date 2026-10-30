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
from .typed_action_contract import (validate_contract, lua_server_guard,
                                    TypedActionContractError)


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
        # Semantic names can be shorter OR longer than physical Part IDs:
        # "AlienEntity" -> "AlienEntity<id>", but also "alien entities on
        # planet" -> "AlienEntities1". Compare their grounded shared stem,
        # not a fixed 12-character substring that rejects short actors.
        # An ambiguous stem is never enough: exactly one source-owned Part
        # must match before a host server handler can be selected.
        aliases = [_normalized(alias) for alias in descriptions
                   if isinstance(alias, str)]
        if any((shared := min(12, len(alias), len(normalized))) >= 8
               and normalized[:shared] == alias[:shared]
               for alias in aliases):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


def _owned_weapon_upgrade_peer(module: Any, proposal: Any) -> Any | None:
    """Reuse one existing verified persistent weapon-upgrade implementation.

    Never fabricate a new purchase ledger, item catalog, or unrelated price.
    """
    from .host_owned_weapon_performance import eligible_owned_weapon_performance
    peers = [
        peer for peer in getattr(proposal, "modules", ())
        if peer is not module
        and eligible_owned_weapon_performance(peer, proposal) is not None
    ]
    return peers[0] if len(peers) == 1 else None


def eligible_verified_effect(module: Any, proposal: Any) -> tuple[str, str, str | None, str | None] | None:
    """Match only typed one-remote actions with real owned runtime dependencies."""
    if (module.kind != ModuleKind.SERVER_MODULE
            or not module.module_id.startswith("dyn_")
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    # A world ABI checker asks whether *arbitrary* server modules have
    # special placement permissions. Only inspect a candidate whose authored
    # behavior actually describes one of the three supported host effects.
    # Other typed actions (e.g. colony aliases with legacy field labels)
    # must not be schema-validated or fail here.
    description = str(getattr(module, "description", "") or "").casefold()
    if not (
        all(part in description for part in
            ("purchase record", "weapon upgrade", "currency", "upgrade state"))
        or all(part in description for part in
               ("alien", "target", "damage"))
        or all(part in description for part in
               ("mineral", "deposit", "quantity", "inventory"))
    ):
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
    try:
        contract = validate_contract(typed.get("contract"),
                                     world_entities=typed.get("world_entities") or [],
                                     transport_only=True)
    except (TypedActionContractError, TypeError, ValueError):
        return None
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
        if _owned_weapon_upgrade_peer(module, proposal) is None:
            return None
        return ("owned_tool_purchase", remote, None, None)
    if all(part in description for part in ("alien", "target", "damage")):
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

_RANKED_DAMAGE = r'''    if args.quantity ~= 1 then
        return {success = false, reason = "one_attack_per_request"} end
    local hp = target:GetAttribute("RMMAlienHealth")
    if type(hp) ~= "number" or hp % 1 ~= 0 or hp <= 0
        or hp > 100 then return {success = false, reason = "target_defeated"} end
    local ranks = services.PlayerDataManager.GetState(player, "RMMRankProgress")
    if type(ranks) ~= "table" then
        return {success = false, reason = "upgrade_profile_unavailable"} end
    local crew = ranks.crew_performance_state or 0
    local weapon = ranks.owned_weapon or 0
    if type(crew) ~= "number" or type(weapon) ~= "number"
        or crew % 1 ~= 0 or weapon % 1 ~= 0 or crew < 0
        or weapon < 0 or crew > 100 or weapon > 100 then
        return {success = false, reason = "invalid_upgrade_rank"} end
    local damage = math.min(70, 20 + 2 * crew + 3 * weapon)
    local remaining = math.max(0, hp - damage)
    target:SetAttribute("RMMAlienHealth", remaining)
    recent[player] = os.clock()
    return {success = true, remainingHealth = remaining, damage = damage,
        defeated = remaining == 0}'''


# This source-verified extension connects a persisted, paid weapon level to
# the real server combat handler. A cosmetic Tool attribute is not gameplay.
# Damage, cooldown and server-owned magazine changes use the exact profile
# that the weapon upgrade service writes. The client supplies only a target.
_OWNED_WEAPON_ATTACK = r'''    local equipped = character and character:FindFirstChildOfClass("Tool")
    local upgradedLevel = 0
    local weaponAmmo = nil
    if equipped then
        local savedWeapons = services.PlayerDataManager.GetState(player, "RMMWeaponPerformance")
        if type(savedWeapons) ~= "table" then
            return {success = false, reason = "weapon_profile_not_ready"} end
        local purchase = savedWeapons[equipped.Name]
        if purchase ~= nil and type(purchase) ~= "table" then
            return {success = false, reason = "invalid_weapon_state"} end
        if purchase ~= nil or equipped:GetAttribute("RMMOwnedWeapon") == true then
            upgradedLevel = purchase and purchase.level or 0
            if type(upgradedLevel) ~= "number" or upgradedLevel % 1 ~= 0
                or upgradedLevel < 0 or upgradedLevel > 5 then
                return {success = false, reason = "invalid_weapon_rank"} end
            local rounds = services.PlayerDataManager.GetState(player, "RMMWeaponAmmo")
            if type(rounds) ~= "table" then
                return {success = false, reason = "ammo_profile_not_ready"} end
            local size = 6 + 2 * upgradedLevel
            local existing = rounds[equipped.Name]
            if existing == nil or type(existing) ~= "table"
                or existing.capacity ~= size then
                existing = {capacity = size, remaining = size, lastShotUTC = 0}
                rounds[equipped.Name] = existing
            end
            if type(existing.remaining) ~= "number"
                or existing.remaining % 1 ~= 0 or existing.remaining < 0
                or existing.remaining > size
                or type(existing.lastShotUTC) ~= "number" then
                return {success = false, reason = "invalid_ammo_state"} end
            if existing.remaining == 0 then
                if os.time() - existing.lastShotUTC < 2 then
                    return {success = false, reason = "reloading"} end
                existing.remaining = size
            end
            weaponAmmo = existing
        end
    end
    -- The interval is derived from persisted server rank, never from a
    -- client-provided multiplier. Unarmed attacks retain the base interval.
    local fireInterval = 0.3 / (1 + 0.1 * upgradedLevel)
    if recent[player] and now - recent[player] < fireInterval then
        return {success = false, reason = "cooldown"} end
'''
_COLONY_DAMAGE = r'''    if args.quantity ~= 1 then
        return {success = false, reason = "one_attack_per_request"} end
    local hp = target:GetAttribute("RMMAlienHealth")
    if type(hp) ~= "number" or hp % 1 ~= 0 or hp <= 0
        or hp > 100 then return {success = false, reason = "target_defeated"} end
    local progress = services.PlayerDataManager.GetState(player, "RMMPlanetProgress")
    if type(progress) ~= "table" then
        return {success = false, reason = "planet_progress_unavailable"} end
    local remaining = math.max(0, hp - 20)
    -- No yielding between world damage and authoritative player progress.
    target:SetAttribute("RMMAlienHealth", remaining)
    if remaining == 0 then
        progress.planetOwned = true
        player:SetAttribute("RMMPlanetOwned", true)
    end
    recent[player] = now
    return {success = true, remainingHealth = remaining,
        defeated = remaining == 0, planetOwned = progress.planetOwned == true}'''


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
        # Reuse the existing verified, persistent purchase/upgrade route.
        # Both actions now share the authoritative level, owned Tool,
        # entitlement and price protocol instead of double charging.
        from .host_owned_weapon_performance import render_owned_weapon_performance
        peer = _owned_weapon_upgrade_peer(module, proposal)
        return render_owned_weapon_performance(peer, proposal) if peer else None
    else:
        assert world_name is not None and destination is not None
        state_key = ("RMMAlienHealth" if role == "world_damage"
                     else "RMMSpecialMineralStock")
        start = (_WORLD_START
                 .replace("__DESTINATION__", json.dumps(destination))
                 .replace("__WORLD__", json.dumps(world_name))
                 .replace("__STATE_KEY__", json.dumps(state_key))
                 .replace("__OFFSET__", "28" if role == "world_damage" else "-28"))
        ranked_combat = False
        colony_combat = False
        weapon_performance_combat = False
        if role == "world_damage":
            from .host_level_upgrade import eligible_rank_protocol
            from .host_owned_weapon_performance import eligible_owned_weapon_performance
            from .host_verified_colony import eligible_colony
            targets = set()
            for peer in proposal.modules:
                if peer.kind != ModuleKind.SERVER_MODULE or peer is module:
                    continue
                rank = eligible_rank_protocol(peer, proposal)
                if rank is not None:
                    targets.add(rank[2])
                if eligible_owned_weapon_performance(peer, proposal) is not None:
                    weapon_performance_combat = True
                if eligible_colony(peer, proposal) is not None:
                    colony_combat = True
            ranked_combat = bool({"crew_performance_state", "owned_weapon"} & targets) or weapon_performance_combat
        if role != "world_damage":
            effect = _HARVEST
        elif ranked_combat:
            effect = _RANKED_DAMAGE
            if weapon_performance_combat:
                effect = effect.replace(
                    '    local damage = math.min(70, 20 + 2 * crew + 3 * weapon)',
                    _OWNED_WEAPON_ATTACK
                    + '    local damage = math.min(70, 20 + 2 * crew + 3 * weapon'
                      ' + 4 * upgradedLevel)',
                ).replace(
                    '    target:SetAttribute("RMMAlienHealth", remaining)',
                    '    if weaponAmmo then\n'
                    '        weaponAmmo.remaining -= 1\n'
                    '        weaponAmmo.lastShotUTC = os.time()\n'
                    '    end\n'
                    '    target:SetAttribute("RMMAlienHealth", remaining)',
                )
            if colony_combat:
                effect = effect.replace(
                    '    target:SetAttribute("RMMAlienHealth", remaining)',
                    '    local progress = services.PlayerDataManager.GetState(player, "RMMPlanetProgress")\n'
                    '    if type(progress) ~= "table" then\n'
                    '        return {success = false, reason = "planet_progress_unavailable"} end\n'
                    '    target:SetAttribute("RMMAlienHealth", remaining)\n'
                    '    if remaining == 0 then\n'
                    '        progress.planetOwned = true\n'
                    '        player:SetAttribute("RMMPlanetOwned", true)\n'
                    '    end',
                )
        elif colony_combat:
            effect = _COLONY_DAMAGE
        else:
            effect = _DAMAGE
        body = (_WORLD_BODY.replace("__EFFECT__", effect)
                .replace("__WORLD__", json.dumps(world_name)))
        if weapon_performance_combat:
            # The integrated ranged-weapon handler performs its own dynamic
            # fire-rate gate, including the unupgraded base cooldown.
            body = body.replace(
                '    if recent[player] and now - recent[player] < 0.3 then\\n'
                '        return {success = false, reason = "cooldown"} end\\n',
                '',
            )
    # The damage handler needs only the authenticated player and the actual
    # world target; unlike harvesting it does not read the service registry.
    # Declare that argument intentionally unused so Selene never reports a
    # deterministic host-template defect after a successful 26-module build.
    template = _COMMON
    if role == "world_damage" and not ranked_combat and not colony_combat:
        template = template.replace(
            "function Service.handleAction(player, services, ...)",
            "function Service.handleAction(player, _services, ...)",
        )
    return (template.replace("__GUARD__", lua_server_guard(contract).rstrip())
            .replace("__START__", start)
            .replace("__BODY__", body))
