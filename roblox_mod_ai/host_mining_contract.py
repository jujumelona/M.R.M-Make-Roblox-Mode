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
from .host_mining_nodes import mining_world_nodes
from .world_interaction_placement import place_first_interaction, spawn_anchor, spawn_size

_MINE = re.compile(r"\b(?:mining|mines?|ores?|harvest(?:ing)?|gather(?:ing)?)\b|채굴|자원파밍", re.I)
_SERVICE_MINE = re.compile(r"\b(?:mining|mine|ore|gather|gathering|harvest|harvesting)\b", re.I)
_RESOURCE = re.compile(r"resource|ore|mineral|자원|광물", re.I)
_REWARD = re.compile(r"currency|coins?|credits?|earn|돈|화폐", re.I)
_NODE = re.compile(r"resource.*node|ore.*node|ore.*deposit", re.I)


def _is_named_mining_service(name: str, description: str, prompt: str) -> bool:
    # A specific game request and module role must both support this action.
    # Split CamelCase service identifiers: CoreEconomy contains the letters
    # "ore" but is NOT a mining mechanic. ResourceMining remains eligible.
    service_tokens = re.sub(
        r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)",
        " ", name,
    )
    explicit_mining_source = bool(re.search(
        r"\b(?:mining|mines?|harvesting|gathering|extracting)\b"
        r".{0,65}\b(?:resource|ore|mineral)\s+(?:node|deposit)\b",
        description, re.I,
    ))
    # Short planner-generated module names can truncate "Gathering" to
    # "Gatherin"; the fully authored behavioral contract is authoritative.
    # Require an actual source-node interaction, not merely the word "ore"
    # inside an unrelated economy module's CamelCase name.
    return bool(
        (_SERVICE_MINE.search(service_tokens) or explicit_mining_source)
        and _MINE.search(prompt)
        and (_RESOURCE.search(description) or _MINE.search(description))
        # Resource-only harvesting is legitimate without minting coins.
        # The generic host miner already has an inventory-only implementation;
        # previously this reward clause incorrectly excluded it and forced
        # the tiny coder to guess an entire Luau runtime.
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
    mutations: list[dict[str, Any]] = []
    # The local model may supply only a *transport* form, not a gameplay
    # contract. Host-owned nearest-node mining has a stricter input ABI:
    # a server-selected world Part and ZERO client claims about yield/cost.
    # Do not rewrite a genuine typed gameplay specification.
    def host_transport_only(route: str) -> bool:
        spec = (design.get("host_typed_actions") or {}).get(route)
        if not isinstance(spec, dict) or spec.get("transport_only") is not True:
            return False
        contract = spec.get("contract")
        fields = contract.get("inputs") if isinstance(contract, dict) else None
        return bool(isinstance(contract, dict)
                    and isinstance(fields, list)
                    and len(fields) == 2
                    and contract.get("target") == {"kind": "none"}
                    and contract.get("state_changes") == []
                    and {f.get("id") for f in fields
                         if isinstance(f, dict)} == {"selection", "quantity"})

    for module in proposal.modules:
        if module.kind != ModuleKind.SERVER_MODULE or not module.module_id.startswith("dyn_"):
            continue
        if not _is_named_mining_service(module.name, module.description, proposal.requested_prompt):
            continue
        routed = [(name, row) for name, row in actions.items()
                  if isinstance(row, dict) and row.get("service") == module.name]
        routes = [row for _, row in routed]
        worlds = [key for key, row in
                  (design.get("host_world_actions") or {}).items()
                  if isinstance(row, dict) and row.get("service") == module.name]
        if len(routes) != 1 or worlds or routes[0].get("kind") != "RemoteFunction":
            continue
        remote, route = routed[0]
        rebased = host_transport_only(remote)
        # Preserve source-requested batch/multi-item mining semantics; only
        # replace an ungrounded generic host transport shell.
        if rebased and re.search(
                r"\b(?:batch(?:es)?|bulk|quantity|multiple\s+at\s+once)\b|"
                r"대량|수량|한\s*번에",
                module.description + " " + proposal.requested_prompt, re.I):
            rebased = False
        # A zero-argument mining request can be secure when the HOST selects
        # the closest planned Part by server-measured player distance.
        planned = mining_world_nodes(proposal, module)
        if planned:
            # Preserve an existing source-owned world target. Normalize ONLY
            # unsupported transport-only input when an actual server node can
            # safely satisfy the requested one-action mining effect.
            if rebased:
                route["max_args"] = 0
                design["host_typed_actions"].pop(remote, None)
                mutations.append({
                    "service": module.name, "resource_node": planned[0],
                    "input": "host_verified_nearest_resource",
                    "transport_rebased": True,
                    "basis": "server_authoritative_resource_interaction",
                })
            continue
        stem = re.findall(r"\d{5,}", module.name)
        suffix = (stem[0] if stem else
                  hashlib.sha256(module.name.encode("utf-8")).hexdigest()[:10].upper())
        node = "ResourceNode" + suffix + "1"
        for idx in range(2, 1000):
            if node not in reserved_names:
                break
            node = "ResourceNode" + suffix + str(idx)
        else:
            raise ValueError("Could not allocate a unique mined resource Part")
        # Use authored geometry and actual spawn, never a fixed coordinate,
        # game genre or object-count-derived position.
        anchor = spawn_anchor(
            proposal.game_design,
            round_lobby=any(m.module_id == "mod_arena_round"
                            for m in proposal.modules),
        )
        position = place_first_interaction(
            objects, anchor=anchor,
            spawn_bounds=spawn_size(proposal.game_design),
            size=(4.0, 4.0, 4.0),
            max_distance=18.0,
        )
        obj = {"name": node, "class": "Part",
               "position": list(position), "size": [4.0, 4.0, 4.0]}
        objects.append(obj)
        reserved_names.add(node)
        for peer in proposal.modules:
            if peer.name == module.name or (
                    peer.name == module.name.removesuffix("Server") + "Client"):
                linked = owned.setdefault(peer.module_id, [])
                if not isinstance(linked, list):
                    raise ValueError("module_world_objects rows must be lists")
                if node not in linked:
                    linked.append(node)
        if rebased:
            # Both the UI and gateway read the SAME mutable design route.
            # They now call a deterministic host template, not 9B Luau.
            route["max_args"] = 0
            design["host_typed_actions"].pop(remote, None)
        mutations.append({
            "service": module.name, "resource_node": node,
            "transport_rebased": rebased,
            "input": ("RemoteFunction_server_selected_nearest_Part"
                      if routes[0].get("max_args") == 0
                      else "RemoteFunction_with_server_verified_Part"),
            "basis": "user_requested_resource_mining",
        })
    if mutations:
        design["module_world_objects"] = owned
        design.setdefault("host_materialized_world", []).extend(mutations)
    return mutations
