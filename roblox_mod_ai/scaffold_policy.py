"""Fail-closed policy for small-model gameplay units.

A planned action with host-owned Remote ingress should not fall back to a
6000-token whole ModuleScript after one failed 850/1500-token body. That
fallback was the principal repeated failure pattern in uploaded runs.

Existing host-owned templates still take precedence, while truly unowned or
passive modules may use the legacy general-purpose coder. Keep all rejected
micro-snippets and parser errors in the existing failure ZIP contract.
"""
from __future__ import annotations

from typing import Any

from .agent_loop import LuauGenerationError
from .spec import ModuleKind


def single_host_action(proposal: Any, module: Any) -> bool:
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.SERVER_MODULE
            or not module.file_path.startswith("src/server/")):
        return False
    design = proposal.game_design.get("dynamic_design") or {}
    actions = [row for row in (design.get("host_actions") or {}).values()
               if isinstance(row, dict) and row.get("service") == module.name]
    worlds = [row for row in (design.get("host_world_actions") or {}).values()
              if isinstance(row, dict) and row.get("service") == module.name]
    return len(actions) + len(worlds) == 1


def single_client_action(proposal: Any, module: Any) -> bool:
    if (not module.module_id.startswith("dyn_")
            or module.kind != ModuleKind.CLIENT_SCRIPT
            or not module.file_path.startswith("src/client/")
            or not module.file_path.endswith(".client.luau")):
        return False
    design = proposal.game_design.get("dynamic_design") or {}
    linked = (design.get("module_remotes") or {}).get(module.module_id)
    if not isinstance(linked, list) or len(linked) != 1:
        return False
    name = linked[0]
    action = (design.get("host_actions") or {}).get(name)
    if (not isinstance(action, dict) or action.get("kind") != "RemoteFunction"
            or action.get("max_args") == 0
            or (design.get("remotes") or {}).get(name) != "RemoteFunction"):
        return False
    owner = action.get("service")
    if not isinstance(owner, str) or module.name != owner.removesuffix("Server") + "Client":
        return False
    return any(peer.kind == ModuleKind.SERVER_MODULE and peer.name == owner
               for peer in proposal.modules)


def scaffold_exhausted(module: Any, attempts: Any, unit: str) -> LuauGenerationError:
    history = [item for item in attempts if isinstance(item, dict)] if isinstance(attempts, list) else []
    diagnostics = [
        "SCOPED_" + unit.upper() + "_EXHAUSTED: the short-model task failed; "
        "do not retry the same failure as a full 6000-token ModuleScript. "
        "Revise the action contract or regenerate this bounded unit."
    ]
    for attempt in history[-3:]:
        diagnostics.extend(str(x)[:800] for x in attempt.get("diagnostics", [])[:2])
    return LuauGenerationError(
        module.name,
        str(history[-1].get("candidate") or "") if history else "",
        diagnostics,
        history=history,
    )

def single_passive_service(proposal: Any, module: Any) -> bool:
    """Authorize a no-ingress server startup unit from an actual authored plan."""
    from .host_architecture import requires_player_ingress
    if not (module.module_id.startswith("dyn_")
            and module.kind == ModuleKind.SERVER_MODULE
            and module.file_path.startswith("src/server/")
            and module.file_path.endswith(".luau")
            and not module.file_path.endswith(".server.luau")):
        return False
    design = proposal.game_design.get("dynamic_design") or {}
    if not design:
        return False
    for key in ("host_actions", "host_world_actions"):
        if any(isinstance(row, dict) and row.get("service") == module.name
               for row in (design.get(key) or {}).values()):
            return False
    # Absence of a host route is NOT evidence of passivity. Custom pet
    # hatching and other model-owned client/server pairs may bind their own
    # interaction code; converting them to start-only silently breaks them.
    import re
    description = module.description.casefold()
    passive_intent = re.search(
        r"\\b(?:automatically|autonomous(?:ly)?|passive(?:ly)?|"
        r"on startup|on server start|world setup|environment setup|"
        r"scene setup|background simulation|server initialization)\\b",
        description,
    )
    return bool(passive_intent) and not requires_player_ingress(
        module.name, module.description)
