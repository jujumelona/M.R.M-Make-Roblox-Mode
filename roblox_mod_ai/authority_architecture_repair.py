"""Bounded feedback repair of authority-incomplete game architectures.

The small model may redesign SOURCE-OWNED semantics. The host exclusively
decides whether a corrected design contains real source-authorized effects.
No error is converted to a fake state change, world target or success receipt.
"""
from __future__ import annotations

from typing import Any, Callable

from .spec import RobloxProposal


class AuthorityArchitectureExhausted(ValueError):
    pass


def inspect_authority_design(
    design: dict[str, Any], existing_modules: list[Any], *,
    requested_prompt: str,
) -> list[dict[str, Any]]:
    """Use exactly the same host protocol handoff and scope as production."""
    from .generation_scope import generation_scope
    from .host_protocol_handoff import rebase_complete_host_protocols
    from .model_action_authority import unproven_model_actions

    preview = RobloxProposal(
        requested_prompt=requested_prompt,
        game_title="AuthorityPreflight",
        description="Unbuilt source-level authority verification",
        game_design={"dynamic_design": design},
        modules=[*existing_modules, *design["modules"]],
    )
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
            missing = check(design, existing_modules, requested_prompt)
            inspections.append({
                "round": attempt + 1,
                "passed": not missing,
                "unproven": missing,
                "verified_as": "plan_source_contract_not_studio_execution",
            })
            if not missing:
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
