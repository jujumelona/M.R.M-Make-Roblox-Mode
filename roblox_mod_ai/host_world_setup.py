"""Deterministic passive world setup, independent of player-travel permission.

This adapter applies only when the authored server service explicitly owns a
passive themed world setup with NO player ingress. It creates actual Roblox
instances. Unlocks/teleports remain the concern of separate server actions.
"""
from __future__ import annotations

import re

from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal


def render_host_world_setup(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.SERVER_MODULE
            or not module.file_path.startswith("src/server/")
            or not module.file_path.endswith(".luau")):
        return None
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", module.name).casefold()
    desc = module.description.casefold()
    # Both *name* and semantic behavior must describe an environment setup.
    # No client action, player-facing reward, purchase, or gate can be subsumed.
    if (not re.search(r"\bspace mode setup\b|\bspace environment setup\b", name)
            or not all(x in desc for x in ("environment", "space", "mode"))
            or not any(x in desc for x in ("themed", "assets", "world", "setup"))):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    for source in ("host_actions", "host_world_actions"):
        if any(isinstance(row, dict) and row.get("service") == module.name
               for row in (design.get(source) or {}).values()):
            return None
    return _SERVER


_SERVER = r'''--!strict
-- World setup is global and passive. It never grants space-flight access.
-- The separate launch service must validate ship construction and upgrades.
local Lighting = game:GetService("Lighting")
local Service = {}
local initialized = false
local function ensurePlanetEnvironment()
    local region = workspace:FindFirstChild("RMMStartingPlanet")
    if region ~= nil then
        assert(region:IsA("Folder"), "Planet scene name is reserved")
    else
        region = Instance.new("Folder")
        region.Name = "RMMStartingPlanet"
        region.Parent = workspace
    end
    local ground = region:FindFirstChild("PlanetGround")
    if ground == nil then
        ground = Instance.new("Part")
        ground.Name = "PlanetGround"
        ground.Anchored = true
        ground.Size = Vector3.new(160, 2, 160)
        -- The Rojo Baseplate spans Y=-20..0. Placing a 2-stud terrain
        -- slab at Y=-2 hid the entire planet floor under the Baseplate.
        -- Keep the new floor visible (top Y=0.5), but below the spawn
        -- pad (top Y=1.5) so it cannot bury SpawnLocation.
        ground.Position = Vector3.new(0, -0.5, 0)
        ground.Material = Enum.Material.Slate
        ground.Color = Color3.fromRGB(74, 82, 114)
        ground.Parent = region
    else
        assert(ground:IsA("BasePart"), "Planet ground has an invalid class")
    end
    local atmosphere = Lighting:FindFirstChild("RMMPlanetAtmosphere")
    if atmosphere == nil then
        atmosphere = Instance.new("Atmosphere")
        atmosphere.Name = "RMMPlanetAtmosphere"
        atmosphere.Density = 0.3
        atmosphere.Color = Color3.fromRGB(146, 154, 205)
        atmosphere.Parent = Lighting
    else
        assert(atmosphere:IsA("Atmosphere"), "Planet atmosphere class mismatch")
    end
    workspace:SetAttribute("RMMWorldSceneReady", true)
end
function Service.start(services)
    assert(type(services) == "table", "World setup requires a server service registry")
    if initialized then return end
    ensurePlanetEnvironment()
    initialized = true
end
function Service.isReady()
    return initialized and workspace:GetAttribute("RMMWorldSceneReady") == true
end
return Service
'''