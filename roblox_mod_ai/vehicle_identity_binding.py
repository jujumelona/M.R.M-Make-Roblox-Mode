"""Resolve physically identical producer->consumer vehicle actors before Luau.

The host creates world Instances and module-to-world assignments. It MUST also
own identity edges between a builder and a vehicle movement system: a model
cannot repair a separately fabricated placeholder by writing more Luau.

This binder never invents a vehicle, chooses among ambiguous roots, edits
unrelated objects, or asserts that physics/welds are gameplay-verified.
"""
from __future__ import annotations

import re
from typing import Any

from .vehicle_identity_contract import _BUILD, _VEHICLE

_VEHICLE_NAME = re.compile(
    r"ship|spacecraft|craft|vehicle|vessel|rocket|shuttle|"
    r"car|train|aircraft|boat|plane|raft", re.I,
)
# "root/chassis/frame" denotes a physical actor root. "hull/body" is a
# fallback ONLY if there is no primary root and is unique.
_PRIMARY_ROOT = re.compile(r"root|chassis|frame", re.I)
_FALLBACK_ROOT = re.compile(r"hull|body", re.I)
_AUXILIARY = re.compile(
    r"seat|occupant|passenger|crew|destination|planet|spawn|arrival", re.I
)
_VALID_CLASS = {"Part", "MeshPart", "Model", "UnionOperation"}


def bind_verified_vehicle_providers(proposal: Any) -> list[dict[str, Any]]:
    """Bind a launch to the unique first-party assembled Model provider.

    A builder's dynamic player-owned Model is not a static world Part. When
    the source-authorized ordered-assembly compiler owns GetOwnedActor(player),
    a launcher must consume that provider directly instead of guessing which
    of several decorative Craft Parts is the playable vehicle.
    """
    from .host_ordered_assembly import eligible_ordered_assembly
    from .spec import ModuleKind

    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design")
    if not isinstance(design, dict):
        return []
    motions = design.get("host_world_motion")
    ownership = design.get("module_world_objects")
    if not isinstance(motions, dict) or not isinstance(ownership, dict):
        return []
    modules = {m.name: m for m in getattr(proposal, "modules", ())}
    builders = [
        m for m in modules.values()
        if getattr(m, "kind", None) == ModuleKind.SERVER_MODULE
        and _BUILD.search(str(getattr(m, "description", "")))
        and _VEHICLE.search(str(getattr(m, "description", "")))
        and eligible_ordered_assembly(m, proposal) is not None
    ]
    # Refuse ambiguous builders: only an actual host compiled builder can
    # promise GetOwnedActor, and never bind to an unrelated visible ship.
    if len(builders) != 1:
        return []
    builder = builders[0]
    routes = design.get("host_typed_actions") or {}
    actions = design.get("host_actions") or {}
    remote_kinds = design.get("remotes") or {}
    remotes_by_module = design.get("module_remotes") or {}
    if not all(isinstance(x, dict) for x in
               (routes, actions, remote_kinds, remotes_by_module)):
        return []
    changes = []
    for owner_name, motion in motions.items():
        if (owner_name not in modules or not isinstance(motion, dict)
                or motion.get("kind") != "vehicle_world_transition"
                or motion.get("actor_identity_source") == "verified_owned_actor_provider"):
            continue
        server = modules[owner_name]
        if (getattr(server, "kind", None) != ModuleKind.SERVER_MODULE
                or server == builder):
            continue
        assigned = [(name, binding) for name, binding in actions.items()
                    if isinstance(binding, dict)
                    and binding.get("service") == owner_name]
        if len(assigned) != 1:
            continue
        remote, binding = assigned[0]
        if (binding.get("kind") != "RemoteFunction"
                or remote_kinds.get(remote) != "RemoteFunction"):
            continue
        typed = routes.get(remote)
        if (not isinstance(typed, dict)
                or typed.get("transport_only") is not True
                or typed.get("server") != server.name):
            continue
        client = modules.get(typed.get("client"))
        if (client is None or getattr(client, "kind", None) != ModuleKind.CLIENT_SCRIPT
                or client.name != server.name.removesuffix("Server") + "Client"
                or not client.file_path.endswith(".client.luau")
                or remotes_by_module.get(server.module_id) not in (None, [remote])
                or remotes_by_module.get(client.module_id) not in (None, [remote])):
            continue
        # Both controller sides remain linked to the source-authored world.
        # Their decorative Craft Parts are NOT repurposed as the actual Model.
        if not isinstance(ownership.get(server.module_id), list) or not isinstance(
                ownership.get(client.module_id), list):
            continue
        motion["builder_module_id"] = builder.module_id
        motion["actor_identity_source"] = "verified_owned_actor_provider"
        motion["actor_provider"] = "GetOwnedActor"
        # A previously guessed actor_world_name is not runtime authority.
        motion.pop("actor_world_name", None)
        motion.pop("actor_world_class", None)
        changes.append({
            "server": server.name, "client": client.name, "builder": builder.name,
            "actor_provider": "GetOwnedActor", "actor": None,
            "physical_assembly_verified": False,
        })
    if changes:
        design.setdefault("host_vehicle_identity_bindings", []).extend(changes)
    return changes


