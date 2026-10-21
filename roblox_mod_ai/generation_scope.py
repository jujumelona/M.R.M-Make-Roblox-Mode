"""Truthful, source-derived generation work assignment before model inference.

A passing mock CI cannot certify end-to-end success. This report shows
exactly which modules will use first-party host implementations, bounded
model bodies, or unsupported whole-file model coding. It persists into the
failure receipt so the NEXT likely bottlenecks are visible before expensive
GGUF tokens are spent. Never present it as a success probability.
"""
from __future__ import annotations

from typing import Any

from .host_gameplay import render_host_gameplay
from .host_catalog_purchase import eligible_catalog_purchase
from .host_ship_sections import eligible_ship_sections
from .host_ship_attachment import eligible_ship_attachment
from .host_capped_ship_parts import eligible_capped_ship_parts
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
        elif eligible_ship_sections(module, proposal) is not None:
            strategy = "host_declarative_ship_sections"
        elif eligible_ship_attachment(module, proposal) is not None:
            strategy = "host_declarative_ship_attachment"
        elif eligible_capped_ship_parts(module, proposal) is not None:
            strategy = "host_declarative_capped_ship_parts"
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
        "notes": (
            "Bounded-body and declarative routes still require real game-rule "
            "validation. A legacy whole-file model route is not automatically "
            "invalid, but is an unmitigated source of long-output failures."
        ),
    }
