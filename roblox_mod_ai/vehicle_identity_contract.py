"""Check authored builder -> launched vehicle identity across gameplay stages.

A source request to build a vehicle and then launch it is NOT fulfilled when
the builder edits one Part and the launcher moves a separately generated Part.
Do not guess or silently rename Instances: a verified physical identity or an
explicit host-owned same-object link is required before model-code inference.
"""
from __future__ import annotations

import re
from typing import Any

_BUILD = re.compile(r"\b(?:assembl\w*|construct\w*|build\w*|install\w*)\b", re.I)
_VEHICLE = re.compile(
    r"\b(?:ship|spaceship|spacecraft|vessel|vehicle|rocket|shuttle|craft|"
    r"boat|train|aircraft)\b", re.I
)


def relevant_candidates(modules: dict[str, Any], launch_name: str) -> list[Any]:
    return [
        m for m in modules.values()
        if m.name != launch_name
        and getattr(m, "module_id", "").startswith("dyn_")
        and getattr(m, "file_path", "").startswith("src/server/")
        and _BUILD.search(str(getattr(m, "description", "")))
        and _VEHICLE.search(str(getattr(m, "description", "")))
    ]


def vehicle_identity_errors(proposal: Any) -> list[str]:
    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design") or {}
    motions = design.get("host_world_motion") or {}
    ownership = design.get("module_world_objects") or {}
    if not isinstance(motions, dict) or not isinstance(ownership, dict):
        return []
    modules = {m.name: m for m in getattr(proposal, "modules", ())}
    # Builder evidence comes from the actual authored description, not an
    # unrelated world Part named "Vehicle" or a prompt-matching exception.
    builders = [
        m for m in modules.values()
        if getattr(m, "module_id", "").startswith("dyn_")
        and getattr(m, "file_path", "").startswith("src/server/")
        and _BUILD.search(str(getattr(m, "description", "")))
        and _VEHICLE.search(str(getattr(m, "description", "")))
    ]
    errors: list[str] = []
    declared = {obj.get("name") for obj in design.get("world_objects", ())
                if isinstance(obj, dict) and isinstance(obj.get("name"), str)}
    for owner_name, spec in motions.items():
        if not isinstance(spec, dict) or spec.get("kind") != "vehicle_world_transition":
            continue
        consumer = modules.get(owner_name)
        if consumer is None:
            errors.append("VEHICLE_ACTOR_OWNER_MISSING: " + str(owner_name))
            continue
        # Provider-bound transitions move the player's runtime Model returned
        # by the verified first-party builder, not any static Craft proxy.
        if spec.get("actor_identity_source") == "verified_owned_actor_provider":
            from .host_vehicle_actor_capability import eligible_vehicle_actor_builder
            from .spec import ModuleKind
            builder = next(
                (m for m in relevant_candidates(modules, owner_name)
                 if m.module_id == spec.get("builder_module_id")), None)
            provider_valid = (
                spec.get("actor_provider") == "GetOwnedActor"
                and builder is not None
                and getattr(builder, "kind", None) == ModuleKind.SERVER_MODULE
                and eligible_vehicle_actor_builder(builder, proposal) is not None)
            actions = design.get("host_actions") or {}
            typed = design.get("host_typed_actions") or {}
            routes = [
                (remote, binding) for remote, binding in actions.items()
                if isinstance(binding, dict)
                and binding.get("service") == owner_name
                and binding.get("kind") == "RemoteFunction"
                and (design.get("remotes") or {}).get(remote) == "RemoteFunction"
                and isinstance(typed.get(remote), dict)
                and typed[remote].get("transport_only") is True
                and typed[remote].get("server") == owner_name
            ]
            if len(routes) != 1:
                provider_valid = False
            else:
                client = modules.get(typed[routes[0][0]].get("client"))
                module_routes = design.get("module_remotes") or {}
                if (client is None
                        or getattr(client, "kind", None) != ModuleKind.CLIENT_SCRIPT
                        or client.name != owner_name.removesuffix("Server") + "Client"
                        or module_routes.get(consumer.module_id) not in (None, [routes[0][0]])
                        or module_routes.get(client.module_id) not in (None, [routes[0][0]])):
                    provider_valid = False
            if not provider_valid:
                errors.append(
                    "VEHICLE_ACTOR_PROVIDER_INVALID: " + owner_name +
                    " lacks a unique source-linked first-party builder "
                    "with GetOwnedActor(player) and matching Remote pair")
            continue
        consumer_refs = set(ownership.get(consumer.module_id) or ()) & declared
        if not consumer_refs:
            errors.append(
                "VEHICLE_ACTOR_WORLD_UNRESOLVED: " + owner_name +
                " has no materialized world object target"
            )
            continue
        relevant = [b for b in builders if b.name != owner_name]
        if not relevant:
            continue  # Standalone vehicles do not require a separate builder.
        # A launch actor must be the actual builder-owned root, not ANY
        # world object incidentally shared with the builder (e.g. a shop
        # terminal or a resource deposit). Prefer a host-verified explicit
        # actor identity; otherwise require structural root evidence.
        actor = spec.get("actor_world_name")
        if actor is not None:
            if not isinstance(actor, str) or actor not in consumer_refs:
                errors.append(
                    "VEHICLE_ACTOR_IDENTITY_INVALID: " + owner_name +
                    " names an actor not linked to its server world targets"
                )
                continue
            declared_class = next((obj.get("class") for obj in
                design.get("world_objects", ()) if isinstance(obj, dict)
                and obj.get("name") == actor), None)
            if (spec.get("actor_world_class") is not None and
                    spec["actor_world_class"] != declared_class):
                errors.append(
                    "VEHICLE_ACTOR_CLASS_MISMATCH: " + owner_name +
                    " resolved actor does not match materialized Instance class"
                )
                continue
            for route in (design.get("host_typed_actions") or {}).values():
                if not isinstance(route, dict) or route.get("server") != owner_name:
                    continue
                client = modules.get(route.get("client"))
                if (client is not None and actor not in
                        (ownership.get(client.module_id) or ())):
                    errors.append(
                        "VEHICLE_ACTOR_CLIENT_NOT_BOUND: " + owner_name +
                        " launch UI and server do not reference the same "
                        "materialized vehicle root"
                    )
        # A physical Part shared by builder and launcher is only an identity
        # link, NOT proof of an assembled driveable Model. If the approved
        # launch must keep passengers aboard, the host must own a builder
        # that exposes GetOwnedActor(player) and constructs the vehicle/seat.
        # Otherwise the tiny coder spends minutes trying to move a dummy
        # Part while inventing missing services and a destination.
        if (spec.get("actor_identity_source") ==
                    "unique_host_materialized_builder_root"
                and re.search(r"occupant|aboard|passenger|crew",
                              str(spec.get("occupant_rule") or ""), re.I)):
            from .host_vehicle_actor_capability import eligible_vehicle_actor_builder
            from .spec import ModuleKind
            source_builder = next(
                (b for b in relevant
                 if b.module_id == spec.get("builder_module_id")), None
            )
            if (source_builder is None
                    or getattr(source_builder, "kind", None) != ModuleKind.SERVER_MODULE
                    or eligible_vehicle_actor_builder(source_builder, proposal) is None):
                errors.append(
                    "VEHICLE_PASSENGER_MODEL_UNPROVEN: " + owner_name +
                    " requires the actual assembled, passenger-carrying Model "
                    "from a verified builder GetOwnedActor(player). Linking "
                    "a scene Part named " + str(actor) +
                    " is not a valid movable ship. Re-author the builder "
                    "and launcher world/Remote contracts before Luau coding."
                )
                continue
        physical_root = re.compile(
            r"(?:ship|spacecraft|craft|vehicle|vessel|rocket|shuttle|"
            r"car|train|aircraft|boat|plane|raft).{0,55}"
            r"(?:root|chassis|frame|hull|body)|"
            r"(?:root|chassis|frame|hull|body).{0,55}"
            r"(?:ship|spacecraft|craft|vehicle|vessel|rocket|shuttle|"
            r"car|train|aircraft|boat|plane|raft)", re.I
        )
        shared = [
            (b.name, sorted(name for name in consumer_refs &
                            (set(ownership.get(b.module_id) or ()) & declared)
                            if (name == actor if actor is not None
                                else physical_root.search(name))))
            for b in relevant
        ]
        if all(not refs for _, refs in shared):
            errors.append(
                "VEHICLE_ACTOR_NOT_BUILT_OBJECT: " + owner_name +
                " moves materialized object(s) " +
                ", ".join(sorted(consumer_refs)) +
                ", but the authored vehicle builder(s) " +
                ", ".join(sorted(b.name for b in relevant)) +
                " own disjoint objects. Bind the SAME verified craft root "
                "before coding; a separate dummy Part is not the assembled vehicle."
            )
    return errors
