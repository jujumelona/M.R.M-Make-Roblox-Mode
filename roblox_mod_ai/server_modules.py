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
    return (
        "--!strict\n"
        "-- Host-generated startup. Modules share the same server-only registry.\n"
        "local ServerScriptService = game:GetService(\"ServerScriptService\")\n"
        "local names = {\n" + table_rows + "\n}\n"
        "local services: {[string]: any} = {}\n"
        "for _, name in names do\n"
        "    local scriptModule = ServerScriptService:WaitForChild(name)\n"
        "    if not scriptModule:IsA(\"ModuleScript\") then\n"
        "        error(\"Expected server ModuleScript: \" .. name)\n"
        "    end\n"
        "    services[name] = require(scriptModule)\n"
        "end\n"
        "for _, name in names do\n"
        "    local service = services[name]\n"
        "    if type(service) == \"table\" and type(service.start) == \"function\" then\n"
        "        service.start(services)\n"
        "    end\n"
        "end\n"
    )


def module_bootstrap_contract(module: RobloxModuleSpec, proposal: RobloxProposal) -> str:
    if not (module.module_id.startswith("dyn_")
            and module.kind == ModuleKind.SERVER_MODULE):
        return ""
    registry = [m.name for m in proposal.modules if m.module_id.startswith("dyn_")
                and m.roblox_service == RobloxService.SERVER_SCRIPT_SERVICE
                and m.file_path.endswith(".luau")
                and not m.file_path.endswith(".server.luau")]
    return (
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
