"""Hand off incomplete model UI transport to proven first-party protocol pairs.

A transport_only contract is NOT a gameplay effect and is not authoritative
over a complete first-party host renderer. Prior code_generator.py always
returned the generic typed coder *before* checking safe declarative host
renderers, so game services hallucinated world APIs despite reusable host
code existing. Only rebase an exact, verified server+client pair that exports
the entire protocol. Never take over a typed contract with real state effects.
"""
from __future__ import annotations

from typing import Any

_HOST_PROTOCOLS = frozenset({
    "host_verified_template",
    "host_declarative_mode_navigation",
    "host_declarative_mode_unlock",
    "host_declarative_catalog",
    "host_declarative_trade_catalog",
    "host_declarative_general_upgrades",
    "host_declarative_rank_upgrade",
    "host_declarative_ordered_assembly",
    "host_declarative_ship_slot_configuration",
    "host_declarative_ship_slot_levels",
    "host_declarative_ship_launch_gate",
    "host_declarative_resource_ship_builder",
    "host_declarative_ship_sections",
    "host_declarative_ship_hierarchy",
    "host_declarative_ship_reconfiguration",
    "host_declarative_ship_attachment",
    "host_declarative_capped_ship_parts",
    "host_declarative_ship_upgrades",
    "host_declarative_ship_part_catalog",
    "host_ship_purchase_facade",
})


def rebase_complete_host_protocols(proposal: Any, scope: dict[str, Any]) -> list[dict[str, str]]:
    """Clear transport-only ABI *only* for a complete host server/client pair.

    Called BEFORE the generation queue and before any module checkpoint is
    accepted. Neither the Remote's real kind nor its owner changes.
    Only the empty input-only manifest, which conflicts with the verified
    first-party client, is replaced by that client's complete host protocol.
    """
    design = (proposal.game_design or {}).get("dynamic_design") or {}
    typed = design.get("host_typed_actions")
    if not isinstance(typed, dict) or not typed:
        return []
    strategies = {
        row["name"]: row["strategy"]
        for row in scope.get("modules", [])
        if isinstance(row, dict) and isinstance(row.get("name"), str)
        and isinstance(row.get("strategy"), str)
    }
    modules = {
        m.name: m for m in getattr(proposal, "modules", [])
    }
    actions = design.get("host_actions") or {}
    module_remotes = design.get("module_remotes") or {}
    completed: list[dict[str, str]] = []
    for remote, spec in list(typed.items()):
        if not isinstance(spec, dict) or spec.get("transport_only") is not True:
            continue
        contract = spec.get("contract")
        if not isinstance(contract, dict) or contract.get("state_changes") != []:
            continue
        if contract.get("target") != {"kind": "none"}:
            continue
        owner = actions.get(remote)
        if (not isinstance(owner, dict) or owner.get("kind") != "RemoteFunction"
                or owner.get("service") != spec.get("server")
                or (design.get("remotes") or {}).get(remote) != "RemoteFunction"):
            continue
        server = modules.get(spec.get("server"))
        client = modules.get(spec.get("client"))
        if server is None or client is None:
            continue
        if (not server.file_path.startswith("src/server/")
                or not server.file_path.endswith(".luau")
                or not client.file_path.startswith("src/client/")
                or not client.file_path.endswith(".client.luau")):
            continue
        server_strategy = strategies.get(server.name)
        client_strategy = strategies.get(client.name)
        if (server_strategy not in _HOST_PROTOCOLS
                or client_strategy != server_strategy):
            continue
        if (module_remotes.get(server.module_id) != [remote]
                or module_remotes.get(client.module_id) != [remote]):
            continue
        if spec.get("server") != server.name or spec.get("client") != client.name:
            continue
        # Both sides of the Remote must be taken over atomically.
        # Retain the SOURCE-OWNED target IDs and ownership contract for
        # the host rank compiler. Deleting transport-only UI must not erase
        # the semantic inputs needed to compile a real progression effect.
        if server_strategy == "host_declarative_rank_upgrade":
            design.setdefault("host_rank_contracts", {})[remote] = dict(spec)
        if server_strategy == "host_declarative_ordered_assembly":
            design.setdefault("host_ordered_assembly_contracts", {})[remote] = dict(spec)
        typed.pop(remote)
        completed.append({
            "remote": remote,
            "server": server.name,
            "client": client.name,
            "protocol": server_strategy,
            "reason": "replaced_input_only_manifest_with_verified_host_protocol",
        })
    if completed:
        design.setdefault("host_protocol_handovers", []).extend(completed)
    return completed
