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
# A source mention does not authorize resource mining when it explicitly
# forbids that mechanic. This is a source permission gate, not a generic
# English keyword check; err on the side of preserving the user's prohibition.
_FORBID_MINE = re.compile(
    r"\b(?:without|no|never|exclude|excluding|forbid|forbids)\b"
    r".{0,45}\b(?:mine|mining|harvest\w*|gather\w*|"
    r"collect\w*|extract\w*)\b|"
    r"\b(?:do(?:es)?\s+not|don't|doesn't|cannot|can't)\b"
    r".{0,25}\b(?:mine|mining|harvest\w*|gather\w*|"
    r"collect\w*|extract\w*)\b|"
    r"(?:채굴|수집|파밍|채취)\s*(?:없|금지|하지\s*않)",
    re.I,
)
_NEGATED_EXTRACT = re.compile(
    r"\b(?:no|never|not|without|cannot|can't|doesn't|don't|"
    r"does\s+not|do\s+not)\b"
    r".{0,55}\b(?:extract\w*|mine\w*|harvest\w*|gather\w*)\b",
    re.I,
)


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
    # Log40: the atomic source owner was a descriptive action rather than a
    # "MiningServer" service. It explicitly acquired actual resource from a
    # mineable WORLD source into the player's owned inventory, but the name
    # check rejected that verified gameplay. Match the *complete* semantic
    # world->owned-inventory transition, not a keyword in the service name.
    # The caller still requires one genuine server RemoteFunction, a source
    # request for mining, unique world target, and an exclusively transport-
    # only two-field ABI before handing off to the executable host miner.
    # A resource transition remains the same gameplay action when a small
    # model mentions the player's inventory BEFORE the mineable world source.
    # Require a local connection from the extraction verb to all three
    # independently relevant facts; matching the word "resource" alone would
    # incorrectly turn a shop or inventory reader into a mine.
    def nearby(left: str, right: str, maximum: int) -> bool:
        lhs = list(re.finditer(left, description, re.I))
        rhs = list(re.finditer(right, description, re.I))
        return any(abs(a.start() - b.start()) <= maximum
                   for a in lhs for b in rhs)

    extraction = r"\b(?:extract\w*|harvest\w*|mine|mines|mined|mining)\b"
    physical_source = (
        r"\b(?:mineable|harvestable|resource\s+(?:node|source)|"
        r"ore\s+(?:node|deposit)|mineral\s+deposit)\b"
    )
    owned_inventory = (
        r"\b(?:player['’]?s?|owned)\b.{0,95}\b(?:inventory|cargo)\b"
    )
    source_owned_extraction = bool(
        not _NEGATED_EXTRACT.search(description)
        and nearby(extraction, physical_source, 190)
        and nearby(extraction, r"\b(?:resources?|minerals?|ores?)\b", 160)
        and nearby(extraction, owned_inventory, 250)
    )
    # Short planner-generated module names can truncate "Gathering" to
    # "Gatherin"; the fully authored behavioral contract is authoritative.
    # Require an actual source-node interaction, not merely the word "ore"
    # inside an unrelated economy module's CamelCase name.
    return bool(
        (_SERVICE_MINE.search(service_tokens) or explicit_mining_source
         or source_owned_extraction)
        and _MINE.search(prompt)
        and not _FORBID_MINE.search(prompt)
        and (_RESOURCE.search(description) or _MINE.search(description))
        # Resource-only harvesting is legitimate without minting coins.
        # The generic host miner already has an inventory-only implementation;
        # previously this reward clause incorrectly excluded it and forced
        # the tiny coder to guess an entire Luau runtime.
        and _RESOURCE.search(prompt)
    )


def _source_traced_extraction(module: Any, proposal: RobloxProposal) -> bool:
    """Recover a world-resource producer using audited source ownership.

    Model-authored service descriptions may omit the words "mine" and
    "harvest" even while the audited requirement explicitly assigns that
    exact service an extraction from a validated deposit into owned inventory.
    This is *not* permission to invent a reward: the actual host miner still
    requires one authenticated Remote and an owned, materialized world Part.
    """
    if _FORBID_MINE.search(proposal.requested_prompt):
        return False
    name = re.sub(
        r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)",
        " ", str(getattr(module, "name", "")),
    )
    description = str(getattr(module, "description", "") or "")
    if _NEGATED_EXTRACT.search(description):
        return False
    role = name + " " + description
    if not re.search(r"\b(?:extract\w*|harvest\w*|mining|mine|gather\w*)\b",
                     role, re.I):
        return False
    ledger = (proposal.game_design.get("implementation_blueprint") or {})
    requirements = ledger.get("requirements") or []
    if not isinstance(requirements, list):
        return False
    for item in requirements:
        if (not isinstance(item, dict)
                or module.name not in (item.get("owners") or [])
                or not isinstance(item.get("source"), str)
                or not item["source"].strip()):
            continue
        acceptance = str(item.get("acceptance") or "")
        if (re.search(r"\b(?:extract\w*|harvest\w*|mine|gather\w*)\b",
                      acceptance, re.I)
                and re.search(r"\b(?:resource\w*|mineral\w*|ores?)\b",
                              acceptance, re.I)
                and re.search(r"\b(?:world|deposit|node|mineable)\b",
                              acceptance, re.I)
                and re.search(r"\b(?:owned|player['’]?s?)\b",
                              acceptance, re.I)
                and re.search(r"\b(?:inventory|cargo)\b",
                              acceptance, re.I)):
            return True
    return False


