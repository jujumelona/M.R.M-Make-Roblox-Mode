"""Host-generated single entry point for AI-authored server services.

Roblox's module-first design is one server Script plus requireable server
ModuleScripts. A plain .server.luau Script cannot be safely treated as a module
and shared with other services. This adaptation applies to generated dynamic
services, not to existing authored first-party scripts.
"""
from __future__ import annotations

import json

from .spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService

_BOOTSTRAP_ID = "mod_dynamic_server_bootstrap"
_BOOTSTRAP_NAME = "RMMServerBootstrap"
_BOOTSTRAP_PATH = "src/server/RMMServerBootstrap.server.luau"


def normalize_dynamic_server_modules(proposal: RobloxProposal) -> bool:
    if not proposal.game_design.get("dynamic_design"):
        return False
    changed = False
    names = set()
    for module in proposal.modules:
        if not module.module_id.startswith("dyn_"):
            continue
        if module.roblox_service != RobloxService.SERVER_SCRIPT_SERVICE:
            continue
        if module.file_path.startswith("src/server/") and module.file_path.endswith(
                ".server.luau"):
            module.file_path = module.file_path[:-len(".server.luau")] + ".luau"
            module.kind = ModuleKind.SERVER_MODULE
            # Startup ordering and services injection are owned by bootstrap,
            # not by a phantom dependency on the ReplicatedStorage bridge.
            module.depends_on = []
            changed = True
        if (module.file_path.startswith("src/server/")
                and module.file_path.endswith(".luau")
                and not module.file_path.endswith(".server.luau")):
            names.add(module.module_id)

    if not names:
        return changed
    existing = next((m for m in proposal.modules if m.module_id == _BOOTSTRAP_ID), None)
    if existing is None:
        proposal.modules.append(RobloxModuleSpec(
            module_id=_BOOTSTRAP_ID,
            name=_BOOTSTRAP_NAME,
            kind=ModuleKind.SERVER_SCRIPT,
            file_path=_BOOTSTRAP_PATH,
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
            description="Host-authored single server startup script loads and starts generated modules.",
            depends_on=sorted(names),
        ))
        changed = True
    elif set(existing.depends_on) != names:
        existing.depends_on = sorted(names)
        existing.code = ""
        changed = True
    return changed