def bind_vehicle_actors(proposal: Any) -> list[dict[str, Any]]:
    """Bind an unambiguous authored builder root to server AND client routes.

    All selections are made from existing materialized names. Each operation
    checks every affected reference before mutation, then changes those
    references together. Unknown/ambiguous identities remain untouched for
    vehicle_identity_errors to report as an implementation-contract failure.
    """
    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design")
    if not isinstance(design, dict):
        return []
    motions = design.get("host_world_motion")
    ownership = design.get("module_world_objects")
    world = design.get("world_objects")
    if (not isinstance(motions, dict) or not isinstance(ownership, dict)
            or not isinstance(world, list)):
        return []
    objects = {
        obj["name"]: obj
        for obj in world if isinstance(obj, dict)
        and isinstance(obj.get("name"), str)
        and obj.get("class") in _VALID_CLASS
    }
    modules = {m.name: m for m in getattr(proposal, "modules", ())}
    builders = [
        m for m in modules.values()
        if str(getattr(m, "module_id", "")).startswith("dyn_")
        and str(getattr(m, "file_path", "")).startswith("src/server/")
        and _BUILD.search(str(getattr(m, "description", "")))
        and _VEHICLE.search(str(getattr(m, "description", "")))
    ]
    if not builders:
        return []
    changes: list[dict[str, Any]] = []
    routes = design.get("host_typed_actions") or {}
    if not isinstance(routes, dict):
        routes = {}
    for launch_name, motion in motions.items():
        if (isinstance(motion, dict)
                and motion.get("actor_identity_source") == "verified_owned_actor_provider"):
            continue
        if (not isinstance(motion, dict)
                or motion.get("kind") != "vehicle_world_transition"
                or launch_name not in modules):
            continue
        consumer = modules[launch_name]
        linked = ownership.get(consumer.module_id)
        if not isinstance(linked, list):
            continue
        linked_real = [name for name in linked if name in objects]
        if not linked_real:
            continue
        if any(
            set(linked_real) & set(ownership.get(b.module_id) or ())
            for b in builders if b.name != launch_name
        ):
            continue  # Shared identity already exists. No mutation.
        # Demand exactly one root *across all builders*. A model-authored
        # scene with multiple vehicles must provide an explicit identity.
        candidate_roots: dict[str, str] = {}
        for builder in builders:
            if builder.name == launch_name:
                continue
            for name in ownership.get(builder.module_id) or ():
                if name not in objects or not _VEHICLE_NAME.search(name):
                    continue
                if _PRIMARY_ROOT.search(name) or _FALLBACK_ROOT.search(name):
                    candidate_roots[name] = builder.name
        primary = [name for name in candidate_roots if _PRIMARY_ROOT.search(name)]
        fallback = [name for name in candidate_roots if _FALLBACK_ROOT.search(name)]
        choices = primary if primary else fallback
        if len(choices) != 1:
            continue  # No guessing and no false success.
        root = choices[0]
        builder = modules[candidate_roots[root]]
        # Isolate one old launch actor, not passenger/seat/arrival entities.
        old_actor = [
            name for name in linked_real
            if _VEHICLE_NAME.search(name) and not _AUXILIARY.search(name)
        ]
        if len(old_actor) != 1:
            continue
        old = old_actor[0]
        # Use the already-declared paired client of exactly this Remote.
        paired: list[Any] = []
        for spec in routes.values():
            if not isinstance(spec, dict) or spec.get("server") != launch_name:
                continue
            client = modules.get(spec.get("client"))
            if client is None or not str(client.file_path).endswith(".client.luau"):
                continue
            client_links = ownership.get(client.module_id)
            if not isinstance(client_links, list) or old not in client_links:
                continue
            paired.append(client)
        if len(paired) != 1:
            continue
        client = paired[0]
        # Commit atomically after validating both ends. Preserve all nonactor
        # references and the original world object: another system may use it.
        affected = [consumer.module_id, client.module_id]
        old_lists = {id_: list(ownership[id_]) for id_ in affected}
        for id_, names in old_lists.items():
            next_names = [root if item == old else item for item in names]
            ownership[id_] = list(dict.fromkeys(next_names))
        motion["actor_world_name"] = root
        motion["builder_module_id"] = builder.module_id
        motion["actor_world_class"] = objects[root]["class"]
        motion["actor_identity_source"] = "unique_host_materialized_builder_root"
        changes.append({
            "server": launch_name,
            "client": client.name,
            "builder": builder.name,
            "actor": root,
            "replaced_placeholder": old,
            "physical_assembly_verified": False,
        })
    if changes:
        design.setdefault("host_vehicle_identity_bindings", []).extend(changes)
    return changes