def inspect_mining_contract_gates(proposal: RobloxProposal) -> list[dict[str, Any]]:
    """Read-only evidence for source-owned mining routing and materialization.

    Cross-system blockers must name the failed authority edge instead of
    reporting only that the downstream assembled vehicle is absent.
    """
    design = (proposal.game_design.get("dynamic_design") or {})
    if not isinstance(design, dict):
        return []
    from .host_mining import render_host_mining
    out = []
    actions = design.get("host_actions") or {}
    worlds = design.get("host_world_actions") or {}
    remotes = design.get("remotes") or {}
    typed = design.get("host_typed_actions") or {}
    for module in proposal.modules:
        if module.kind != ModuleKind.SERVER_MODULE or not module.module_id.startswith("dyn_"):
            continue
        named = bool(_is_named_mining_service(
            module.name, module.description, proposal.requested_prompt
        ))
        traced = bool(_source_traced_extraction(module, proposal))
        if not (named or traced):
            continue
        routed = [(key, val) for key, val in actions.items()
                  if isinstance(val, dict) and val.get("service") == module.name]
        world_routed = [(key, val) for key, val in worlds.items()
                        if isinstance(val, dict) and val.get("service") == module.name]
        route_kinds = [
            {"name": key, "kind": val.get("kind"),
             "declared_remote_kind": remotes.get(key),
             "transport_only": bool(isinstance(typed.get(key), dict)
                                    and typed[key].get("transport_only") is True),
             "input_ids": [
                 item.get("id") for item in (
                     (((typed.get(key) or {}).get("contract") or {}).get("inputs") or [])
                     if isinstance((typed.get(key) or {}).get("contract") or {}, dict)
                     else []
                 ) if isinstance(item, dict)
             ]}
            for key, val in routed
        ]
        source = render_host_mining(module, proposal)
        out.append({
            "service": module.name,
            "recognized_by_description": named,
            "recognized_by_source_blueprint": traced,
            "remote_routes": route_kinds,
            "world_routes": [key for key, _ in world_routed],
            "owned_world_nodes": mining_world_nodes(proposal, module),
            "host_materialized_world": [
                x for x in (design.get("host_materialized_world") or [])
                if isinstance(x, dict) and x.get("service") == module.name
            ],
            "host_mining_renderer_eligible": source is not None,
        })
    return out


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
        if not (_is_named_mining_service(module.name, module.description, proposal.requested_prompt)
                or _source_traced_extraction(module, proposal)):
            continue
        routed = [(name, row) for name, row in actions.items()
                  if isinstance(row, dict) and row.get("service") == module.name]
        routes = [row for _, row in routed]
        worlds = [key for key, row in
                  (design.get("host_world_actions") or {}).items()
                  if isinstance(row, dict) and row.get("service") == module.name]
        # A source-owned world action is an already-authored physical ingress.
        # The old branch skipped it entirely, then the vehicle builder saw
        # zero mined-resource producers even though a real Part existed.
        # Reconcile the exact Part bound to this service; never synthesize an
        # unrelated node or redirect another service's object.
        if worlds:
            if len(worlds) != 1 or routes:
                continue
            world_name = worlds[0]
            node_obj = next((
                obj for obj in objects
                if isinstance(obj, dict) and obj.get("name") == world_name
                and obj.get("class") == "Part"
            ), None)
            if node_obj is None:
                continue
            linked = owned.setdefault(module.module_id, [])
            if not isinstance(linked, list):
                raise ValueError("module_world_objects rows must be lists")
            if world_name not in linked:
                linked.append(world_name)
            mutations.append({
                "service": module.name, "resource_node": world_name,
                "transport_rebased": True,
                "input": "host_verified_world_action_Part",
                "basis": "existing_source_owned_world_interaction",
            })
            continue
        if len(routes) != 1 or routes[0].get("kind") != "RemoteFunction":
            continue
        remote, route = routed[0]
        rebased = host_transport_only(remote)
        # Preserve source-requested batch/multi-item mining semantics; only
        # replace an ungrounded generic host transport shell.
        # "quantity" and "수량" describe ordinary transaction accounting
        # too; they do not request batch mining. Reject host one-at-a-time
        # normalization only for an explicit multi-item *single request*.
        if rebased and re.search(
                r"\b(?:batch(?:es)?|bulk|multiple\s+at\s+once|"
                r"multiple\s+(?:items?|ores?|resources?)\s+per\s+(?:action|click))\b|"
                r"대량|한\s*번에",
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
