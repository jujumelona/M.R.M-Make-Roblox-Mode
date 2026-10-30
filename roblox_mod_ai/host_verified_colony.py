"""Verified, source-grounded planet-colony action for a real orbit landing site.

This replaces unbounded model-written Luau only when a connected launch,
owned ship, physically materialized arrival and typed server/client action
exist. It never treats an alien Part as a Model or as a planet.
"""
from __future__ import annotations

import json
import re

from .spec import ModuleKind
from .host_space_actions import COLONY_WORLD_HELPERS


def eligible_colony(module, proposal):
    if not module.module_id.startswith("dyn_") or module.kind not in (
        ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT,
    ):
        return None
    d = (proposal.game_design or {}).get("dynamic_design") or {}
    linked = (d.get("module_remotes") or {}).get(module.module_id)
    if not isinstance(linked, list) or len(linked) != 1:
        return None
    remote = linked[0]
    typed = (d.get("host_typed_actions") or {}).get(remote)
    action = (d.get("host_actions") or {}).get(remote)
    if not isinstance(typed, dict) or not isinstance(action, dict):
        return None
    server = next((m for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE
                   and m.name == typed.get("server")), None)
    client = next((m for m in proposal.modules if m.kind == ModuleKind.CLIENT_SCRIPT
                   and m.name == typed.get("client")), None)
    if server is None or client is None:
        return None
    if (module not in (server, client)
            or (d.get("module_remotes") or {}).get(server.module_id) != [remote]
            or (d.get("module_remotes") or {}).get(client.module_id) != [remote]
            or not server.file_path.startswith("src/server/")
            or not client.file_path.startswith("src/client/")
            or not client.file_path.endswith(".client.luau")):
        return None
    description = (server.description or "").casefold()
    if not (re.search(r"\bplanet\b", description)
            and re.search(r"\bcoloniz", description)
            and "server-owned" in description):
        return None
    if (typed.get("transport_only") is not True
            or action.get("service") != server.name
            or action.get("kind") != "RemoteFunction"
            or action.get("max_args") != 1
            or (d.get("remotes") or {}).get(remote) != "RemoteFunction"):
        return None
    contract = typed.get("contract") or {}
    if (contract.get("target") != {"kind": "none"}
            or contract.get("state_changes") != []
            or [(f.get("id"), f.get("type")) for f in contract.get("inputs", [])]
            != [("selection", "text"), ("quantity", "integer")]):
        return None
    # If the same proposal has an already materialized colony service,
    # leave its established ownership/persistence protocol alone.
    from .host_space_actions import render_host_space_action
    if any(m.kind == ModuleKind.SERVER_MODULE and m is not server
           and ("coloniz" in (m.description or "").casefold())
           and render_host_space_action(m, proposal) is not None
           for m in proposal.modules):
        return None
    bindings = d.get("host_vehicle_identity_bindings") or []
    if len(bindings) != 1 or not isinstance(bindings[0], dict):
        return None
    binding = bindings[0]
    builder = binding.get("builder")
    launch = binding.get("server")
    if (not isinstance(builder, str) or not isinstance(launch, str)
            or not any(m.kind == ModuleKind.SERVER_MODULE and m.name == builder
                       for m in proposal.modules)
            or not any(m.kind == ModuleKind.SERVER_MODULE and m.name == launch
                       for m in proposal.modules)):
        return None
    from .host_ship_attachment import eligible_ship_attachment
    ship_builder = next(m for m in proposal.modules if m.name == builder)
    if eligible_ship_attachment(ship_builder, proposal) is None:
        return None
    candidates = [v.get("arrival") for v in (d.get("host_arrival_materializations") or [])
                  if isinstance(v, dict) and v.get("server") == launch
                  and v.get("builder") == builder]
    if len(candidates) != 1 or not isinstance(candidates[0], str):
        return None
    arrival = candidates[0]
    if sum(1 for w in (d.get("world_objects") or [])
           if isinstance(w, dict) and w.get("name") == arrival
           and w.get("class") == "Part") != 1:
        return None
    # A landing site is the only physical colony surface authorized here.
    # Unrelated alien or craft Parts are never reclassified as planets.
    return remote, builder, arrival


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local recent = setmetatable({}, {__mode="k"})
local ARRIVAL = __ARRIVAL__
local BUILDER = __BUILDER__
__SETTLEMENT_HELPERS__
local function validArrival(player, services)
    if player:GetAttribute("RMMFlightState") ~= "arrived" then return nil end
    local builder = services[BUILDER]
    if type(builder) ~= "table" or type(builder.GetOwnedActor) ~= "function" then return nil end
    local ship = builder.GetOwnedActor(player)
    local arrival = workspace:FindFirstChild(ARRIVAL, true)
    if not arrival or not arrival:IsA("BasePart")
        or not ship or not ship:IsA("Model") or ship.Parent == nil
        or ship:GetAttribute("OwnerUserId") ~= player.UserId
        or (ship:GetPivot().Position - arrival.Position).Magnitude > 80 then return nil end
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0
        or not root or not root:IsA("BasePart")
        or (root.Position - arrival.Position).Magnitude > 80 then return nil end
    return arrival
