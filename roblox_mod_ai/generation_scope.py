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

from .host_level_upgrade import eligible_rank_protocol
from .host_ordered_assembly import eligible_ordered_assembly
from .host_vehicle_departure import eligible_departure
from .host_gameplay import render_host_gameplay
from .host_space_actions import render_host_space_action
from .host_space_colonization import render_colony_alias
from .typed_action_contract import render_typed_client
from .host_mode_navigation import eligible_mode_navigation
from .host_mode_unlock import eligible_mode_unlock
from .host_catalog_purchase import eligible_catalog_purchase
from .host_trade_catalog import eligible_trade_catalog
from .host_upgrade_declarative import eligible_declarative_upgrade
from .host_ship_sections import eligible_ship_sections
from .host_resource_ship_builder import eligible_resource_ship_builder
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
from .host_ship_purchase_facade import eligible_ship_purchase_facade
from .host_peer_currency_exchange import eligible_peer_currency_exchange
from .scaffold_policy import (
    single_host_action, single_client_action, single_passive_service,
)


def generation_scope(
    proposal: Any, *, for_protocol_handoff: bool = False,
) -> dict[str, Any]:
    """Classify source ownership at either side of the atomic host handoff.

    Pre-handoff discovers COMPLETE first-party server+client implementations
    even when a transport-only typed contract is temporarily attached.
    The final scope reflects code_generator's actual typed-first precedence.
    Never use the provisional scope for checkpoint provenance.
    """
    design = proposal.game_design.get("dynamic_design") or {}
    strategies = []
    for module in proposal.modules:
        if not module.module_id.startswith("dyn_"):
            strategy = "builtin_source"
        elif render_colony_alias(module, proposal) is not None:
            strategy = "host_space_colony_alias"
        elif render_host_space_action(module, proposal) is not None:
            strategy = "host_space_action"
        # Routing precedence MUST match code_generator.generate_module_code:
        # typed client and typed server are resolved before genre adapters.
        # A different strategy here invalidates checkpoint provenance and
        # misreports whether a small-model body will actually be generated.
        elif (not for_protocol_handoff
              and render_typed_client(module, proposal) is not None):
            strategy = "host_typed_client_ui"
        elif (not for_protocol_handoff
              and module.kind == ModuleKind.SERVER_MODULE
              and module.module_id.startswith("dyn_")
              and any(
                  remote in (design.get("host_typed_actions") or {})
                  for remote in (design.get("module_remotes") or {}).get(
                      module.module_id, []))):
            linked = [
                remote for remote in
                (design.get("module_remotes") or {}).get(module.module_id, [])
                if remote in (design.get("host_typed_actions") or {})
            ]
            strategy = ("bounded_typed_server_action"
                        if len(linked) == 1 and single_host_action(proposal, module)
                        else "invalid_typed_server_action")
        elif render_host_gameplay(module, proposal) is not None:
            strategy = "host_verified_template"
        elif eligible_departure(module, proposal) is not None:
            strategy = "host_declarative_vehicle_departure"
        elif eligible_ordered_assembly(module, proposal) is not None:
            strategy = "host_declarative_ordered_assembly"
        elif eligible_rank_protocol(module, proposal) is not None:
            strategy = "host_declarative_rank_upgrade"
        elif eligible_mode_navigation(module, proposal) is not None:
            strategy = "host_declarative_mode_navigation"
        elif eligible_mode_unlock(module, proposal) is not None:
            strategy = "host_declarative_mode_unlock"
        elif eligible_ship_purchase_facade(module, proposal) is not None:
            strategy = "host_ship_purchase_facade"
        elif eligible_catalog_purchase(module, proposal) is not None:
            strategy = "host_declarative_catalog"
        elif eligible_trade_catalog(module, proposal) is not None:
            strategy = "host_declarative_trade_catalog"
        elif eligible_declarative_upgrade(module, proposal) is not None:
            strategy = "host_declarative_general_upgrades"
        elif eligible_ship_slot_configuration(module, proposal) is not None:
            strategy = "host_declarative_ship_slot_configuration"
        elif eligible_ship_slot_levels(module, proposal) is not None:
            strategy = "host_declarative_ship_slot_levels"
        elif eligible_ship_launch_gate(module, proposal) is not None:
            strategy = "host_declarative_ship_launch_gate"
        elif eligible_resource_ship_builder(module, proposal) is not None:
            strategy = "host_declarative_resource_ship_builder"
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
    # A source-owned navigation UI is not proof that an unrelated launch
    # module writes the EXACT saved mode/flight ABI it consumes. A scripted
    # mode UI can compile yet remain locked forever if launch does not set
    # RMMTravelProgress.inSpace and RMMGameMode.activeMode.
    for module in proposal.modules:
        if module.kind != ModuleKind.SERVER_MODULE:
            continue
        if eligible_mode_navigation(module, proposal) is None:
            continue
        verified_launch = any(
            peer.kind == ModuleKind.SERVER_MODULE
            and peer.name != module.name
            and eligible_ship_launch_gate(peer, proposal) is not None
            for peer in proposal.modules
        )
        if not verified_launch:
            unverified_dependencies.append({
                "consumer": module.name,
                "required": "launch producer for RMMTravelProgress.inSpace and RMMGameMode.activeMode",
                "status": "unverified_launch_state_producer",
                "reason": (
                    "Mode navigation can only select a planet after an actual "
                    "server launch marks the player in space. A model-authored "
                    "launch module has not been verified to populate those "
                    "shared state namespaces. Planet/mineral/colony integration "
                    "also requires a matching host-defined planet registry."
                ),
            })
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

    # A purchased part/license is not an installed ship section. The generic
    # trade catalog records an entitlement in RMMTradeEntitlements; a separate
    # physical builder must consume the SAME verified ID before it can be
    # presented as an assembled part. Never label codegen success as game
    # integration without that consumer, regardless of the module names.
    from .host_trade_catalog import _required_categories
    for module in proposal.modules:
        if (module.kind == ModuleKind.SERVER_MODULE
                and eligible_trade_catalog(module, proposal) is not None
                and "section" in _required_categories(module.description)):
            unverified_dependencies.append({
                "consumer": module.name,
                "required": "physical ship builder that consumes purchased "
                            "RMMTradeEntitlements section license IDs",
                "status": "unverified_ship_section_license_consumer",
                "reason": (
                    "Catalog purchases record persistent owned section licenses, "
                    "not physical ship parts. A separate verified builder must "
                    "consume this license and update the ship assembly/geometry. "
                    "No generic model-authored builder may be assumed to do so."
                ),
            })

    # One live-server call can settle both wallets without yielding, but
    # separate player profile DataStore writes cannot commit atomically.
    # Never describe a source-only host adapter as verified durable trading.
    for module in proposal.modules:
        if (module.kind == ModuleKind.SERVER_MODULE
                and eligible_peer_currency_exchange(module, proposal) is not None):
            unverified_dependencies.append({
                "consumer": module.name,
                "required": "atomic cross-player persistent settlement and crash recovery",
                "status": "unverified_cross_player_persistence",
                "reason": (
                    "Host trade verifies both consented balances and mutates both in one "
                    "non-yielding server session. PlayerDataManager persists each user "
                    "separately. A crash between saves can create an inconsistent "
                    "cross-player balance, so global atomic durability is NOT verified."
                ),
            })

    # Mode unlock cannot prove real flight, ship section and paid upgrade ABIs.
    # Only the actual launcher may produce RMMTravelProgress.inSpace.
    for module in proposal.modules:
        if (module.kind == ModuleKind.SERVER_MODULE
                and eligible_mode_unlock(module, proposal) is not None):
            verified_flight = any(
                other is not module and other.kind == ModuleKind.SERVER_MODULE
                and eligible_ship_launch_gate(other, proposal) is not None
                for other in proposal.modules)
            if not verified_flight:
                unverified_dependencies.append({
                    "consumer": module.name,
                    "required": "server launch producer of RMMTravelProgress.inSpace",
                    "status": "unverified_mode_launch_producer",
                    "reason": (
                        "The host gate will reject entering Space Mode until a "
                        "separate verified launch service records inSpace=true. "
                        "An authored launch description does not prove the "
                        "saved flight ABI or spatial movement."
                    ),
                })
            unverified_dependencies.append({
                "consumer": module.name,
                "required": "RMMShipSections.sections and RMMUpgradePurchases purchase records",
                "status": "unverified_mode_ship_upgrade_producers",
                "reason": (
                    "An upstream module description is not evidence that generated "
                    "ship and upgrade services populate these exact saved namespaces. "
                    "The host gate cannot fabricate a ship or purchased upgrades."
                ),
            })

    legacy = [row["name"] for row in strategies
              if row["strategy"] == "whole_file_model_legacy"]
    # A host-owned shell is not a deterministic gameplay implementation.
    # Historical logs had zero whole-file risks yet 4-8 free-form model
    # server bodies; reporting only legacy routes hid the dominant failure
    # probability from operators before wasting expensive model calls.
    model_action_risks = [
        row["name"] for row in strategies
        if row["strategy"] in (
            "bounded_server_action", "bounded_typed_server_action",
            "invalid_typed_server_action", "bounded_passive_start",
            "whole_file_model_legacy",
        )
    ]
    count = {}
    for row in strategies:
        count[row["strategy"]] = count.get(row["strategy"], 0) + 1
    return {
        "schema": "rmm/generation-scope-v1",
        "scope": "source_routing_only_not_success_or_gameplay_evidence",
        "modules": strategies,
        "counts": count,
        "whole_file_model_risk_modules": legacy,
        "model_action_risk_modules": model_action_risks,
        "model_action_risk_count": len(model_action_risks),
        "unverified_cross_module_dependencies": unverified_dependencies,
        "notes": (
            "Bounded-body and declarative routes still require real game-rule "
            "validation. A legacy whole-file model route is not automatically "
            "invalid, but is an unmitigated source of long-output failures."
        ),
    }
