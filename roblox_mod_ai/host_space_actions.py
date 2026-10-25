"""Fail-closed host Luau for a connected space-combat/colony/mining loop.

The model declares requirements, not mutable Roblox state or Lua code.
Only source-matched typed RemoteFunction pairs enter this implementation.
"""
from __future__ import annotations
import json
from .spec import ModuleKind

RULES = {
    "AlienCombat": ("combat target", "combat state", "AlienTarget", "alien", "Attack alien"),
    "MarkPlanetColonized": ("planet owned", "colonized state", "PlayerOwnedPlanet", "planet", "Colonize planet"),
    "ExtractOtherPlanetMineral": ("mineral deposit", "owned mineral", "OtherPlanetMineralDepos", "ore", "Mine alien mineral"),
    "WeaponPerformanceUpgrade": ("weapon's owner", "performance state", None, "owned_weapon", "Upgrade owned weapon"),
}


def _role(server):
    for prefix, (a, b, _, _, _) in RULES.items():
        if (server.name.startswith(prefix) and a in server.description.casefold()
                and b in server.description.casefold()):
            return prefix
    return None


def render_host_space_action(module, proposal):
    if not module.module_id.startswith("dyn_") or module.kind not in (
            ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    links = design.get("module_remotes", {}).get(module.module_id, [])
    if len(links) != 1:
        return None
    remote = links[0]
    spec = design.get("host_typed_actions", {}).get(remote)
    if not isinstance(spec, dict) or not spec.get("transport_only"):
        return None
    if design.get("remotes", {}).get(remote) != "RemoteFunction":
        return None
    contract = spec.get("contract", {})
    if ([(f.get("id"), f.get("type")) for f in contract.get("inputs", [])]
            != [("selection", "text"), ("quantity", "integer")]
            or contract.get("target") != {"kind": "none"}):
        return None
    server = next((m for m in proposal.modules
                   if m.kind == ModuleKind.SERVER_MODULE and m.name == spec.get("server")), None)
    if server is None:
        return None
    role = _role(server)
    if role is None:
        return None
    if module.kind == ModuleKind.SERVER_MODULE and module.name != server.name:
        return None
    if module.kind == ModuleKind.CLIENT_SCRIPT and module.name != spec.get("client"):
        return None
    if role != "WeaponPerformanceUpgrade":
        roles = {_role(m) for m in proposal.modules if m.kind == ModuleKind.SERVER_MODULE}
        if not {"AlienCombat", "MarkPlanetColonized", "ExtractOtherPlanetMineral"} <= roles:
            return None
    world, builder = {}, ""
    if role != "WeaponPerformanceUpgrade":
        bindings = design.get("host_vehicle_identity_bindings") or []
        if not isinstance(bindings, list) or len(bindings) != 1:
            return None
        builder = bindings[0].get("builder")
        if not builder or not any(m.name == builder and m.kind == ModuleKind.SERVER_MODULE
                                  for m in proposal.modules):
            return None
        objects = design.get("world_objects") or []
        targets = [o["name"] for o in objects if isinstance(o, dict)
                   and o.get("class") == "Part" and isinstance(o.get("name"), str)
                   and o["name"].startswith(RULES[role][2])]
        arrivals = design.get("host_arrival_materializations") or []
        binding = bindings[0]
        launch = binding.get("server")
        landing = [a for a in arrivals if isinstance(a, dict)
                   and a.get("server") == launch
                   and a.get("builder") == builder
                   and isinstance(a.get("arrival"), str)]
        # The launch service and the space action must agree on the same
        # materialized destination, not a guessed prefix.
        if len(targets) != 1 or len(landing) != 1:
            return None
        arrival_name = landing[0]["arrival"]
        if sum(o.get("name") == arrival_name and o.get("class") == "Part"
               for o in objects if isinstance(o, dict)) != 1:
            return None
        world = {"target": targets[0], "arrival": arrival_name}
    return (_client(remote, role) if module.kind == ModuleKind.CLIENT_SCRIPT
            else _server(role, world, builder))


LUA = '''--!strict
-- Host-validated server action; client supplies no prices or ownership IDs.
local Players = game:GetService("Players")
local Service = {}
local recent = setmetatable({}, {__mode="k"})
local function integer(n, hi)
    return type(n)=="number" and n==n and n%1==0 and n>=0 and n<=hi
end
__WORLD_HELPERS__
function Service.start(services)
    assert(services.PlayerDataManager and type(services.PlayerDataManager.GetState)=="function", "Space action requires PlayerDataManager.GetState")
    Players.PlayerRemoving:Connect(function(p) recent[p]=nil end)
    __PLACE_TARGET__
    services.PlayerDataManager.OnReady(function(p)
        local saved=services.PlayerDataManager.GetState(p,__NAMESPACE__)
        if saved then __RESTORE__ end
    end)
end
function Service.handleAction(player,services,...)
    if typeof(player)~="Instance" or not player:IsA("Player")
        or player.Parent~=Players or select("#",...)~=1 then return {success=false,reason="player"} end
    local args=...
    if typeof(args)~="table" or args.selection~=__ACTION__
        or not integer(args.quantity,__MAX_Q__) or args.quantity<1 then
        return {success=false,reason="input"} end
    for k in pairs(args) do
        if k~="selection" and k~="quantity" then return {success=false,reason="extra"} end
    end
    local now=os.clock()
    if recent[player] and now-recent[player]<0.45 then return {success=false,reason="cooldown"} end
    local state=services.PlayerDataManager.GetState(player,__NAMESPACE__)
    if not state then return {success=false,reason="loading"} end
    __ENSURE_TARGET__
__EFFECT__
end
return Service
'''

PLANET_WORLD_HELPERS = '''local function near(player, name)
    local target=workspace:FindFirstChild(name,true)
    local char=player.Character
    local human=char and char:FindFirstChildOfClass("Humanoid")
    local root=char and char:FindFirstChild("HumanoidRootPart")
    return target and target:IsA("BasePart") and human and human.Health>0
        and root and root:IsA("BasePart") and (root.Position-target.Position).Magnitude<=24
end
local function arrived(player,services,markerName)
    local builder=services[__BUILDER__]
    if not builder or type(builder.GetOwnedActor)~="function" then return false end
    local ship=builder.GetOwnedActor(player)
    local marker=workspace:FindFirstChild(markerName,true)
    return ship and ship:IsA("Model") and ship.Parent~=nil
        and ship:GetAttribute("OwnerUserId")==player.UserId
        and marker and marker:IsA("BasePart")
        and (ship:GetPivot().Position-marker.Position).Magnitude<=80
end
-- The planner places authored planet targets on the ground (Y=2), but
-- the same launch contract moves the craft to orbit (Y=8000). Put the
-- action surface near the *real* arrival point or gameplay is impossible.
-- This relocation touches only the exact source-bound gameplay target.
local function placePlanetActionTarget()
    local marker=workspace:FindFirstChild(__ARRIVAL__,true)
    local target=workspace:FindFirstChild(__TARGET__,true)
    if not marker or not marker:IsA("BasePart")
        or not target or not target:IsA("BasePart") then return false end
    target.Anchored=true
    target.CFrame=marker.CFrame*CFrame.new(__OFFSET_X__,12,__OFFSET_Z__)
    target.Size=Vector3.new(6,7,6)
    return true
end
'''

EFFECTS = {
    "AlienCombat": '''    if not arrived(player,services,__ARRIVAL__) or not near(player,__TARGET__) then
        return {success=false,reason="not_on_planet"} end
    local hp=state.alienHp
    if hp==nil then hp=3 end
    if not integer(hp,3) or hp==0 then return {success=false,reason="defeated"} end
    recent[player]=now
    hp-=1
    state.alienHp=hp
    if hp==0 then state.planetOwned=true end
    player:SetAttribute("RMMPlanetOwned",state.planetOwned==true)
    player:SetAttribute("RMMAlienCombatState",hp==0 and "won" or "attacking")
    return {success=true,hp=hp,planetOwned=state.planetOwned==true}''',
    "MarkPlanetColonized": '''    if not arrived(player,services,__ARRIVAL__) or not near(player,__TARGET__) then
        return {success=false,reason="not_on_planet"} end
    if state.planetOwned~=true then return {success=false,reason="not_owned"} end
    if state.colonized==true then return {success=false,reason="already_colonized"} end
    recent[player]=now
    state.colonized=true
    state.colonizedAt=os.time()
    player:SetAttribute("RMMPlanetColonized",true)
    return {success=true,colonized=true}''',
    "ExtractOtherPlanetMineral": '''    if not arrived(player,services,__ARRIVAL__) or not near(player,__TARGET__) then
        return {success=false,reason="not_on_planet"} end
    if state.colonized~=true then return {success=false,reason="not_colonized"} end
    local stock=state.mineralRemaining
    if stock==nil then stock=100 end
    local amount=state.minerals
    if amount==nil then amount=0 end
    if not integer(stock,100) or not integer(amount,2147483600)
        or args.quantity>stock or amount+args.quantity>2147483600 then
        return {success=false,reason="depleted"} end
    recent[player]=now
    state.mineralRemaining=stock-args.quantity
    state.minerals=amount+args.quantity
    return {success=true,minerals=state.minerals,remaining=state.mineralRemaining}''',
    "WeaponPerformanceUpgrade": '''    local inv=services.PlayerDataManager.GetState(player,"RMMInventory")
    if not inv or type(inv.items)~="table" or not integer(inv.items.owned_weapon,2147483600)
        or inv.items.owned_weapon<1 then return {success=false,reason="not_owned"} end
    local tier=state.tier or 0
    if not integer(tier,1) or tier>=1 then return {success=false,reason="max"} end
    local stats=player:FindFirstChild("leaderstats")
    local coins=stats and stats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value<100 then
        return {success=false,reason="funds"} end
    recent[player]=now
    coins.Value-=100
    state.tier=1
    player:SetAttribute("RMMWeaponPerformanceTier",1)
    return {success=true,tier=1,coins=coins.Value}''',
}
RESTORE = {
    "AlienCombat": 'p:SetAttribute("RMMPlanetOwned",saved.planetOwned==true)',
    "MarkPlanetColonized": 'p:SetAttribute("RMMPlanetColonized",saved.colonized==true)',
    "ExtractOtherPlanetMineral": 'p:SetAttribute("RMMPlanetMinerals",saved.minerals or 0)',
    "WeaponPerformanceUpgrade": 'p:SetAttribute("RMMWeaponPerformanceTier",saved.tier or 0)',
}


def _server(role, world, builder):
    action = RULES[role][3]
    effect = EFFECTS[role]
    for k, v in (("ARRIVAL", world.get("arrival", "")),
                 ("TARGET", world.get("target", ""))):
        effect = effect.replace("__"+k+"__", json.dumps(v))
    namespace = "RMMWeaponProgress" if role == "WeaponPerformanceUpgrade" else "RMMPlanetProgress"
    is_planet = role != "WeaponPerformanceUpgrade"
    offsets = {"AlienCombat": (10, -6),
               "MarkPlanetColonized": (14, 5),
               "ExtractOtherPlanetMineral": (-10, 5)}
    x, z = offsets.get(role, (0, 0))
    return (LUA.replace("__WORLD_HELPERS__", PLANET_WORLD_HELPERS if is_planet else "")
            .replace("__BUILDER__", json.dumps(builder))
            .replace("__PLACE_TARGET__", "placePlanetActionTarget()" if is_planet else "-- No world action target")
            .replace("__ENSURE_TARGET__", 'if not placePlanetActionTarget() then return {success=false,reason="target_not_ready"} end' if is_planet else '-- No planet target')
            .replace("__OFFSET_X__", str(x)).replace("__OFFSET_Z__", str(z))
            .replace("__TARGET__", json.dumps(world.get("target", "")))
            .replace("__ARRIVAL__", json.dumps(world.get("arrival", "")))
            .replace("__ACTION__", json.dumps(action))
            .replace("__MAX_Q__", "10" if role == "ExtractOtherPlanetMineral" else "1")
            .replace("__NAMESPACE__", json.dumps(namespace))
            .replace("__RESTORE__", RESTORE[role])
            .replace("__EFFECT__", effect))


def _client(remote, role):
    action, label = RULES[role][3:]
    index = list(RULES).index(role)
    return '''--!strict
-- Host-generated controls: users never enter internal IDs.
local Players=game:GetService("Players")
local ReplicatedStorage=game:GetService("ReplicatedStorage")
local player=Players.LocalPlayer
local remote=ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
assert(remote:IsA("RemoteFunction"), "Space action requires a RemoteFunction")
local gui=Instance.new("ScreenGui")
gui.Name=__GUI__
gui.ResetOnSpawn=false
gui.Parent=player:WaitForChild("PlayerGui")
local button=Instance.new("TextButton")
button.Size=UDim2.fromOffset(220,40)
button.Position=UDim2.new(1,-235,0,__Y__)
button.Text=__LABEL__
button.Parent=gui
local status=Instance.new("TextLabel")
status.Size=UDim2.fromOffset(220,38)
status.Position=UDim2.new(1,-235,0,__SY__)
status.Parent=gui
local busy=false
button.Activated:Connect(function()
    if busy then return end
    busy=true
    local ok,res=pcall(function()
        return remote:InvokeServer({selection=__ACTION__,quantity=1})
    end)
    busy=false
    if ok and type(res)=="table" then
        status.Text=res.success and "Success" or "Rejected: "..tostring(res.reason)
    else status.Text="Request failed" end
end)
'''.replace("__REMOTE__",json.dumps(remote)).replace("__GUI__",json.dumps("RMM_"+role))\
        .replace("__ACTION__",json.dumps(action)).replace("__LABEL__",json.dumps(label))\
        .replace("__Y__",str(180+index*90)).replace("__SY__",str(223+index*90))