def materialize_source_linked_space_arrivals(proposal: Any) -> list[dict[str, Any]]:
    """Create a real orbit arrival only for a uniquely bound, host-owned ship.

    This is a *world prerequisite*, not a claim of playtested flight. In a
    sourced assembly->launch chain, a missing destination used to force the
    9B coder to invent workspace.Orbit and misuse the assembly root as a Model.
    An unrelated mover or an ambiguous ship does not qualify.
    """
    from hashlib import sha256
    from .host_ordered_assembly import eligible_ordered_assembly

    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design")
    if not isinstance(design, dict):
        return []
    motions = design.get("host_world_motion")
    ownership = design.get("module_world_objects")
    world = design.get("world_objects")
    if not isinstance(motions, dict) or not isinstance(ownership, dict) or not isinstance(world, list):
        return []
    modules = {mod.name: mod for mod in getattr(proposal, "modules", [])}
    by_id = {mod.module_id: mod for mod in getattr(proposal, "modules", [])}
    results = []
    for owner_name, motion in motions.items():
        if (not isinstance(motion, dict)
                or motion.get("kind") != "vehicle_world_transition"
                or not re.search(r"space|orbit", str(motion.get("destination", "")), re.I)):
            continue
        owner = modules.get(owner_name)
        builder = by_id.get(motion.get("builder_module_id"))
        actor = motion.get("actor_world_name")
        provider_link = (motion.get("actor_identity_source") ==
                         "verified_owned_actor_provider"
                         and motion.get("actor_provider") == "GetOwnedActor")
        world_link = (owner is not None and builder is not None
                      and isinstance(actor, str)
                      and actor in (ownership.get(owner.module_id) or [])
                      and actor in (ownership.get(builder.module_id) or []))
        if (owner is None or builder is None
                or eligible_ordered_assembly(builder, proposal) is None
                or not (provider_link or world_link)):
            continue
        # Only a complete host builder exposes the Model returned by
        # GetOwnedActor(player), rather than the materialized Part root.
        routes = [(remote, row) for remote, row in
                  (design.get("host_actions") or {}).items()
                  if isinstance(row, dict) and row.get("service") == owner_name]
        if len(routes) != 1 or routes[0][1].get("kind") != "RemoteFunction":
            continue
        typed = (design.get("host_typed_actions") or {}).get(routes[0][0])
        if not isinstance(typed, dict) or typed.get("transport_only") is not True:
            continue
        client = modules.get(typed.get("client"))
        if (client is None or typed.get("server") != owner_name
                or actor not in (ownership.get(client.module_id) or [])):
            continue
        names = {obj.get("name"): obj for obj in world if isinstance(obj, dict)}
        current_refs = ownership.get(owner.module_id) or []
        existing = [name for name in current_refs
                    if re.search(r"arrival|landing", str(name), re.I)
                    and names.get(name, {}).get("class") in ("Part", "MeshPart")]
        if existing:
            continue  # Use a real previously declared destination.
        arrival = "RMMOrbitArrival_" + sha256(owner.module_id.encode("utf-8")).hexdigest()[:10]
        if arrival in names:
            # A name collision must not silently rebind another author's Part.
            continue
        dest_number = sum(1 for obj in world if isinstance(obj, dict)
                          and str(obj.get("name", "")).startswith("RMMOrbitArrival_"))
        world.append({"name": arrival, "class": "Part",
                      "position": [0.0, 8000.0 + 300.0 * dest_number, 0.0],
                      "size": [96.0, 4.0, 96.0]})
        ownership[owner.module_id] = list(dict.fromkeys(current_refs + [arrival]))
        ownership[client.module_id] = list(dict.fromkeys(
            (ownership.get(client.module_id) or []) + [arrival]))
        motion["arrival_world_name"] = arrival
        motion["arrival_source"] = "host_materialized_source_linked_orbit"
        results.append({"server": owner_name, "builder": builder.name,
                        "client": client.name, "arrival": arrival,
                        "studio_verified": False})
    if results:
        design.setdefault("host_arrival_materializations", []).extend(results)
    return results
