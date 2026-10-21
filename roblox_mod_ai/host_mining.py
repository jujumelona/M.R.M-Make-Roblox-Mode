"""Host-owned mining: validated world target, proximity, cooldown, persistent Coins.

Only applies when an accepted authored plan defines a real resource Part and
exactly one host-owned RemoteFunction or world ProximityPrompt action.
Does not substitute for unrelated game mechanics.
"""
from __future__ import annotations

import json
import re

from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal
from .host_mining_nodes import mining_world_nodes

_NODES = re.compile(r"resource.*(?:node|deposit)|ore.*(?:node|deposit)", re.I)


def mining_rewards_currency(owner: RobloxModuleSpec, proposal: RobloxProposal) -> bool:
    """True only if the accepted plan explicitly sources Coins from gathering."""
    description = owner.description.casefold()
    if any(token in description for token in ("currency", "coin", "credit")):
        return True
    return any(
        peer.kind == ModuleKind.SERVER_MODULE and peer.name != owner.name
        and re.search(r"\b(?:resource[- ]gathering|mining|gathering)\s+actions?\b", peer.description, re.I)
        and re.search(r"\b(?:award|grant|credit|earn)\w*\b", peer.description, re.I)
        and re.search(r"\b(?:currency|coins?|credits?)\b", peer.description, re.I)
        for peer in getattr(proposal, "modules", [])
    )


def _bind_verified_mined_income(
    source: str, proposal: RobloxProposal, paid_by_miner: bool,
) -> str:
    """Connect a real successful server mining action to the earned ledger.

    No client-submitted amounts or extra remotes are involved. The persisted
    totalMined counter is monotonic, and the ledger pays each increment once.
    """
    if paid_by_miner:
        return source  # Never pay twice when the miner itself grants Coins.
    from .host_earned_currency import matching_ledger
    selected = matching_ledger(proposal)
    if selected is None:
        return source
    service, _ = selected
    preflight = """    local mined = progress.totalMined
    if mined == nil then mined = 0 end
    if type(mined) ~= "number" or mined ~= mined or mined < 0
        or mined % 1 ~= 0 or mined >= 2147483647 then return false end
"""
    before = '    node.remaining -= 1\n'
    after = '    progress.resources = balance + 1\n'
    if source.count(before) != 1 or source.count(after) != 1:
        raise ValueError("Verified mining host template contract drift")
    source = source.replace(before, preflight + before)
    post = ('    progress.totalMined = mined + 1\n'
            + '    local rewardService = services[' + json.dumps(service) + ']\n'
            + '    if type(rewardService) == "table"'
              ' and type(rewardService.recordMiningReward) == "function" then\n'
              '        rewardService.recordMiningReward(player, services)\n'
              '    end\n')
    return source.replace(after, after + post)