def render_dynamic_server_bootstrap(proposal: RobloxProposal) -> str:
    modules = sorted(
        (module for module in proposal.modules
         if module.module_id.startswith("dyn_")
         and module.roblox_service == RobloxService.SERVER_SCRIPT_SERVICE
         and module.file_path.startswith("src/server/")
         and module.file_path.endswith(".luau")
         and not module.file_path.endswith(".server.luau")),
        key=lambda m: m.name,
    )
    if not modules:
        raise ValueError("No server modules to bootstrap")
    if any(m.name == _BOOTSTRAP_NAME for m in modules):
        raise ValueError("Reserved bootstrap module name collision")
    table_rows = "\n".join("    " + json.dumps(m.name) + "," for m in modules)
    active_rows = "\n".join("    " + json.dumps(m.name) + "," for m in modules
                           if m.kind == ModuleKind.SERVER_MODULE)
    source = (
        "--!strict\n"
        "-- Host-generated startup. Modules share the same server-only registry.\n"
        "local ServerScriptService = game:GetService(\"ServerScriptService\")\n"
        "local names = {\n" + table_rows + "\n}\n"
        "local active = {\n" + active_rows + "\n}\n"
        "local services: {[string]: any} = {}\n"
        "for _, name in names do\n"
        "    local scriptModule = ServerScriptService:WaitForChild(name)\n"
        "    if not scriptModule:IsA(\"ModuleScript\") then\n"
        "        error(\"Expected server ModuleScript: \" .. name)\n"
        "    end\n"
        "    services[name] = require(scriptModule)\n"
        "end\n"
        "for _, name in active do\n"
        "    local service = services[name]\n"
        "    if type(service) ~= \"table\" or type(service.start) ~= \"function\" then\n"
        "        error(\"Missing server service start(): \" .. name)\n"
        "    end\n"
        "    service.start(services)\n"
        "end\n"
    )

    # The host handles ENGINE transport and universal first-line safety, not
    # a 9B model. Game-specific permission, proximity, item ownership and
    # transaction checks remain mandatory in the exported handler.
    actions = (proposal.game_design.get("dynamic_design") or {}).get(
        "host_actions") or {}
    if not actions:
        return source
    source += (
        "\n-- Host-owned Remote ingress. AI never wires OnServerEvent itself.\n"
        "local ReplicatedStorage = game:GetService(\\"ReplicatedStorage\\")\n"
        "local Players = game:GetService(\\"Players\\")\n"
        "local remotes = ReplicatedStorage:WaitForChild(\\"Remotes\\")\n"
        "local lastAction = setmetatable({}, {__mode = \\"k\\"})\n"
        "local function allowAction(player, actionName)\n"
        "    if typeof(player) ~= \\"Instance\\" or not player:IsA(\\"Player\\") then return false end\n"
        "    if player.Parent ~= Players then return false end\n"
        "    local now = os.clock()\n"
        "    local actionsForPlayer = lastAction[player]\n"
        "    if not actionsForPlayer then\n"
        "        actionsForPlayer = {}\n"
        "        lastAction[player] = actionsForPlayer\n"
        "    end\n"
        "    local previous = actionsForPlayer[actionName]\n"
        "    if previous and now - previous < 0.08 then return false end\n"
        "    actionsForPlayer[actionName] = now\n"
        "    return true\n"
        "end\n"
    )
    names_by_id = {
        m.name for m in modules if m.kind == ModuleKind.SERVER_MODULE
    }
    for remote_name, binding in sorted(actions.items()):
        if not isinstance(binding, dict):
            raise ValueError("Invalid host Remote action definition")
        service_name, kind = binding.get("service"), binding.get("kind")
        contracts = (proposal.game_design.get("dynamic_design") or {}).get(
            "remotes") or {}
        if (service_name not in names_by_id or remote_name not in contracts or
                contracts[remote_name] != kind or
                kind not in {"RemoteEvent", "RemoteFunction"}):
            raise ValueError("Host Remote has invalid service/Remote class mapping")
        remote = json.dumps(remote_name)
        service = json.dumps(service_name)
        source += (
            "do\n"
            f"    local remote = remotes:WaitForChild({remote})\n"
            f"    if not remote:IsA({json.dumps(kind)}) then error(\\"Wrong Remote class for {remote_name}\\") end\n"
            f"    local service = services[{service}]\n"
            "    if type(service) ~= \\"table\\" or type(service.handleAction) ~= \\"function\\" then\n"
            f"        error(\\"Missing server action handler for {remote_name}\\")\n"
            "    end\n"
        )
        if kind == "RemoteEvent":
            source += (
                "    remote.OnServerEvent:Connect(function(player, ...)\n"
                f"        if not allowAction(player, {remote}) then return end\n"
                "        service.handleAction(player, services, ...)\n"
                "    end)\n"
            )
        else:
            source += (
                "    remote.OnServerInvoke = function(player, ...)\n"
                f"        if not allowAction(player, {remote}) then return nil end\n"
                "        return service.handleAction(player, services, ...)\n"
                "    end\n"
            )
        source += "end\n"
    return source


def module_bootstrap_contract(module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
    if not (module.module_id.startswith("dyn_")
            and module.kind == ModuleKind.SERVER_MODULE):
        return ""
    registry = [m.name for m in proposal.modules if m.module_id.startswith("dyn_")
                and m.roblox_service == RobloxService.SERVER_SCRIPT_SERVICE
                and m.file_path.endswith(".luau")
                and not m.file_path.endswith(".server.luau")]
    contract = (
        "SERVER MODULE CONTRACT: file ends in .luau and is a server-only "
        "ModuleScript, NOT a .server.luau auto-running Script. Return a table "
        "of callable functions at the end. For event handlers/init, expose "
        "function Service.start(services) that connects declared remotes or "
        "world/PlayerAdded events. Bootstrap requires all modules first and "
        "calls each exported .start(services) once. The services table holds "
        "the actual exported APIs by their exact names; available keys: "
        + json.dumps(sorted(registry)) +
        ". Use services.EconomyLedger.Grant/TrySpend/GetBalance where applicable. "
        "Do not require any .server.luau Scripts, create a second currency store, "
        "or write client methods on the server."
    )
    action_routes = {
        name: binding for name, binding
        in ((proposal.game_design.get("dynamic_design") or {}).get(
            "host_actions") or {}).items()
        if isinstance(binding, dict) and binding.get("service") == module.name
    }
    if action_routes:
        contract += (
            " HOST-OWNED NETWORK: bootstrap handles all RemoteEvent/"
            "RemoteFunction binding and server-side player/rate checks. "
            "Do not use OnServerEvent/OnServerInvoke, and do not bind Remotes "
            "manually. Export function Service.handleAction(player, services, ...) "
            "containing only the game-specific validation/state changes, "
            "AND function Service.start(services) for other initialization. "
            "Action routes and classes: " + json.dumps(action_routes)
        )
    return contract
