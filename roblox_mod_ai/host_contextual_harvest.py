"""Contract-driven vehicle resource interaction for any Roblox genre.

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


def eligible_contextual_harvest(module: Any, proposal: Any) -> tuple[str, str, str, str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    # Dispatch only through the declared host service/remote ownership.
    # No Korean or English request phrases, specific resource types, planets,
    # game titles, or naming suffixes are used as gameplay evidence.
    if module.kind == ModuleKind.SERVER_MODULE:
        server_name = module.name
    else:
        linked_remote_names = (design.get("module_remotes") or {}).get(
            module.module_id, []
        )
        candidates = {
            row.get("service") for name, row in
            (design.get("host_actions") or {}).items()
            if name in linked_remote_names and isinstance(row, dict)
        }
        if len(candidates) != 1:
            return None
        server_name = next(iter(candidates))
    owner = next((m for m in proposal.modules if
                  m.name == server_name and m.kind == ModuleKind.SERVER_MODULE), None)
    if owner is None:
        return None
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
        if (not module.file_path.startswith("src/client/")
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
    # A world can contain vehicles for unrelated gameplay. Their existence
    # does NOT impose vehicle ownership, arrival and seating prerequisites
    # on an independent resource action. Only an ACTION-OWNED declaration
    # authorizes the extra preconditions, moving its node, and vehicle UI.
    context = materializations[0].get("vehicle_context")
    if not isinstance(context, dict) or (
            context.get("requires_seated_driver") is not True
            or context.get("actor_provider") != "GetOwnedActor"
            or not isinstance(context.get("builder"), str)
            or not isinstance(context.get("arrival"), str)):
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
    # Multiple vehicle services are valid in a generic game, but a resource
    # action must identify exactly one real actor provider for its arrival.
    admissible = [
        row for row in bindings if isinstance(row, dict)
        and row.get("actor_provider") == context["actor_provider"]
        and row.get("builder") == context["builder"]
        and any(isinstance(a, dict)
                and a.get("server") == row.get("server")
                and a.get("builder") == row.get("builder")
                and a.get("arrival") == context["arrival"]
                for a in arrivals)
    ]
    if len(admissible) != 1:
        return None
    binding = admissible[0]
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


def render_contextual_harvest(module: Any, proposal: Any) -> str | None:
    selected = eligible_contextual_harvest(module, proposal)
    if selected is None:
        return None
    _owner, remote, node, builder, arrival = selected
    design = proposal.game_design.get("dynamic_design") or {}
    materializations = [
        row for row in (design.get("host_materialized_world") or [])
        if isinstance(row, dict) and row.get("service") == _owner
        and row.get("resource_node") == node
    ]
    if len(materializations) != 1:
        return None
    authored = materializations[0]
    # The host's state ABI is shared across genres. The reward field, amount,
    # display and maximum interaction distance are data, never invented Luau.
    reward = authored.get("reward") or {}
    if not isinstance(reward, dict):
        return None
    namespace = reward.get("namespace", "RMMInventory")
    field = reward.get("key", "resources")
    attribute = reward.get("attribute", "RMMResourceCount")
    label = reward.get("label", "Collect resource")
    radius = authored.get("interaction_range", 55)
    if (not all(isinstance(x, str) and _IDENTIFIER.fullmatch(x)
                for x in (namespace, field, attribute))
            or not isinstance(label, str) or not 1 <= len(label) <= 64
            or type(radius) not in (int, float) or not 5 <= radius <= 256):
        raise ValueError("INVALID_CONTEXTUAL_HARVEST_CONTRACT: reward state, label or range")
    code = _SERVER if module.kind == ModuleKind.SERVER_MODULE else _CLIENT
    for key, value in (
        ("@REMOTE@", json.dumps(remote)),
        ("@NODE@", json.dumps(node)),
        ("@BUILDER@", json.dumps(builder)),
        ("@ARRIVAL@", json.dumps(arrival)),
        ("@NAMESPACE@", json.dumps(namespace)),
        ("@FIELD@", json.dumps(field)),
        ("@ATTRIBUTE@", json.dumps(attribute)),
        ("@LABEL@", json.dumps(label)),
        ("@MAX_RANGE@", str(radius)),
    ):
        code = code.replace(key, value)
    return code


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local NODE_NAME = @NODE@
local ARRIVAL_NAME = @ARRIVAL@
local BUILDER_NAME = @BUILDER@
local INVENTORY_NAMESPACE = @NAMESPACE@
local INVENTORY_FIELD = @FIELD@
local RESOURCE_ATTRIBUTE = @ATTRIBUTE@
local MAX_RANGE = @MAX_RANGE@
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
local function locateResource()
    local node, arrival = worldParts()
    if not node or not arrival then return false end
    -- Use the REAL server-authored orbit marker, never a fake Craft Part.
    node.Anchored = true
    -- Use the actual declared arrival pad bounds, never a map-specific
    -- coordinate; verify the target remains a server-owned workspace Part.
    local offset = Vector3.new(
        arrival.Size.X / 4,
        arrival.Size.Y / 2 + node.Size.Y / 2 + 1,
        arrival.Size.Z / 4
    )
    node.CFrame = arrival.CFrame * CFrame.new(offset)
    node:SetAttribute("RMMHarvestTarget", true)
    return true
end
function Service.start(services)
    local builder = services[BUILDER_NAME]
    assert(type(builder) == "table" and type(builder.GetOwnedActor) == "function"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function",
        "Resource interaction requires an owned vehicle and persistent inventory")
    assert(locateResource(), "Authorized resource node and destination required")
    services.PlayerDataManager.OnReady(function(player)
        local inventory = services.PlayerDataManager.GetState(player, INVENTORY_NAMESPACE)
        if type(inventory) ~= "table" then return end
        local count = inventory[INVENTORY_FIELD] or 0
        if integer(count) then player:SetAttribute(RESOURCE_ATTRIBUTE, count) end
    end)
    Players.PlayerRemoving:Connect(function(player) last[player] = nil end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 0 then
        return {success = false, reason = "invalid_request"}
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
    local seat = craft:FindFirstChildWhichIsA("VehicleSeat", true)
    if not seat or not seat:IsA("VehicleSeat") or seat.Occupant ~= humanoid then
        return {success = false, reason = "not_in_authorized_vehicle"}
    end
    local node, arrival = worldParts()
    if not node or not arrival or node:GetAttribute("RMMHarvestTarget") ~= true
        or (node.Position - arrival.Position).Magnitude >
           (arrival.Size.Magnitude + node.Size.Magnitude)
        or (craft:GetPivot().Position - node.Position).Magnitude > MAX_RANGE then
        return {success = false, reason = "outside_resource_range"}
    end
    local now = os.clock()
    if last[player] and now - last[player] < COOLDOWN then
        return {success = false, reason = "cooldown"}
    end
    local inventory = services.PlayerDataManager.GetState(player, INVENTORY_NAMESPACE)
    if type(inventory) ~= "table" then
        return {success = false, reason = "profile_loading"}
    end
    local count = inventory[INVENTORY_FIELD] or 0
    if not integer(count) or count == MAX_INVENTORY then
        return {success = false, reason = "inventory_invalid"}
    end
    -- Server selected target, server validated actual ship and pilot, and a
    -- no-yield persisted inventory mutation. Never charge arbitrary Coins.
    inventory[INVENTORY_FIELD] = count + 1
    last[player] = now
    node:SetAttribute("RMMLastHarvest", now)
    player:SetAttribute(RESOURCE_ATTRIBUTE, count + 1)
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
    error("Resource interaction RemoteFunction missing")
end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMContextResourceHarvest"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Size = UDim2.fromOffset(260, 48)
button.Position = UDim2.new(1, -278, 1, -150)
button.Text = @LABEL@
button.Parent = gui
local status = Instance.new("TextLabel")
status.Size = UDim2.fromOffset(270, 45)
status.Position = UDim2.new(1, -278, 1, -98)
status.Text = "Approach the resource with your authorized vehicle"
status.Parent = gui
local busy = false
local function refresh()
    button.Active = not busy
end
refresh()
button.Activated:Connect(function()
    if busy then return end
    busy = true
    refresh()
    local ok, result = pcall(function() return remote:InvokeServer() end)
    busy = false
    refresh()
    if not ok or type(result) ~= "table" then
        status.Text = "Harvest network error"
    elseif result.success then
        status.Text = "Resources: " .. tostring(result.total)
    else
        status.Text = "Rejected: " .. tostring(result.reason or "unknown")
    end
end)
'''


# Public compatibility symbols for previously authored plans.
eligible_space_mineral = eligible_contextual_harvest
render_space_mineral = render_contextual_harvest
