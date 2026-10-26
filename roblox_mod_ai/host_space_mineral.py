"""Source-grounded space-only mineral harvesting with real craft identity.

A short model cannot infer Model objects from decorative world Parts. The host
owns the real builder-backed craft, zero-argument RemoteFunction, node Part,
persisted inventory mutation and zero-argument client controller.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,90}$")


def eligible_space_mineral(module: Any, proposal: Any) -> tuple[str, str, str, str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server_name = (module.name if module.kind == ModuleKind.SERVER_MODULE
                   else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in proposal.modules if
                  m.name == server_name and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
    description = owner.description.casefold()
    source = str(proposal.requested_prompt or "").casefold()
    if not (("mineral" in description or "ore" in description)
            and ("harvest" in description or "mine" in description)
            and "space" in description and "craft" in description
            and "aboard" in description
            and ("광물" in source or "mineral" in source)
            and ("우주" in source or "space" in source)):
        return None

    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(key, value) for key, value in
              (design.get("host_actions") or {}).items()
              if isinstance(value, dict) and value.get("service") == server_name]
    if len(routes) != 1:
        return None
    remote, action = routes[0]
    if (action.get("kind") != "RemoteFunction"
            or action.get("max_args") != 0
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or not _IDENTIFIER.fullmatch(remote)):
        return None
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if linked != [remote]:
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/") or not module.file_path.endswith(".luau"):
            return None
    else:
        if (module.name != server_name.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None

    materializations = [
        row for row in (design.get("host_materialized_world") or [])
        if isinstance(row, dict)
        and row.get("service") == server_name
        and row.get("transport_rebased") is True
        and row.get("input") == "RemoteFunction_server_selected_nearest_Part"
    ]
    if len(materializations) != 1:
        return None
    node = materializations[0].get("resource_node")
    world = (design.get("world_objects") or [])
    names = (design.get("module_world_objects") or {}).get(owner.module_id) or []
    if (not isinstance(node, str) or not _IDENTIFIER.fullmatch(node)
            or node not in names
            or sum(row.get("name") == node and row.get("class") in ("Part", "MeshPart")
                   for row in world if isinstance(row, dict)) != 1):
        return None
    # A binding only has source authority if its builder is the SAME actual
    # owner referenced by the declared orbit-arrival contract.
    bindings = (design.get("host_vehicle_identity_bindings") or [])
    arrivals = (design.get("host_arrival_materializations") or [])
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    builder = binding.get("builder")
    launcher = binding.get("server")
    if (binding.get("actor_provider") != "GetOwnedActor"
            or not isinstance(builder, str) or not _IDENTIFIER.fullmatch(builder)
            or not any(m.name == builder and m.kind == ModuleKind.SERVER_MODULE
                       for m in proposal.modules)):
        return None
    matches = [
        row for row in arrivals if isinstance(row, dict)
        and row.get("server") == launcher and row.get("builder") == builder
        and isinstance(row.get("arrival"), str)
    ]
    if len(matches) != 1:
        return None
    arrival = matches[0]["arrival"]
    if (not _IDENTIFIER.fullmatch(arrival)
            or sum(row.get("name") == arrival and row.get("class") in ("Part", "MeshPart")
                   for row in world if isinstance(row, dict)) != 1):
        return None
    return server_name, remote, node, builder, arrival


def render_space_mineral(module: Any, proposal: Any) -> str | None:
    selected = eligible_space_mineral(module, proposal)
    if selected is None:
        return None
    _owner, remote, node, builder, arrival = selected
    code = _SERVER if module.kind == ModuleKind.SERVER_MODULE else _CLIENT
    for key, value in (
        ("@REMOTE@", json.dumps(remote)),
        ("@NODE@", json.dumps(node)),
        ("@BUILDER@", json.dumps(builder)),
        ("@ARRIVAL@", json.dumps(arrival)),
    ):
        code = code.replace(key, value)
    return code


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local NODE_NAME = @NODE@
local ARRIVAL_NAME = @ARRIVAL@
local BUILDER_NAME = @BUILDER@
local MAX_INVENTORY = 2147483647
local COOLDOWN = 0.8
local last = setmetatable({}, {__mode = "k"})
local function integer(n)
    return type(n) == "number" and n == n and n % 1 == 0
        and n >= 0 and n <= MAX_INVENTORY
end
local function worldParts()
    local node = workspace:FindFirstChild(NODE_NAME, true)
    local arrival = workspace:FindFirstChild(ARRIVAL_NAME, true)
    if not node or not node:IsA("BasePart")
        or not arrival or not arrival:IsA("BasePart") then return nil, nil end
    return node, arrival
end
local function locateOre()
    local node, arrival = worldParts()
    if not node or not arrival then return false end
    -- Use the REAL server-authored orbit marker, never a fake Craft Part.
    node.Anchored = true
    node.CFrame = arrival.CFrame * CFrame.new(18, 7, 12)
    node:SetAttribute("RMMOrbitalOre", true)
    return true
end
function Service.start(services)
    local builder = services[BUILDER_NAME]
    assert(type(builder) == "table" and type(builder.GetOwnedActor) == "function"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Space mining requires real assembled craft and persistent inventory")
    assert(locateOre(), "Space mineral node and verified orbit arrival required")
    services.PlayerDataManager.OnReady(function(player)
        local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
        if type(inventory) ~= "table" then return end
        local count = inventory.specialMinerals or 0
        if integer(count) then player:SetAttribute("RMMSpecialMinerals", count) end
    end)
    Players.PlayerRemoving:Connect(function(player) last[player] = nil end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 0 then
        return {success = false, reason = "invalid_request"}
    end
    if player:GetAttribute("RMMFlightState") ~= "arrived" then
        return {success = false, reason = "not_in_space"}
    end
    local builder = services[BUILDER_NAME]
    if type(builder) ~= "table" or type(builder.GetOwnedActor) ~= "function" then
        return {success = false, reason = "craft_service_unavailable"}
    end
    local craft = builder.GetOwnedActor(player)
    local humanoid = player.Character and player.Character:FindFirstChildOfClass("Humanoid")
    if not craft or not craft:IsA("Model") or craft.Parent == nil
        or craft:GetAttribute("OwnerUserId") ~= player.UserId
        or not humanoid or humanoid.Health <= 0 then
        return {success = false, reason = "craft_unavailable"}
    end
    local seat = craft:FindFirstChild("PilotSeat", true)
    if not seat or not seat:IsA("VehicleSeat") or seat.Occupant ~= humanoid then
        return {success = false, reason = "not_aboard"}
    end
    local node, arrival = worldParts()
    if not node or not arrival or node:GetAttribute("RMMOrbitalOre") ~= true
        or (node.Position - arrival.Position).Magnitude > 45
        or (craft:GetPivot().Position - node.Position).Magnitude > 55 then
        return {success = false, reason = "outside_orbit_mining_range"}
    end
    local now = os.clock()
    if last[player] and now - last[player] < COOLDOWN then
        return {success = false, reason = "cooldown"}
    end
    local inventory = services.PlayerDataManager.GetState(player, "RMMInventory")
    if type(inventory) ~= "table" then
        return {success = false, reason = "profile_loading"}
    end
    local count = inventory.specialMinerals or 0
    if not integer(count) or count == MAX_INVENTORY then
        return {success = false, reason = "inventory_invalid"}
    end
    -- Server selected target, server validated actual ship and pilot, and a
    -- no-yield persisted inventory mutation. Never charge arbitrary Coins.
    inventory.specialMinerals = count + 1
    last[player] = now
    node:SetAttribute("RMMLastHarvest", now)
    player:SetAttribute("RMMSpecialMinerals", count + 1)
    return {success = true, harvested = 1, total = count + 1}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing Remotes") end
local remote = remotes:WaitForChild(@REMOTE@, 20)
if not remote or not remote:IsA("RemoteFunction") then
    error("Special-mineral harvest RemoteFunction missing")
end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMSpaceMineralHarvest"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Size = UDim2.fromOffset(260, 48)
button.Position = UDim2.new(1, -278, 1, -150)
button.Text = "Harvest special mineral"
button.Parent = gui
local status = Instance.new("TextLabel")
status.Size = UDim2.fromOffset(270, 45)
status.Position = UDim2.new(1, -278, 1, -98)
status.Text = "Requires your craft at the orbital mining node"
status.Parent = gui
local busy = false
local function refresh()
    button.Active = player:GetAttribute("RMMFlightState") == "arrived" and not busy
end
player:GetAttributeChangedSignal("RMMFlightState"):Connect(refresh)
refresh()
button.Activated:Connect(function()
    if busy or player:GetAttribute("RMMFlightState") ~= "arrived" then return end
    busy = true
    refresh()
    local ok, result = pcall(function() return remote:InvokeServer() end)
    busy = false
    refresh()
    if not ok or type(result) ~= "table" then
        status.Text = "Harvest network error"
    elseif result.success then
        status.Text = "Special minerals: " .. tostring(result.total)
    else
        status.Text = "Rejected: " .. tostring(result.reason or "unknown")
    end
end)
'''
