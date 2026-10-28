"""Reuse an independently verified owned-upgrade service for purchase aliases.

This adapter never creates a second price, wallet, entitlement or upgrade
ledger. A natural-language plan may split "buy upgrade" and "upgrade weapon"
into two UI actions; the real authoritative operation is performed exactly
once by the verified service.
"""
from __future__ import annotations

import json
import re
from .spec import ModuleKind
from .host_owned_weapon_performance import eligible_owned_weapon_performance


def eligible_verified_upgrade_alias(module, proposal):
    if (module.kind != ModuleKind.SERVER_MODULE
            or not module.module_id.startswith("dyn_")
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    desc = module.description.casefold()
    # Require the complete business transaction, not a keyword in a name.
    if not all(re.search(pattern, desc) for pattern in (
        r"\bweapon\b", r"\bupgrad\w*\b", r"\b(?:purchas\w*|buy|debit)\b",
        r"\b(?:currency|balance|price)\b", r"\b(?:validat\w*|reject)\b",
    )):
        return None
    design = (proposal.game_design or {}).get("dynamic_design") or {}
    routes = [(name, route) for name, route in
              (design.get("host_actions") or {}).items()
              if isinstance(route, dict) and route.get("service") == module.name]
    if len(routes) != 1:
        return None
    remote, route = routes[0]
    if (route.get("kind") != "RemoteFunction"
            or route.get("max_args") != 1
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (design.get("module_remotes") or {}).get(module.module_id) != [remote]):
        return None
    typed = (design.get("host_typed_actions") or {}).get(remote)
    if (not isinstance(typed, dict)
            or typed.get("transport_only") is not True
            or typed.get("server") != module.name
            or not isinstance(typed.get("contract"), dict)):
        return None
    contract = typed["contract"]
    if (contract.get("target") != {"kind": "none"}
            or contract.get("state_changes") != []):
        return None
    fields = contract.get("inputs")
    if (not isinstance(fields, list) or len(fields) != 2
            or {(x.get("id"), x.get("type")) for x in fields
                if isinstance(x, dict)}
                != {("selection", "text"), ("quantity", "integer")}):
        return None
    if (typed.get("client") != module.name.removesuffix("Server") + "Client"
            or not any(m.kind == ModuleKind.CLIENT_SCRIPT
                       and m.name == typed["client"]
                       and (design.get("module_remotes") or {}).get(m.module_id) == [remote]
                       for m in proposal.modules)):
        return None
    owners = [m for m in proposal.modules
              if m.module_id != module.module_id
              and eligible_owned_weapon_performance(m, proposal) is not None]
    if len(owners) != 1:
        return None
    return owners[0].name


def render_verified_upgrade_alias(module, proposal):
    target = eligible_verified_upgrade_alias(module, proposal)
    if target is None:
        return None
    return _SERVER.replace("__TARGET__", json.dumps(target))


_SERVER = r'''--!strict
-- An alias of one verified, server-authoritative purchase/upgrade operation.
local Players = game:GetService("Players")
local Service = {}
local ownerName = __TARGET__
function Service.start(services)
    local owner = services[ownerName]
    assert(type(owner) == "table" and type(owner.handleAction) == "function",
        "Verified upgrade owner missing from service registry")
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success=false,reason="invalid_player"}
    end
    local args = ...
    if typeof(args) ~= "table" or type(args.selection) ~= "string"
        or #args.selection < 1 or #args.selection > 120
        or type(args.quantity) ~= "number" or args.quantity ~= 1 then
        return {success=false,reason="invalid_input"}
    end
    for key in pairs(args) do
        if key ~= "selection" and key ~= "quantity" then
            return {success=false,reason="extra_input"}
        end
    end
    -- Never charge here. The canonical service validates Tool ownership,
    -- license, price, balance and persistent level in one transaction.
    local owner = services[ownerName]
    if type(owner) ~= "table" or type(owner.handleAction) ~= "function" then
        return {success=false,reason="upgrade_unavailable"}
    end
    return owner.handleAction(player, services, args)
end
return Service
'''