end
function Service.start(services)
    assert(type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.GetState) == "function"
        and type(services.PlayerDataManager.OnReady) == "function"
        and type(services[BUILDER]) == "table"
        and type(services[BUILDER].GetOwnedActor) == "function",
        "Colony requires real launch craft and persistent player state")
    services.PlayerDataManager.OnReady(function(player)
        local state = services.PlayerDataManager.GetState(player,"RMMPlanetProgress")
        if type(state) ~= "table" then return end
        if state.colonized == true and state.planetOwned == true then
            local stamp = state.colonizedAt
            if type(stamp) == "number" and stamp%1 == 0
                and stamp >= 1 and stamp <= 4102444800 then
                if spawnColony(player, ARRIVAL, stamp) then
                    player:SetAttribute("RMMPlanetColonized", true)
                end
            end
        end
    end)
    Players.PlayerRemoving:Connect(function(player)
        recent[player] = nil
        removeColony(player)
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success=false, reason="invalid_player"} end
    local args = (...)
    if typeof(args) ~= "table" or args.selection ~= "planet"
        or type(args.quantity) ~= "number" or args.quantity ~= 1 then
        return {success=false,reason="invalid_input"} end
    for key in pairs(args) do
        if key ~= "selection" and key ~= "quantity" then
            return {success=false,reason="extra_field"} end
    end
    if not validArrival(player, services) then
        return {success=false,reason="not_at_planet"} end
    local now=os.clock()
    if recent[player] and now-recent[player]<0.4 then
        return {success=false,reason="cooldown"} end
    local state=services.PlayerDataManager.GetState(player,"RMMPlanetProgress")
    if type(state) ~= "table" then
        return {success=false,reason="profile_unavailable"} end
    -- Combat victory is the server-owned permission to found a colony.
    -- A nearby alien prop or an arrived ship alone cannot grant the planet.
    if state.planetOwned ~= true then
        return {success=false,reason="planet_not_owned"} end
    local stamp
    local already=state.colonized == true
    if already then
        stamp=state.colonizedAt
        if type(stamp) ~= "number" or stamp%1 ~= 0
            or stamp<1 or stamp>4102444800 then
            return {success=false,reason="corrupt_colony_state"} end
    else
        stamp=os.time()
    end
    -- Create or restore a real per-player Model before committing success.
    if not spawnColony(player,ARRIVAL,stamp) then
        return {success=false,reason="settlement_unavailable"} end
    if not already then
        state.colonized=true
        state.colonizedAt=stamp
    end
    recent[player]=now
    player:SetAttribute("RMMPlanetColonized",true)
    return {success=true,colonized=true,already=already,settlement="materialized"}
end
return Service
'''

def render_colony(module, proposal):
    chosen = eligible_colony(module, proposal)
    if chosen is None:
        return None
    remote, builder, arrival = chosen
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        from .host_space_actions import _client
        return _client(remote, "MarkPlanetColonized")
    return (_SERVER.replace("__ARRIVAL__", json.dumps(arrival))
            .replace("__BUILDER__", json.dumps(builder))
            .replace("__SETTLEMENT_HELPERS__", COLONY_WORLD_HELPERS))
