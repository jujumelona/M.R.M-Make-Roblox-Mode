"""Host-owned attach-once ship assembly for a single section-ID action.

The domain LLM only chooses bounded gameplay data (part identifiers, resource
prices, performance effects). It never implements Roblox profile, proximity,
remote input, world Parts, persistence or transaction orchestration.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .host_catalog_purchase import _ID
from .host_mining import render_host_mining
from .spec import ModuleKind

_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "label": {"type": "string"},
                "cost": {"type": "integer"}, "performance": {"type": "integer"},
            }, "required": ["id", "label", "cost", "performance"],
        }},
    },
    "required": ["sections"],
}


def _source_linked_section_builder(owner: Any, proposal: Any) -> bool:
    """Admit short small-model assembly descriptions ONLY when launch is linked.

    The actual implementation remains the host's secure add-once, resource
    debiting section builder. A decorative ship or unsourced mechanic fails.
    """
    source = str(getattr(proposal, "requested_prompt", "") or "")
    desc = str(getattr(owner, "description", "") or "")
    assembly = bool(re.search(
        r"우주선.{0,70}(?:부위|부품|부분)|"
        r"\b(?:ship|spaceship|spacecraft|craft|vessel)\b"
        r".{0,80}\b(?:part|section|component|module)s?\b|"
        r"\b(?:assembl|build|construct)\w*\b.{0,80}"
        r"\b(?:ship|spacecraft|vehicle)\b", source, re.I,
    ))
    departure = bool(re.search(
        r"우주(?:로|에)\s*(?:나가|나갈|나간|나갔|출발|진입|이동)|"
        r"\b(?:launch|depart|travel|fly)\w*\b.{0,70}"
        r"\b(?:space|orbit)\b", source, re.I,
    ))
    authored = all((
        re.search(r"\b(?:ship|spaceship|spacecraft|craft|vessel)\b", desc, re.I),
        re.search(r"\b(?:part|section|component|module)s?\b", desc, re.I),
        re.search(r"\b(?:attach|install|assembl|build|construct)\w*\b", desc, re.I),
        re.search(r"\bserver\b", desc, re.I),
    ))
    if not assembly or not departure or not authored or re.search(
        r"\b(?:remov|replac|detach|uninstall|refund)\w*\b", desc, re.I,
    ):
        return False
    d = (proposal.game_design or {}).get("dynamic_design") or {}
    motions = d.get("host_world_motion") or {}
    actions = d.get("host_actions") or {}
    typed = d.get("host_typed_actions") or {}
    launch_contracts = d.get("host_launch_contracts") or {}
    kinds = d.get("remotes") or {}
    # Require the second independently source-authored physical transition
    # with its typed host-owned Remote pair before selecting this adapter.
    launches = [
        name for name, motion in motions.items()
        if isinstance(motion, dict)
        and motion.get("kind") == "vehicle_world_transition"
        and name != owner.name
        and any(isinstance(route, dict)
                and route.get("service") == name
                and route.get("kind") == kinds.get(remote) == "RemoteFunction"
                and isinstance(
                    typed.get(remote) or launch_contracts.get(remote), dict)
                and (typed.get(remote) or
                     launch_contracts.get(remote)).get("transport_only") is True
                for remote, route in actions.items())
    ]
    return len(launches) == 1


def eligible_ship_attachment(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not module.module_id.startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = module.name if module.kind == ModuleKind.SERVER_MODULE else module.name.removesuffix("Client") + "Server"
    owner = next((p for p in getattr(proposal, "modules", [])
                  if p.kind == ModuleKind.SERVER_MODULE and p.name == server), None)
    if owner is None:
        return None
    desc = owner.description.casefold()
    # This adapter handles an *add-once* section contract, not the separately
    # supported remove/replace/upgrade assembly workflow.
    lacks_strict_evidence = (
        not re.search(r"\b(?:spaceship|ship|vessel)\s+(?:assembly|construction)\b", desc)
        or not re.search(r"\b(?:modular\s+)?sections?\b", desc)
        or not re.search(r"\b(?:add|attach|install|build)\b", desc)
        or not re.search(r"\b(?:duplicate|already\s+present)\b", desc)
        or not re.search(r"\b(?:performance|contribution)\b", desc)
        or not re.search(r"\b(?:build\s+context|radius|proximity|range)\b", desc)
        or not re.search(r"\b(?:persist|save|record)\w*\b", desc)
    )
    if lacks_strict_evidence and not _source_linked_section_builder(owner, proposal):
        return None
    if re.search(r"\b(?:remove|uninstall|replace|unassign)\b", desc):
        return None
    # The component must use earned resources, supplied by an actual
    # source-owned mining service, not an invented independent currency ledger.
    miners = [p for p in getattr(proposal, "modules", [])
              if p.kind == ModuleKind.SERVER_MODULE and p.name != server
              and render_host_mining(p, proposal) is not None]
    if not miners:
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(name, value) for name, value in (design.get("host_actions") or {}).items()
              if isinstance(value, dict) and value.get("service") == server]
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


def _validated_sections(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("sections"), list):
        raise ValueError("Assembly needs a sections array")
    sections = result["sections"]
    if not 1 <= len(sections) <= 8:
        raise ValueError("Assembly must define 1-8 section choices")
    unique = set()
    rows = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Each section must be an object")
        name, label = section.get("id"), section.get("label")
        cost, performance = section.get("cost"), section.get("performance")
        if (not isinstance(name, str) or not _ID.fullmatch(name)
                or name.casefold() in unique
                or not isinstance(label, str) or not 1 <= len(label.strip()) <= 54
                or type(cost) is not int or not 1 <= cost <= 1000000
                or type(performance) is not int or not 1 <= performance <= 1000):
            raise ValueError("Invalid section ID, label, resource cost, or performance")
        unique.add(name.casefold())
        rows.append({"id": name, "label": label.strip(), "cost": cost,
                     "performance": performance})
    return rows


def _catalog(proposal: Any, server: str, router: Any) -> list[dict[str, Any]]:
    store = proposal.game_design.setdefault("_host_ship_attachment_catalogs", {})
    if server in store:
        return _validated_sections({"sections": store[server]})
    if not hasattr(router, "complete_json"):
        raise ValueError("Concrete ship sections must come from bounded game-design data")
    owner = next(p for p in proposal.modules if p.name == server)
    text = (
        "Return ONLY compact JSON {sections:[{id,label,cost,performance}]}. "
        "Define 1-8 genuine section choices for this game. All costs are "
        "positive units of the real server-mined RMMInventory.resources; "
        "performance is a positive contribution for attaching that section. "
        "IDs must be ASCII stable identifiers. Do not output Luau, Roblox "
        "services, client-supplied prices, fictional ledgers, or TODOs. "
        "The host implements complete construction, player ownership and "
        "proximity checking. Game requirement: " + owner.description[:1050]
    )
    previous = ""
    for _ in range(2):
        try:
            output = router.complete_json(
                text + ("\nData validation error: " + previous if previous else ""),
                role="planner", temperature=0, max_tokens=950, json_schema=_SCHEMA,
            )
            result = _validated_sections(output)
            store[server] = result
            return result
        except Exception as exc:
            previous = str(exc)[:300]
    raise ValueError("HOST_SHIP_ATTACHMENT_CATALOG_EXHAUSTED: " + previous)


def try_ship_attachment(module: Any, proposal: Any, router: Any = None) -> str | None:
    selected = eligible_ship_attachment(module, proposal)
    if selected is None:
        return None
    server, remote = selected
    entries = _catalog(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        catalog = ",\n".join(
            "{id = " + json.dumps(row["id"]) + ", label = " +
            json.dumps(row["label"], ensure_ascii=False) +
            ", cost = " + str(row["cost"]) + "}" for row in entries
        )
        return _CLIENT.replace("__REMOTE__", json.dumps(remote)).replace("__SECTIONS__", catalog)
    catalog = ",\n".join(
        "[" + json.dumps(row["id"]) + "] = {cost = " + str(row["cost"]) +
        ", performance = " + str(row["performance"]) +
        ", ordinal = " + str(i + 1) + "}" for i, row in enumerate(entries)
    )
    result = _SERVER.replace("__SECTIONS__", catalog)
    linked = ((proposal.game_design.get("dynamic_design") or {})
              .get("host_flight_ready_builders") or {})
    if linked.get(server) == "section_attachment":
        from .host_flight_ready_attachment import render_flight_ready_attachment
        result = render_flight_ready_attachment(result)
    return result


_SERVER = r'''--!strict
-- Host owns input schema, player profile, saved parts and world changes.
local Players = game:GetService("Players")
local Service = {}
local SECTIONS = {
__SECTIONS__
}
local RANGE = 26
local lots = {}
local occupied = {}
local shipModels = {}
local function allocate(player)
    if lots[player] ~= nil then return lots[player] end
    local index = 0
    while occupied[index] do index += 1 end
    occupied[index] = true
    lots[player] = index
    return index
end
local function resolveShip(player)
    local folder = workspace:FindFirstChild("RMMPlayerShips")
    if not folder then
        folder = Instance.new("Folder")
        folder.Name = "RMMPlayerShips"
        folder.Parent = workspace
    end
    local name = "RMMShip_" .. tostring(player.UserId)
    local ship = folder:FindFirstChild(name)
    if ship and not ship:IsA("Model") then return nil end
    if not ship then
        ship = Instance.new("Model")
        ship.Name = name
        ship:SetAttribute("OwnerUserId", player.UserId)
        ship.Parent = folder
    end
    if ship:GetAttribute("OwnerUserId") ~= player.UserId then return nil end
    local anchor = ship:FindFirstChild("AssemblyAnchor")
    if anchor and not anchor:IsA("BasePart") then return nil end
    if not anchor then
        local index = allocate(player)
        anchor = Instance.new("Part")
        anchor.Name = "AssemblyAnchor"
        anchor.Anchored = true
        anchor.Size = Vector3.new(8, 1, 8)
        anchor.Position = Vector3.new(15 + (index % 12) * 22, 2,
            30 + math.floor(index / 12) * 28)
        anchor.Parent = ship
    end
    local parts = ship:FindFirstChild("AssembledSections")
    if parts and not parts:IsA("Folder") then return nil end
    if not parts then
        parts = Instance.new("Folder")
        parts.Name = "AssembledSections"
        parts.Parent = ship
    end
    shipModels[player] = ship
    return ship, anchor, parts
end
local function publish(player, profile)
    local score = 0
    if type(profile.sections) == "table" then
        for id, definition in pairs(SECTIONS) do
            local part = profile.sections[id]
            if type(part) == "table" and part.owned == true then
                score += definition.performance
            end
        end
    end
    player:SetAttribute("RMMShipAssemblyPerformance", score)
    return score
end
local function placePart(parts, anchor, id)
    local definition = SECTIONS[id]
    if not definition then return false end
    if parts:FindFirstChild(id) then return true end
    local part = Instance.new("Part")
    part.Name = id
    part.Anchored = true
    part.Size = Vector3.new(5, 2, 6)
    part.Position = anchor.Position + Vector3.new(
        definition.ordinal * 5, 4, 0)
    part:SetAttribute("RMMAssemblySection", id)
    part.Parent = parts
    return true
end
function Service.start(services)
    assert(type(services) == "table"
        and type(services.PlayerDataManager) == "table"
        and type(services.PlayerDataManager.OnReady) == "function"
        and type(services.PlayerDataManager.GetState) == "function",
        "Ship assembly requires the authoritative server profile")
    services.PlayerDataManager.OnReady(function(player)
        local profile = services.PlayerDataManager.GetState(player, "RMMShipSections")
        if not profile then return end
        if profile.sections == nil then profile.sections = {} end
        if type(profile.sections) ~= "table" then return end
        local ship, anchor, parts = resolveShip(player)
        if not ship or not anchor or not parts then return end
        for id in pairs(SECTIONS) do
            local saved = profile.sections[id]
            if type(saved) == "table" and saved.owned == true then
                placePart(parts, anchor, id)
            end
        end
        publish(player, profile)
    end)
    Players.PlayerRemoving:Connect(function(player)
        -- Destroy the complete per-session actor, not just its sections.
        -- Keeping the old anchor and pilot seat leaves an orphaned model,
        -- while its build-lot lease is released for a different player.
        local ship = shipModels[player]
        if ship then ship:Destroy() end
        shipModels[player] = nil
        if lots[player] ~= nil then
            occupied[lots[player]] = nil
            lots[player] = nil
        end
    end)
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player")
        or player.Parent ~= Players or select("#", ...) ~= 1 then
        return {success = false, reason = "invalid_request"}
    end
    local id = ...
    if type(id) ~= "string" or not SECTIONS[id] then
        return {success = false, reason = "invalid_section"}
    end
    local ship, anchor, parts = resolveShip(player)
    local character = player.Character
    local root = character and character:FindFirstChild("HumanoidRootPart")
    local human = character and character:FindFirstChildOfClass("Humanoid")
    if not ship or not root or not human or human.Health <= 0
        or not anchor or not parts or (root.Position - anchor.Position).Magnitude > RANGE then
        return {success = false, reason = "outside_build_zone"}
    end
    local manager = services.PlayerDataManager
    local profile = manager.GetState(player, "RMMShipSections")
    local inventory = manager.GetState(player, "RMMInventory")
    if not profile or not inventory then
        return {success = false, reason = "profile_loading"}
    end
    if profile.sections == nil then profile.sections = {} end
    if type(profile.sections) ~= "table" then
        return {success = false, reason = "invalid_assembly_state"}
    end
    if profile.sections[id] ~= nil then
        return {success = false, reason = "already_built"}
    end
    local resources = inventory.resources
    if resources == nil then resources = 0 end
    if type(resources) ~= "number" or resources ~= resources
        or resources % 1 ~= 0 or resources < 0 or resources > 2147483647 then
        return {success = false, reason = "invalid_inventory"}
    end
    local definition = SECTIONS[id]
    if resources < definition.cost then
        return {success = false, reason = "insufficient_resources"}
    end
    -- No DataStore call or yield occurs between validation and both updates.
    inventory.resources = resources - definition.cost
    profile.sections[id] = {owned = true, level = 1,
        performance = definition.performance}
    placePart(parts, anchor, id)
    local score = publish(player, profile)
    return {success = true, section = id, resources = inventory.resources,
        performance = score}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remotes = ReplicatedStorage:WaitForChild("Remotes", 20)
if not remotes then error("Missing host Remotes") end
local remote = remotes:WaitForChild(__REMOTE__, 20)
if not remote or not remote:IsA("RemoteFunction") then error("Invalid assembly RemoteFunction") end
local gui = Instance.new("ScreenGui")
gui.Name = "RMMShipAssembly"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local panel = Instance.new("ScrollingFrame")
panel.Size = UDim2.fromOffset(300, 310)
panel.Position = UDim2.new(1, -320, 0, 145)
panel.CanvasSize = UDim2.fromOffset(0, 800)
panel.Parent = gui
local layout = Instance.new("UIListLayout")
layout.Parent = panel
local status = Instance.new("TextLabel")
status.Size = UDim2.new(1, 0, 0, 38)
status.Text = "Approach your ship assembly pad"
status.Parent = panel
local entries = {
__SECTIONS__
}
local busy = false
for _, section in entries do
    local button = Instance.new("TextButton")
    button.Name = section.id
    button.Size = UDim2.new(1, 0, 0, 46)
    button.Text = section.label .. " - " .. tostring(section.cost) .. " ore"
    button.Parent = panel
    button.Activated:Connect(function()
        if busy then return end
        busy = true
        status.Text = "Server validating build..."
        local ok, result = pcall(function() return remote:InvokeServer(section.id) end)
        busy = false
        if ok and type(result) == "table" and result.success == true then
            button.Active = false
            button.Text = section.label .. " (built)"
            status.Text = "Installed " .. tostring(result.section)
                .. " | Ore left: " .. tostring(result.resources)
                .. " | Assembly power: " .. tostring(result.performance)
        else
            status.Text = "Build rejected: " ..
                tostring(ok and type(result) == "table" and result.reason or "network")
        end
    end)
end
'''