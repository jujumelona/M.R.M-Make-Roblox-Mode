"""Host resource-paid, add-once modular ship assembly.

Covers an authored create-only section builder with a parent-hull build pad,
max section count and resource debit. Uses the existing audited server-owned
physical placement and persistence implementation. Never treats a shop item
purchase as an already installed ship part or trusts AI-generated Luau.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .spec import ModuleKind
from .host_ship_attachment import _catalog, _SERVER, _CLIENT
from .host_mining import render_host_mining

_MAX_SECTIONS = 8


def eligible_resource_ship_builder(module: Any, proposal: Any) -> tuple[str, str] | None:
    if (not getattr(module, "module_id", "").startswith("dyn_")
            or module.kind not in (ModuleKind.SERVER_MODULE, ModuleKind.CLIENT_SCRIPT)):
        return None
    server = (module.name if module.kind == ModuleKind.SERVER_MODULE
              else module.name.removesuffix("Client") + "Server")
    owner = next((m for m in getattr(proposal, "modules", ())
                  if m.kind == ModuleKind.SERVER_MODULE and m.name == server), None)
    if owner is None:
        return None
    desc = owner.description.casefold()
    conditions = (
        r"\b(?:ship|spaceship)\s+assembly\s+state\b",
        r"\bsections?\s+build\b|\bbuild\s+sections?\b|\bsection\s+types?\b",
        r"\bparent\s+hull\b",
        r"\b(?:resource|materials?)\b",
        r"\b(?:deduct|spend|consume)\w*\b",
        r"\b(?:validat|reject|check)\w*\b",
        r"\b(?:maximum|max)\s+section\s+count\b",
        r"\b(?:add|build|construct)\w*\b",
    )
    if not all(re.search(p, desc) for p in conditions):
        return None
    if re.search(r"\b(?:remov\w*|replac\w*|refund\w*|detach\w*|uninstall\w*)\b", desc):
        return None
    # The resource debit must correspond to a true server-only mineral source.
    miners = [m for m in proposal.modules
              if m.kind == ModuleKind.SERVER_MODULE and m.name != server
              and render_host_mining(m, proposal) is not None]
    if not miners:
        return None
    design = proposal.game_design.get("dynamic_design") or {}
    routes = [(name, value) for name, value in (design.get("host_actions") or {}).items()
              if isinstance(value, dict) and value.get("service") == server]
    if len(routes) != 1:
        return None
    remote, binding = routes[0]
    maximum = binding.get("max_args")
    if (binding.get("kind") != "RemoteFunction"
            or (design.get("remotes") or {}).get(remote) != "RemoteFunction"
            or (maximum is not None and (type(maximum) is not int or maximum < 1))):
        return None
    if module.kind == ModuleKind.SERVER_MODULE:
        if not module.file_path.startswith("src/server/"):
            return None
    else:
        if (module.name != server.removesuffix("Server") + "Client"
                or not module.file_path.startswith("src/client/")
                or not module.file_path.endswith(".client.luau")):
            return None
        declared = (design.get("module_remotes") or {}).get(module.module_id)
        if declared is not None and remote not in declared:
            return None
    return server, remote


def try_resource_ship_builder(
    module: Any, proposal: Any, router: Any = None,
) -> str | None:
    selected = eligible_resource_ship_builder(module, proposal)
    if selected is None:
        return None
    server, remote = selected
    rows = _catalog(proposal, server, router)
    if module.kind == ModuleKind.CLIENT_SCRIPT:
        entries = ",\n".join(
            "{id = " + json.dumps(row["id"]) + ", label = " +
            json.dumps(row["label"], ensure_ascii=False) + ", cost = " +
            str(row["cost"]) + "}" for row in rows
        )
        return _CLIENT.replace("__REMOTE__", json.dumps(remote)).replace(
            "__SECTIONS__", entries)
    entries = ",\n".join(
        "[" + json.dumps(row["id"]) + "] = {cost = " + str(row["cost"])
        + ", performance = " + str(row["performance"])
        + ", ordinal = " + str(i + 1) + "}" for i, row in enumerate(rows)
    )
    source = _SERVER.replace("__SECTIONS__", entries)
    linked = ((proposal.game_design.get("dynamic_design") or {})
              .get("host_flight_ready_builders") or {})
    if linked.get(server) == "resource_ship_builder":
        from .host_flight_ready_attachment import render_flight_ready_attachment
        source = render_flight_ready_attachment(source)
    marker = (
        '    if profile.sections[id] ~= nil then\n'
        '        return {success = false, reason = "already_built"}\n'
        '    end\n'
    )
    if source.count(marker) != 1:
        raise ValueError("Resource ship attachment template ABI changed")
    limit = (
        '    local sectionCount = 0\n'
        '    for _ in pairs(profile.sections) do sectionCount += 1 end\n'
        '    if sectionCount >= ' + str(_MAX_SECTIONS) + ' then\n'
        '        return {success = false, reason = "ship_section_limit"}\n'
        '    end\n'
    )
    return source.replace(marker, marker + limit)
