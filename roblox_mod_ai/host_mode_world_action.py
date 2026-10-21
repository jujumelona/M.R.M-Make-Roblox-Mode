"""Host-owned mode activation through an actual authored world ProximityPrompt.

This is not space-flight or launch permission. The trigger only activates an
explicitly declared mode and themed environment; the separate launch gate
must check the player's ship before granting orbital progression.
"""
from __future__ import annotations
import json
import re
from typing import Any
from .spec import ModuleKind


def render_host_mode_world_action(module: Any, proposal: Any) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.SERVER_MODULE
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    desc = module.description.casefold()
    if (not re.search(r"\bdedicated\s+([a-z][a-z-]{0,24})\s+mode\b", desc)
            or not re.search(r"\b(?:enable|activate|setup)\w*\b", desc)
            or not re.search(r"\b(?:themed|environment|world)\b", desc)
            or not re.search(r"\b(?:progression|state)\b", desc)):
        return None
    mode = re.search(r"\bdedicated\s+([a-z][a-z-]{0,24})\s+mode\b", desc).group(1).title() + " Mode"
    design = proposal.game_design.get("dynamic_design") or {}
    if any(isinstance(v, dict) and v.get("service") == module.name
           for v in (design.get("host_actions") or {}).values()):
        return None
    routes = [(name, value) for name, value in (design.get("host_world_actions") or {}).items()
              if isinstance(value, dict) and value.get("service") == module.name]
    if len(routes) != 1:
        return None
    part_name = routes[0][0]
    if not any(isinstance(p, dict) and p.get("name") == part_name
               and p.get("class") == "Part" for p in design.get("world_objects") or []):
        return None
    owners = (design.get("module_world_objects") or {}).get(module.module_id)
    if owners is not None and part_name not in owners:
        return None
    return _SERVER.replace("__MODE__", json.dumps(mode)).replace("__PART__",json.dumps(part_name))


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Lighting = game:GetService("Lighting")
local Service = {}
local MODE = __MODE__
local TARGET = __PART__
local DISTANCE = 20
local function valid(player, part)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players
        or typeof(part) ~= "Instance" or not part:IsA("BasePart")
        or part.Name ~= TARGET or workspace:FindFirstChild(TARGET,true) ~= part then
        return false
    end
    local character = player.Character
    local human = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    return human ~= nil and human.Health > 0 and root ~= nil
        and (root.Position-part.Position).Magnitude <= DISTANCE
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Mode setup requires an authoritative saved player profile")
    local atmosphere = Lighting:FindFirstChild("RMMModeAtmosphere")
    if atmosphere == nil then
        atmosphere = Instance.new("Atmosphere")
        atmosphere.Name = "RMMModeAtmosphere"
        atmosphere.Color = Color3.fromRGB(147,161,222)
        atmosphere.Parent = Lighting
    end
    workspace:SetAttribute("RMMModeEnvironmentReady",true)
    services.PlayerDataManager.OnReady(function(player)
        local state = services.PlayerDataManager.GetState(player,"RMMGameMode")
        if type(state) == "table" and state.activeMode == MODE then
            player:SetAttribute("RMMActiveGameMode",MODE)
        end
    end)
end
function Service.handleAction(player, services, ...)
    if select("#",...) ~= 1 then return false end
    local part = ...
    if not valid(player,part) then return false end
    local state = services.PlayerDataManager.GetState(player,"RMMGameMode")
    if type(state) ~= "table" then return false end
    state.activeMode = MODE
    player:SetAttribute("RMMActiveGameMode",MODE)
    -- No RMMInSpace, no teleport and no ship access before launch validation.
    return {success=true,mode=MODE,spaceUnlocked=false}
end
return Service
'''