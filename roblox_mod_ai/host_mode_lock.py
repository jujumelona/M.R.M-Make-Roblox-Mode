"""Host-owned passive game-mode lock with a real player-profile ABI.

A pure mode-lock module is not a complete gameplay service and must not be
invented as a long Luau program by a small model. This adapter sets and reads
the active mode only; unrelated economy/flight/world behaviors remain with
their actual service owners.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind

_ACTIVE = re.compile(
    r"\benforces?\s+(?P<mode>[a-z][a-z0-9_-]*(?:\s+[a-z][a-z0-9_-]*)?)"
    r"\s+as\s+the\s+active\s+game\s+mode\b", re.I,
)


def eligible_mode_lock(module: Any, proposal: Any) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.SERVER_MODULE
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")
            or module.file_path.endswith(".server.luau")):
        return None
    desc = module.description.casefold()
    match = _ACTIVE.search(desc)
    if (not match or not re.search(r"\b(?:validat|enforc)\w*\b", desc)
            or not re.search(r"\b(?:context|state|progression)\b", desc)):
        return None
    mode = match.group("mode").strip().title()
    if len(mode) > 50:
        return None
    dynamic = proposal.game_design.get("dynamic_design") or {}
    for key in ("host_actions", "host_world_actions"):
        if any(isinstance(action, dict) and action.get("service") == module.name
               for action in (dynamic.get(key) or {}).values()):
            return None
    # This is a standalone passive lock, not a replacement for a separately
    # described player-triggered mode switch or a second conflicting mode lock.
    if any(peer is not module and peer.kind == ModuleKind.SERVER_MODULE
           and peer.module_id.startswith("dyn_")
           and _ACTIVE.search(peer.description.casefold())
           for peer in getattr(proposal, "modules", [])):
        return None
    return mode


def render_host_mode_lock(module: Any, proposal: Any) -> str | None:
    mode = eligible_mode_lock(module, proposal)
    if mode is None:
        return None
    return _SERVER.replace("__MODE__", json.dumps(mode))


_SERVER = r'''--!strict
-- Passive invariant, not a Remote capable of granting gameplay rewards.
local Players = game:GetService("Players")
local Service = {}
local MODE = __MODE__
local NAMESPACE = "RMMGameMode"
local manager = nil

local function ready(player)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or not manager then return nil end
    local state = manager.GetState(player, NAMESPACE)
    if type(state) ~= "table" then return nil end
    if state.activeMode ~= MODE then state.activeMode = MODE end
    player:SetAttribute("RMMActiveGameMode", MODE)
    return state
end

function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Mode invariant requires the host PlayerDataManager")
    manager = services.PlayerDataManager
    workspace:SetAttribute("RMMActiveGameMode", MODE)
    manager.OnReady(function(player)
        ready(player)
    end)
end

function Service.getStateForValidation(player)
    if not manager then return nil end
    local state = manager.GetState(player, NAMESPACE)
    if type(state) ~= "table" or state.activeMode ~= MODE then return nil end
    return state
end

function Service.isActive(player)
    return Service.getStateForValidation(player) ~= nil
        and player:GetAttribute("RMMActiveGameMode") == MODE
        and workspace:GetAttribute("RMMActiveGameMode") == MODE
end

return Service
'''