def render_host_mining(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    if not module.module_id.startswith("dyn_"):
        return None
    if module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    owner = next((peer for peer in getattr(proposal, "modules", [])
                  if peer.kind == ModuleKind.SERVER_MODULE and peer.name == server), None)
    description = (owner.description if owner else module.description).lower()
    service_tokens = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", server)
    if (not re.search(r"\b(?:mining|mine|ore|gather|gathering|harvest|harvesting)\b", service_tokens, re.I)
            or not re.search(r"mining|mine|ore|gather|harvest|resource", description)
            or not re.search(r"\b(?:validat|radius|distance|proximity|range|node|deposit|deplet|cooldown|gather)\w*\b", description)):
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    # A mineable source-owned Part is the actual evidence of the resource.
    # Do not reject "mining a static world object" solely because its prose
    # does not spell out the words "resource" or "ore".
    nodes = mining_world_nodes(proposal, owner or module)
    if not nodes:
        return None
    routes = [(name, binding) for name, binding in
              (design.get("host_actions") or {}).items()
              if isinstance(binding, dict) and binding.get("service") == server]
    world_routes = [(name, binding) for name, binding in
                    (design.get("host_world_actions") or {}).items()
                    if isinstance(binding, dict) and binding.get("service") == server]
    # A service has ONE verified ingress contract. Never guess which callback
    # format the host will provide or duplicate player-facing transports.
    if len(routes) + len(world_routes) != 1:
        return None
    reward_currency = mining_rewards_currency(owner or module, proposal)
    if world_routes:
        world_name = world_routes[0][0]
        if (module.kind != ModuleKind.SERVER_MODULE
                or not module.file_path.startswith("src/server/")
                or world_name not in nodes):
            return None
        # Bootstrap already installs ProximityPrompt.Triggered and passes the
        # real target Part to handleAction(player, services, targetPart).
        # Do not create a client or Remote for this mode.
        template = _SERVER if reward_currency else _SERVER_RESOURCES_ONLY
        code = template.replace("__NODES__", "{" + json.dumps(world_name) + "}")
        return _bind_verified_mined_income(code, proposal, reward_currency)
    if routes[0][1].get("kind") != "RemoteFunction":
        return None
    remote = routes[0][0]
    lua_nodes = "{" + ", ".join(json.dumps(node) for node in nodes) + "}"
    no_args = routes[0][1].get("max_args") == 0
    if module.kind == ModuleKind.SERVER_MODULE:
        template = (_SERVER_NEAREST if no_args else _SERVER) if reward_currency else (_SERVER_RESOURCES_NEAREST if no_args else _SERVER_RESOURCES_ONLY)
        code = template.replace("__NODES__", lua_nodes)
        return _bind_verified_mined_income(code, proposal, reward_currency)
    if not module.file_path.startswith("src/client/"):
        return None
    ui = _CLIENT_NEAREST if no_args else _CLIENT
    if not reward_currency:
        ui = _CLIENT_RESOURCES_NEAREST if no_args else _CLIENT_RESOURCES_ONLY
    return ui.replace("__NODES__", lua_nodes).replace("__REMOTE__", json.dumps(remote))


_SERVER = r'''--!strict
local Players = game:GetService("Players")
local Service = {}
local NODE_NAMES = __NODES__
local NODE_INITIAL = 100
local COOLDOWN = 0.7
local MAX_RANGE = 18
local nodes = {}
local recent = setmetatable({}, {__mode = "k"})

local function validNode(part)
    if typeof(part) ~= "Instance" or not part:IsA("BasePart") then return false end
    if not part:IsDescendantOf(workspace) then return false end
    for _, name in NODE_NAMES do
        if part.Name == name and workspace:FindFirstChild(name, true) == part then
            return true
        end
    end
    return false
end
local function getNode(part)
    if not validNode(part) then return nil end
    if nodes[part] then return nodes[part] end
    nodes[part] = {remaining = NODE_INITIAL}
    part:SetAttribute("RemainingResources", NODE_INITIAL)
    part:SetAttribute("ResourceDepleted", false)
    return nodes[part]
end
function Service.start(services)
    assert(type(services) == "table" and
        type(services.PlayerDataManager) == "table" and
        type(services.PlayerDataManager.GetState) == "function",
        "PlayerDataManager.GetState is required")
    for _, name in NODE_NAMES do
        local part = workspace:FindFirstChild(name, true)
        if part and part:IsA("BasePart") then getNode(part) end
    end
end
function Service.handleAction(player, services, ...)
    if typeof(player) ~= "Instance" or not player:IsA("Player") or player.Parent ~= Players then return false end
    if select("#", ...) ~= 1 then return false end
    local part = ...
    local node = getNode(part)
    if not node or node.remaining <= 0 then return false end
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0 or not root then return false end
    if (root.Position - part.Position).Magnitude > MAX_RANGE then return false end
    local progress = services.PlayerDataManager.GetState(player, "RMMInventory")
    if not progress then return false end
    local balance = progress.resources
    if balance == nil then balance = 0 end
    if type(balance) ~= "number" or balance ~= balance or balance < 0
        or balance % 1 ~= 0 or balance >= 2147483647 then return false end
    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value > 2147483646 then return false end
    local now = os.clock()
    if recent[player] and now - recent[player] < COOLDOWN then return false end
    recent[player] = now
    node.remaining -= 1
    coins.Value += 1
    progress.resources = balance + 1
    part:SetAttribute("RemainingResources", node.remaining)
    part:SetAttribute("ResourceDepleted", node.remaining == 0)
    return {success = true, remaining = node.remaining,
            credits = coins.Value, resources = progress.resources}
end
return Service
'''

_CLIENT = r'''--!strict
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild(__REMOTE__)
local NODE_NAMES = __NODES__
local gui = Instance.new("ScreenGui")
gui.Name = "RMMMiningPanel"
gui.ResetOnSpawn = false
gui.Parent = player:WaitForChild("PlayerGui")
local button = Instance.new("TextButton")
button.Name = "Mine"
button.Size = UDim2.fromOffset(175, 48)
button.Position = UDim2.new(0, 16, 1, -112)
button.Text = "Mine nearby node"
button.Parent = gui
local status = Instance.new("TextLabel")
status.Name = "MiningResult"
status.Size = UDim2.fromOffset(320, 35)
status.Position = UDim2.new(0, 16, 1, -64)
status.Text = "Approach a resource node"
status.Parent = gui
local busy = false
button.Activated:Connect(function()
    if busy then return end
    local root = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
    if not root then return end
    local target = nil
    local best = 18
    for _, name in NODE_NAMES do
        local node = workspace:FindFirstChild(name, true)
        if node and node:IsA("BasePart")
            and node:GetAttribute("ResourceDepleted") ~= true then
            local distance = (node.Position - root.Position).Magnitude
            if distance <= best then target = node; best = distance end
        end
    end
    if not target then status.Text = "No nearby node"; return end
    busy = true
    local ok, result = pcall(function() return remote:InvokeServer(target) end)
    busy = false
    if ok and type(result) == "table" and result.success == true then
        status.Text = "Coins: " .. tostring(result.credits) ..
            " | Ore: " .. tostring(result.resources) ..
            " | Remaining: " .. tostring(result.remaining)
    else
        status.Text = "Mining rejected: range, cooldown, depleted, or loading"
    end
end)
'''

# The gateway enforces zero wire arguments for this route. Select a real node
# from the server's own workspace using the live player's position; never trust
# a claimed client target, distance, or reward.
_SERVER_NEAREST = _SERVER.replace(
    '''    if select("#", ...) ~= 1 then return false end
    local part = ...
    local node = getNode(part)
    if not node or node.remaining <= 0 then return false end
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0 or not root then return false end
    if (root.Position - part.Position).Magnitude > MAX_RANGE then return false end''',
    '''    if select("#", ...) ~= 0 then return false end
    local character = player.Character
    local humanoid = character and character:FindFirstChildOfClass("Humanoid")
    local root = character and character:FindFirstChild("HumanoidRootPart")
    if not humanoid or humanoid.Health <= 0 or not root then return false end
    local part = nil
    local best = MAX_RANGE
    for _, name in NODE_NAMES do
        local candidate = workspace:FindFirstChild(name, true)
        if candidate and validNode(candidate) then
            local resource = getNode(candidate)
            if resource and resource.remaining > 0 then
                local distance = (root.Position - candidate.Position).Magnitude
                if distance <= best then
                    part = candidate
                    best = distance
                end
            end
        end
    end
    if not part then return false end
    local node = getNode(part)
    if not node or node.remaining <= 0 then return false end'''
)
assert _SERVER_NEAREST != _SERVER, "Host mining ABI changed without updating no-arg path"

# Visual node selection is UI-only; host still chooses/verifies the target.
_CLIENT_NEAREST = _CLIENT.replace(
    'remote:InvokeServer(target)', 'remote:InvokeServer()'
)
assert _CLIENT_NEAREST != _CLIENT, "Host mining client ABI changed"


# Resource-only harvesting uses the same validated world source and the same
# host-owned RMMInventory namespace, without inventing a money reward.
_RESOURCE_COIN_CHECK = '''    local leaderstats = player:FindFirstChild("leaderstats")
    local coins = leaderstats and leaderstats:FindFirstChild("Coins")
    if not coins or not coins:IsA("IntValue") or coins.Value > 2147483646 then return false end
'''
assert _RESOURCE_COIN_CHECK in _SERVER, "Host mining ledger ABI changed"
_SERVER_RESOURCES_ONLY = (_SERVER
    .replace(_RESOURCE_COIN_CHECK, "")
    .replace('    coins.Value += 1\n', "")
    .replace('credits = coins.Value, resources = progress.resources',
             'resources = progress.resources'))
assert "coins.Value" not in _SERVER_RESOURCES_ONLY

_SERVER_RESOURCES_NEAREST = (_SERVER_NEAREST
    .replace(_RESOURCE_COIN_CHECK, "")
    .replace('    coins.Value += 1\n', "")
    .replace('credits = coins.Value, resources = progress.resources',
             'resources = progress.resources'))
assert "coins.Value" not in _SERVER_RESOURCES_NEAREST

_CLIENT_RESOURCES_ONLY = _CLIENT.replace(
    'status.Text = "Coins: " .. tostring(result.credits) ..\n            " | Ore: " .. tostring(result.resources) ..',
    'status.Text = "Resources: " .. tostring(result.resources) ..')
assert _CLIENT_RESOURCES_ONLY != _CLIENT, "Mining HUD ABI changed"
_CLIENT_RESOURCES_NEAREST = _CLIENT_NEAREST.replace(
    'status.Text = "Coins: " .. tostring(result.credits) ..\n            " | Ore: " .. tostring(result.resources) ..',
    'status.Text = "Resources: " .. tostring(result.resources) ..')
assert _CLIENT_RESOURCES_NEAREST != _CLIENT_NEAREST, "Mining HUD ABI changed"
