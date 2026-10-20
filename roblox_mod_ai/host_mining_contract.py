"""Repair missing Roblox mining world wiring from the user's authored mechanic.

A client cannot securely report its own resource yield. Mining must target a
server-known resource object. When a scoped, server-owned mining RemoteFunction
exists but the plan omitted every mineable Part, materialize ONE deterministic
Part in the existing authored world plan. Preserve unrelated world content and
reject ambiguous remote/service ownership instead of hiding validation errors.
This is a request-specific world prerequisite, not a generic scenery fallback.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .spec import ModuleKind, RobloxProposal

_MINE = re.compile(r"mining|mine|ore|채굴|자원파밍", re.I)
_SERVICE_MINE = re.compile(r"\b(?:mining|mine|ore)\b", re.I)
_RESOURCE = re.compile(r"resource|ore|mineral|자원|광물", re.I)
_REWARD = re.compile(r"currency|coins?|credits?|earn|돈|화폐", re.I)
_NODE = re.compile(r"resource.*node|ore.*node|ore.*deposit", re.I)


def _is_named_mining_service(name: str, description: str, prompt: str) -> bool:
    # A specific game request and module role must both support this action.
    # Split CamelCase service identifiers: CoreEconomy contains the letters
    # "ore" but is NOT a mining mechanic. ResourceMining remains eligible.
    service_tokens = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return bool(
        _SERVICE_MINE.search(service_tokens)
        and _MINE.search(prompt)
        and _RESOURCE.search(description)
        and _REWARD.search(description)
        and _RESOURCE.search(prompt)
    )


def ensure_mining_world_contract(proposal: RobloxProposal) -> list[dict[str, Any]]:
    """Ensure host-owned mining has an actual declared Part, never a fake yield.

    Returns records of materialized target Parts. This changes only the authored
    proposal before gameplay/codegen starts, not any model-generated Lua.
    """
    design = proposal.game_design.get("dynamic_design")
    if not isinstance(design, dict):
        return []
    objects = design.get("world_objects")
    actions = design.get("host_actions")
    if not isinstance(objects, list) or not isinstance(actions, dict):
        return []
    owned = design.get("module_world_objects", {})
    if not isinstance(owned, dict):
        raise ValueError("module_world_objects must be a module-id dictionary")
    reserved_names = {
        obj.get("name") for obj in objects if isinstance(obj, dict)
    }
    occupied = {
        (tuple(obj.get("position") or ()))
        for obj in objects if isinstance(obj, dict)
    }
    mutations: list[dict[str, Any]] = []
    for module in proposal.modules:
        if module.kind != ModuleKind.SERVER_MODULE or not module.module_id.startswith("dyn_"):
            continue
        if not _is_named_mining_service(module.name, module.description, proposal.requested_prompt):
            continue
        routes = [row for row in actions.values()
                  if isinstance(row, dict) and row.get("service") == module.name]
        worlds = [key for key, row in
                  (design.get("host_world_actions") or {}).items()
                  if isinstance(row, dict) and row.get("service") == module.name]
        if len(routes) != 1 or worlds or routes[0].get("kind") != "RemoteFunction":
            continue
        if routes[0].get("max_args") == 0:
            # This no-argument route cannot provide a physically selected Part.
            continue
        stem = re.findall(r"\d{5,}", module.name)
        planned = [obj.get("name") for obj in objects
                   if isinstance(obj, dict) and obj.get("class") == "Part"
                   and isinstance(obj.get("name"), str)
                   and _NODE.search(obj["name"])
                   and (not stem or any(x in obj["name"] for x in stem))]
        if planned:
            continue
        suffix = (stem[0] if stem else
                  hashlib.sha256(module.name.encode("utf-8")).hexdigest()[:10].upper())
        node = "ResourceNode" + suffix + "1"
        for idx in range(2, 1000):
            if node not in reserved_names:
                break
            node = "ResourceNode" + suffix + str(idx)
        else:
            raise ValueError("Could not allocate a unique mined resource Part")
        slot = len(objects)
        while True:
            position = (float(24 + slot % 17 * 12), 2.0,
                        float(24 + slot // 17 * 12))
            if position not in occupied:
                break
            slot += 1
        obj = {"name": node, "class": "Part",
               "position": list(position), "size": [4.0, 4.0, 4.0]}
        objects.append(obj)
        reserved_names.add(node)
        occupied.add(position)
        for peer in proposal.modules:
            if peer.name == module.name or (
                    peer.name == module.name.removesuffix("Server") + "Client"):
                linked = owned.setdefault(peer.module_id, [])
                if not isinstance(linked, list):
                    raise ValueError("module_world_objects rows must be lists")
                if node not in linked:
                    linked.append(node)
        mutations.append({
            "service": module.name, "resource_node": node,
            "input": "RemoteFunction_with_server_verified_Part",
            "basis": "user_requested_resource_mining",
        })
    if mutations:
        design["module_world_objects"] = owned
        design.setdefault("host_materialized_world", []).extend(mutations)
    return mutations
