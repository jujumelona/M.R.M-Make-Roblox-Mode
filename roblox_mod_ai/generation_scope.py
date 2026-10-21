"""Truthful, source-derived generation work assignment before model inference.

A passing mock CI cannot certify end-to-end success. This report shows
exactly which modules will use first-party host implementations, bounded
model bodies, or unsupported whole-file model coding. It persists into the
failure receipt so the NEXT likely bottlenecks are visible before expensive
GGUF tokens are spent. Never present it as a success probability.
"""
from __future__ import annotations

from typing import Any

from .spec import ModuleKind

from .host_gameplay import render_host_gameplay
from .host_catalog_purchase import eligible_catalog_purchase
from .host_upgrade_declarative import eligible_declarative_upgrade
from .host_ship_sections import eligible_ship_sections
from .host_ship_slot_configuration import eligible_ship_slot_configuration
from .host_ship_slot_levels import eligible_ship_slot_levels
from .host_ship_launch_gate import eligible_ship_launch_gate
from .host_ship_hierarchy import eligible_ship_hierarchy
from .host_ship_reconfiguration import eligible_ship_reconfiguration
from .host_ship_attachment import eligible_ship_attachment
from .host_capped_ship_parts import eligible_capped_ship_parts
from .host_ship_owned_upgrades import eligible_ship_owned_upgrades
from .host_performance_mode import eligible_performance_mode
from .host_ship_part_catalog import eligible_ship_part_catalog
from .scaffold_policy import (
    single_host_action, single_client_action, single_passive_service,
)


def generation_scope(proposal: Any) -> dict[str, Any]:
    design = proposal.game_design.get("dynamic_design") or {}
    strategies = []
    for module in proposal.modules:
        if not module.module_id.startswith("dyn_"):
            strategy = "builtin_source"
        elif render_host_gameplay(module, proposal) is not None:
            strategy = "host_verified_template"
        elif eligible_catalog_purchase(module, proposal) is not None:
            strategy = "host_declarative_catalog"
        elif eligible_declarative_upgrade(module, proposal) is not None:
            strategy = "host_declarative_general_upgrades"
        elif eligible_ship_slot_configuration(module, proposal) is not None:
            strategy = "host_declarative_ship_slot_configuration"
        elif eligible_ship_slot_levels(module, proposal) is not None:
            strategy = "host_declarative_ship_slot_levels"
        elif eligible_ship_launch_gate(module, proposal) is not None:
            strategy = "host_declarative_ship_launch_gate"
        elif eligible_ship_sections(module, proposal) is not None:
            strategy = "host_declarative_ship_sections"
        elif eligible_ship_hierarchy(module, proposal) is not None:
            strategy = "host_declarative_ship_hierarchy"
        elif eligible_ship_reconfiguration(module, proposal) is not None:
            strategy = "host_declarative_ship_reconfiguration"
        elif eligible_ship_attachment(module, proposal) is not None:
            strategy = "host_declarative_ship_attachment"
        elif eligible_capped_ship_parts(module, proposal) is not None:
            strategy = "host_declarative_capped_ship_parts"
        elif eligible_ship_owned_upgrades(module, proposal) is not None:
            strategy = "host_declarative_ship_upgrades"
        elif eligible_ship_part_catalog(module, proposal) is not None:
            strategy = "host_declarative_ship_part_catalog"
        elif module.name in design.get("host_client_actions", {}):
            strategy = "host_zero_argument_ui"
        elif single_client_action(proposal, module):
            remote = (design.get("module_remotes") or {}).get(module.module_id, [None])[0]
            strategy = ("host_declarative_options"
                        if remote in (design.get("host_action_choices") or {})
                        else "bounded_client_ui")
        elif single_host_action(proposal, module):
            strategy = "bounded_server_action"
        elif single_passive_service(proposal, module):
            strategy = "bounded_passive_start"
        else:
            strategy = "whole_file_model_legacy"
        strategies.append({
            "module_id": module.module_id,
            "name": module.name,
            "path": module.file_path,
            "strategy": strategy,
        })
    # A codegen route can be structurally valid while a required cross-service
    # runtime value still has no verified producer. Report that dependency
    # instead of treating a passing source-only check as a functional game.
    unverified_dependencies = []
    for module in proposal.modules:
        if module.kind != ModuleKind.SERVER_MODULE:
            continue
        selected = eligible_performance_mode(module, proposal)
        if selected is None:
            continue
        _name, _remote, minimum, _mode = selected
        # These adapters actually calculate their performance from installed
        # authoritative ship parts. An arbitrary model-authored ship service
        # cannot be assumed to implement the same ABI.
        producer = any(
            m.name != module.name
            and m.kind == module.kind
            and (eligible_ship_part_catalog(m, proposal) is not None
                 or eligible_ship_attachment(m, proposal) is not None
                 or eligible_ship_reconfiguration(m, proposal) is not None
                 or eligible_ship_hierarchy(m, proposal) is not None
                 or eligible_ship_slot_configuration(m, proposal) is not None)
            for m in proposal.modules
        )
        if not producer:
            unverified_dependencies.append({
                "consumer": module.name,
                "required": "server-owned RMMShipPerformance or owned RMMShipSections.sections[].performance",
                "threshold": minimum,
                "status": "unverified_producer_contract",
                "reason": (
                    "The proposed ship builder does not have a verified host "
                    "performance publisher. The mode will reject requests until "
                    "a real server-owned installed-part performance exists."
                ),
            })

    legacy = [row["name"] for row in strategies
              if row["strategy"] == "whole_file_model_legacy"]
    count = {}
    for row in strategies:
        count[row["strategy"]] = count.get(row["strategy"], 0) + 1
    return {
        "schema": "rmm/generation-scope-v1",
        "scope": "source_routing_only_not_success_or_gameplay_evidence",
        "modules": strategies,
        "counts": count,
        "whole_file_model_risk_modules": legacy,
        "unverified_cross_module_dependencies": unverified_dependencies,
        "notes": (
            "Bounded-body and declarative routes still require real game-rule "
            "validation. A legacy whole-file model route is not automatically "
            "invalid, but is an unmitigated source of long-output failures."
        ),
    }
