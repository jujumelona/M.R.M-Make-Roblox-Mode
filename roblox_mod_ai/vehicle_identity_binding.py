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
