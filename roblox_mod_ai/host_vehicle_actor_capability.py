"""Select only first-party ship builders that can expose a real Model actor.

The small model may invent a separate CraftPart for a launcher. A validated
declarative builder instead owns a real player Model and its boarding seat.
No model-authored Lua, decorative Parts or ambiguous builders qualify.
"""
from __future__ import annotations

from typing import Any


def eligible_vehicle_actor_builder(builder: Any, proposal: Any) -> str | None:
    from .spec import ModuleKind
    from .host_ordered_assembly import eligible_ordered_assembly
    from .host_ship_attachment import eligible_ship_attachment
    from .host_resource_ship_builder import eligible_resource_ship_builder

    if getattr(builder, "kind", None) != ModuleKind.SERVER_MODULE:
        return None
    if eligible_ordered_assembly(builder, proposal) is not None:
        return "ordered_assembly"
    # Both adapters render the audited attach-once Model and debit actual
    # mined resources. They become launchable ONLY after preflight registers
    # the builder, so their normal stand-alone behavior does not change.
    if eligible_ship_attachment(builder, proposal) is not None:
        return "section_attachment"
    if eligible_resource_ship_builder(builder, proposal) is not None:
        return "resource_ship_builder"
    return None


def matching_launch_provider(
    proposal: Any, builder: Any, launch_name: str,
) -> bool:
    """Require one exact host-owned RemoteFunction/typed server+client pair."""
    from .spec import ModuleKind

    d = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design") or {}
    modules = {m.name: m for m in getattr(proposal, "modules", ())}
    server = modules.get(launch_name)
    if server is None or server.kind != ModuleKind.SERVER_MODULE or builder == server:
        return False
    actions = d.get("host_actions") or {}
    remotes = d.get("remotes") or {}
    typed = d.get("host_typed_actions") or {}
    refs = d.get("module_world_objects") or {}
    links = d.get("module_remotes") or {}
    if not all(isinstance(x, dict) for x in (actions, remotes, typed, refs, links)):
        return False
    routes = [
        (remote, row) for remote, row in actions.items()
        if isinstance(row, dict) and row.get("service") == launch_name
    ]
    if len(routes) != 1:
        return False
    remote, route = routes[0]
    spec = typed.get(remote)
    if not (route.get("kind") == remotes.get(remote) == "RemoteFunction"
            and isinstance(spec, dict)
            and spec.get("transport_only") is True
            and spec.get("server") == launch_name):
        return False
    client = modules.get(spec.get("client"))
    if (client is None or client.kind != ModuleKind.CLIENT_SCRIPT
            or client.name != launch_name.removesuffix("Server") + "Client"
            or not client.file_path.endswith(".client.luau")
            or not isinstance(refs.get(server.module_id), list)
            or not isinstance(refs.get(client.module_id), list)):
        return False
    return (links.get(server.module_id) in (None, [remote])
            and links.get(client.module_id) in (None, [remote]))
