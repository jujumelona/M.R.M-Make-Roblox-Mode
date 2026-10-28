"""Model-action authority provenance preflight (before paying for Luau).

An input Remote and a generically named PlayerDataManager table do not
constitute a gameplay ownership, price, world target or reward producer.
Only the active plan's EXPLICIT effect/state contracts can authorize a
standalone 9B-generated mutation. This is deliberately independent of the
game's theme, action name, and previous failure ZIP names.
"""
from __future__ import annotations

import re
from typing import Any

# A source-described dependency on a *previously existing* owned resource,
# catalog, persisted state or authenticated transaction is a higher-risk
# consumer than a stateless event. The words only SELECT which plans require
# structured proof; prose itself never authorizes the missing provider.
_PREEXISTING_AUTHORITY = re.compile(
    r"\b(?:already\s+owned|preexisting|pre-existing|server[- ]owned|"
    r"owner(?:ship)?|owned\s+(?:balance|currency|item|record|ship|"
    r"spaceship|planet|weapon|part|section)|"
    r"(?:price|cost|balance|inventory|catalog|entitlement|"
    r"purchase\s+record|saved\s+state|persistent\s+state))\b",
    re.I,
)


def _provenance_for_action(spec: dict[str, Any], design: dict[str, Any],
                           remote: str) -> bool:
    """Only a non-transport effect contract with a real declared write can
    clear this *architectural* gate. Runtime proof is a separate stage."""
    contract = spec.get("contract") or {}
    if spec.get("transport_only") is True:
        return False
    changes = contract.get("state_changes")
    if not isinstance(changes, list) or not changes:
        return False
    return bool(
        (design.get("host_executable_actions") or {}).get(remote)
        or (design.get("host_effect_programs") or {}).get(remote)
        or contract.get("target", {}).get("kind") == "world_entity"
    )


def unproven_model_actions(
    proposal: Any, scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Inspect the actual routed model work; host-compiled actions exempt.

    If a model action needs a pre-existing authoritative state, its plan
    cannot be a transport-only selection/quantity envelope. This rejects
    the missing-producer class of log 32 BEFORE writing 24 other modules.
    """
    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design") or {}
    if not design:
        return []
    modules = {m.name: m for m in getattr(proposal, "modules", [])}
    actions = design.get("host_actions") or {}
    typed = design.get("host_typed_actions") or {}
    unresolved: list[dict[str, Any]] = []
    # The model-action authority invariant is not coupled to a single
    # transient source routing label. Before source normalization a typed
    # action may be classified as bounded_server_action or legacy coding,
    # then later become bounded_typed_server_action after a host module
    # conversion. In log34 the planner accepted that preview and production
    # rejected it 90ms later. Any model-owned SERVER implementation with
    # a prior-state obligation requires proof regardless of route label.
    from .spec import ModuleKind
    for row in scope.get("modules", []):
        strategy = str(row.get("strategy") or "")
        if (strategy == "builtin_source" or strategy.startswith("host_")
                or strategy not in {
                    "bounded_typed_server_action", "bounded_server_action",
                    "bounded_passive_start", "whole_file_model_legacy",
                    "invalid_typed_server_action",
                }):
            continue
        name = row.get("name")
        module = modules.get(name)
        if module is None or module.kind != ModuleKind.SERVER_MODULE:
            continue
        description = str(getattr(module, "description", "") or "")
        if not _PREEXISTING_AUTHORITY.search(description):
            continue
        routes = [(key, value) for key, value in actions.items()
                  if isinstance(value, dict) and value.get("service") == name]
        if len(routes) != 1:
            unresolved.append({
                "module": name, "reason": "UNIQUE_AUTHORITY_ROUTE_NOT_FOUND",
                "remote_count": len(routes),
            })
            continue
        remote = routes[0][0]
        spec = typed.get(remote)
        if (isinstance(spec, dict)
                and _provenance_for_action(spec, design, remote)):
            continue
        contract = (spec.get("contract") or {}) if isinstance(spec, dict) else {}
        bound_world = ((design.get("module_world_objects") or {}).get(
            getattr(module, "module_id", ""), []))
        unresolved.append({
            "module": name,
            "remote": remote,
            "reason": "AUTHORITY_PRODUCER_NOT_DECLARED",
            "typed_transport_only": (spec or {}).get("transport_only")
                if isinstance(spec, dict) else None,
            "declared_state_changes": len(contract.get("state_changes") or []),
            "declared_target_kind": (contract.get("target") or {}).get("kind"),
            "declared_physical_objects": bound_world,
            "required_repair": (
                "Replan this action with an independently source-authorized "
                "state producer, owned target / catalog and exact server "
                "effect schema. Do not use unrelated world Parts as the "
                "missing entity; do not invent ownership in the coder body."
            ),
        })
    return unresolved
