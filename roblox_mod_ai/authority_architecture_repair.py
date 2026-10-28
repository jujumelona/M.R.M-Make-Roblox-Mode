"""Bounded feedback repair of authority-incomplete game architectures.

The small model may redesign SOURCE-OWNED semantics. The host exclusively
decides whether a corrected design contains real source-authorized effects.
No error is converted to a fake state change, world target or success receipt.
"""
from __future__ import annotations

from typing import Any, Callable
from copy import deepcopy

from .spec import RobloxProposal


class AuthorityArchitectureExhausted(ValueError):
    pass


def inspect_authority_design(
    design: dict[str, Any], existing_modules: list[Any], *,
    requested_prompt: str,
) -> list[dict[str, Any]]:
    """Reproduce the actual production source transforms before classification.

    The old shallow preview omitted persistence normalization, dynamic server
    ModuleScript conversion, physical mining prerequisite materialization and
    vehicle ownership binding. Those operations can change which compiler
    owns a service. Its 'no blockers' verdict therefore disagreed with the
    production resolver in 34th execution. Check a DEEP CLONE so preview
    cannot poison the authored plan or subsequent repair checkpoints.
    """
    from .economy_core import normalize_economy_ledger
    from .server_modules import normalize_dynamic_server_modules
    from .host_mining_contract import ensure_mining_world_contract
    from .vehicle_identity_binding import (
        bind_verified_vehicle_providers, bind_vehicle_actors,
        materialize_source_linked_space_arrivals,
    )
    from .generation_scope import generation_scope
    from .host_protocol_handoff import rebase_complete_host_protocols
    from .model_action_authority import unproven_model_actions

    preview = RobloxProposal(
        requested_prompt=requested_prompt,
        game_title="AuthorityPreflight",
        description="Unbuilt source-level authority verification",
        game_design={"dynamic_design": deepcopy(design),
                     "storage_backend": "builtin",
                     "project_mode": "new_experience"},
        modules=deepcopy([*existing_modules, *design["modules"]]),
    )
    # These are the same source-level steps as execute() and resolve().
    normalize_economy_ledger(preview)
    normalize_dynamic_server_modules(preview)
    ensure_mining_world_contract(preview)
    bind_verified_vehicle_providers(preview)
    bind_vehicle_actors(preview)
    materialize_source_linked_space_arrivals(preview)
    before = generation_scope(preview, for_protocol_handoff=True)
    rebase_complete_host_protocols(preview, before)
    scope = generation_scope(preview)
    return unproven_model_actions(preview, scope)


def replan_unproven_authority(
    design: dict[str, Any],
    *,
    existing_modules: list[Any],
    requested_prompt: str,
    research: dict[str, Any],
    redesign: Callable[[], dict[str, Any]],
    max_repairs: int = 2,
    allow_codegen_deferral: bool = False,
    inspect: Callable[[dict[str, Any], list[Any], str],
                      list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Replan with bounded, actionable dependency feedback, never fake proof.

    All changed plan instances go through fresh source validation in the
    normal architect. No request text, original source IDs or client payload
    schemas are reinterpreted by this host loop.
    """
    if max_repairs < 0 or max_repairs > 4:
        raise ValueError("Invalid authority retry budget")
    inspections = research.setdefault("authority_replan_attempts", [])
    check = inspect or (lambda design, existing, prompt:
                        inspect_authority_design(
                            design, existing, requested_prompt=prompt))
    try:
        for attempt in range(max_repairs + 1):
            all_missing = check(design, existing_modules, requested_prompt)
            missing = all_missing
            deferred: list[dict[str, Any]] = []
            if allow_codegen_deferral:
                from .model_action_authority import partition_codegen_authority
                missing, deferred = partition_codegen_authority(all_missing)
            inspections.append({
                "round": attempt + 1,
                "passed": not all_missing,
                "unproven": all_missing,
                "deferred_until_codegen": [x["module"] for x in deferred],
                "verified_as": "plan_source_contract_not_studio_execution",
            })
            if not missing:
                if deferred:
                    # Each source-owned typed input remains a strictly
                    # unverified IMPLEMENTATION obligation. Actual emitted
                    # Luau must pass the mandatory post-codegen effect gate.
                    design = dict(design, deferred_model_authority=[{
                        "module": x["module"], "remote": x["remote"],
                        "required_repair": x.get("required_repair"),
                        "verified": False, "verification_stage": "codegen",
                    } for x in deferred])
                return design
            if attempt >= max_repairs:
                raise AuthorityArchitectureExhausted(
                    "UNPROVEN_MODEL_ACTION_AUTHORITY after " +
                    str(max_repairs) + " bounded replans: " +
                    "; ".join(str(gap.get("module")) + ":" +
                              str(gap.get("reason")) for gap in missing)
                )
            modules = {m.name: m for m in design["modules"]}
            facet_ids = design.get("module_facets") or {}
            corrections = []
            for gap in missing:
                name = gap.get("module")
                module = modules.get(name)
                if module is None:
                    continue
                corrections.append({
                    "source_module": name,
                    "source_facet_ids": list(facet_ids.get(module.module_id, [])),
                    "original_server_behavior": str(module.description or "")[:900],
                    "error": gap.get("reason"),
                    "missing_contract": gap.get("required_repair"),
                    "observed": {
                        "transport_only": gap.get("typed_transport_only"),
                        "state_changes": gap.get("declared_state_changes"),
                        "target_kind": gap.get("declared_target_kind"),
                        "world_parts": gap.get("declared_physical_objects"),
                    },
                })
            # Feedback changes only the small model's next design task.
            # Never append it to the user's source request or permission set.
            research["_authority_feedback"] = corrections
            design = redesign()
    finally:
        # Replan feedback is transient. It must never contaminate a normal
        # subsequent request, source ledger or published acceptance claim.
        research.pop("_authority_feedback", None)
    raise AssertionError("unreachable")
