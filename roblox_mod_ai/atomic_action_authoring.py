"""Bounded, per-action semantic authoring for small local planning models.

The source-owned atomic action list is immutable. A failed observable result
is repaired locally, never by regenerating unrelated gameplay actions or
discarding already validated siblings. Does NOT certify generated Luau.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .atomic_action_quotes import (
    SourceActionBindingError, validate_atomic_system_ownership,
)
from .semantic_preservation import (
    source_intent_conflicts, source_outcome_conflicts,
)
from .request_semantics import request_semantic_errors
from .compact_atomic_authoring import (
    author_compact_atomic_system, host_verified_resource_market,
)
from .atomic_transaction_repair import (
    require_transaction_repair, author_transaction_repair,
)
from .atomic_state_mutation_repair import author_state_mutation_repair


def _field_issues(
    action: dict[str, str],
    system: dict[str, Any],
    original_prompt: str,
) -> dict[str, list[str]]:
    server = str(system.get("server_behavior") or "")
    outcome = str(system.get("observable_result") or "")
    issues: dict[str, list[str]] = {}
    if len(server.strip()) < 24:
        issues.setdefault("server_behavior", []).append(
            "server behavior is missing or too short"
        )
    if len(outcome.strip()) < 18:
        issues.setdefault("observable_result", []).append(
            "observable result is missing or too short"
        )
    for field, text, validator in (
        ("server_behavior", server, source_intent_conflicts),
        ("observable_result", outcome, source_outcome_conflicts),
    ):
        for source in (action["source_quote"], action["action"]):
            for issue in validator(source, text):
                issues.setdefault(field, []).append(issue)
    request_issues = request_semantic_errors(system, original_prompt)
    if request_issues:
        issues["request_semantics"] = request_issues
    return {field: list(dict.fromkeys(values))
            for field, values in issues.items() if values}


def author_verified_atomic_systems(
    router: Any,
    actions: list[dict[str, str]],
    *,
    source_clause: str,
    original_prompt: str,
    json_schema: dict[str, Any],
    max_attempts_per_action: int = 3,
    retained_verified: dict[tuple[str, str], dict[str, Any]] | None = None,
    authority_gaps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Author and repair just the rejected action, never successful siblings.

    A single invalid field can be rewritten with a bounded one-field schema;
    both-invalid fields trigger a fresh one-action design, not full-facet
    regeneration. The host ALWAYS reruns the actual ownership validators.
    """
    if not 1 <= max_attempts_per_action <= 3:
        raise ValueError("Invalid bounded atomic action budget")
    # Constrain the model to the one-action contract at GENERATION time, not
    # only after receiving its response. The shared facet schema permits up to
    # three systems; reusing it for one atomic action induced multi-system
    # responses and prematurely aborted otherwise valid sibling actions.
    single_action_schema = deepcopy(json_schema)
    systems_property = single_action_schema.get("properties", {}).get("systems")
    if not isinstance(systems_property, dict) or systems_property.get("type") != "array":
        raise ValueError("Atomic authoring requires a systems array schema")
    systems_property["minItems"] = 1
    systems_property["maxItems"] = 1
    accepted: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not all(isinstance(action.get(key), str)
                   for key in ("source_quote", "action")):
            raise SourceActionBindingError(
                "ATOMIC_ACTION_SOURCE_OWNER_INVALID: " + str(index)
            )
        owner = (action["source_quote"], action["action"])
        # Per-facet, ephemeral memory for a successfully checked atomic child.
        # If a later child truncates, no verified sibling is regenerated.
        if retained_verified is not None and owner in retained_verified:
            preserved = retained_verified[owner]
            validate_atomic_system_ownership(
                [action], [preserved], original_prompt=original_prompt,
            )
            accepted.append(dict(preserved))
            continue
        # The source compiler has already proved that money earned from
        # selling owned resources is the SAME transaction as trading.
        # Generate its fixed, source-derived debit+credit contract here
        # rather than allowing a 9B retry to invent a balance minting API.
        # The public ownership gate still validates both fields.
        host_market = host_verified_resource_market(
            action, original_prompt=original_prompt,
        )
        if host_market is not None:
            validate_atomic_system_ownership(
                [action], [host_market], original_prompt=original_prompt,
            )
            accepted.append(dict(host_market))
            if retained_verified is not None:
                retained_verified[owner] = dict(host_market)
            continue
        # A complete physical resource -> owned-inventory action is already
        # an immutable, source-anchored semantic contract. Log37 showed its
        # third atomic child repeatedly rewritten as the same invalid system
        # even though the original deposit + extraction + inventory effect
        # was present. Preserve only complete grounded effects and recheck
        # the same public source/outcome gates; never fabricate a Workspace
        # Part, planet, currency, inventory backend or runnable Luau.
        from .grounded_atomic_source_effects import (
            preserved_world_inventory_extraction,
        )
        grounded = preserved_world_inventory_extraction(
            action, original_prompt=original_prompt,
        )
        if grounded is not None:
            validate_atomic_system_ownership(
                [action], [grounded], original_prompt=original_prompt,
            )
            accepted.append(dict(grounded))
            if retained_verified is not None:
                retained_verified[owner] = dict(grounded)
            continue
        system: dict[str, Any] | None = None
        seen: set[str] = set()
        rejected_responses: set[str] = set()
        previous_issues: dict[str, list[str]] = {}
        # Never spend all three attempts on an identical one-field repair.
        # A failed repair is locally reformulated as a fresh compact action.
        repaired_fields: set[str] = set()
        transaction_repair_attempts = 0
        transaction_rejections: list[str] = []
        state_repair_attempted = False
        for attempt in range(max_attempts_per_action):
            # Repair the two independently failing fields in order, without
            # discarding an accepted payment just because the old visible
            # outcome was defective too. A global repair_attempted boolean
            # forced whole-action regeneration on the third attempt.
            reparable = {"server_behavior", "observable_result"}
            pending = [
                field for field in ("server_behavior", "observable_result")
                if field in previous_issues and field not in repaired_fields
            ]
            repair_field = (
                pending[0] if system is not None
                and set(previous_issues) <= reparable and pending
                else None
            )
            # 35th failure: the crew upgrade's ORIGINAL source quote
            # explicitly says purchase/trade. The first unstructured reply
            # omitted the payment, then one rejected structured repair was
            # treated as terminal and the third attempt blindly regenerated
            # the same free upgrade. Retry the TWO effect fields (debit and
            # delivered upgrade) twice, preserving the already checked
            # visible result and sibling modules throughout.
            needs_transaction = (
                system is not None
                and "server_behavior" in previous_issues
                and require_transaction_repair(previous_issues)
                and transaction_repair_attempts < 2
            )
            needs_state_repair = (
                system is not None
                and "server_behavior" in previous_issues
                and set(previous_issues) <= reparable
                and not needs_transaction
                and not state_repair_attempted
                and getattr(router, "supports_atomic_state_mutation_repair", False)
            )
            if needs_transaction:
                transaction_repair_attempts += 1
                repaired_fields.add("server_behavior")
                try:
                    transaction_server = author_transaction_repair(
                        router, action,
                        str(system.get("server_behavior") or ""),
                        prior_rejections=transaction_rejections,
                    )
                except (ValueError, TypeError) as exc:
                    rejection = type(exc).__name__ + ": " + str(exc)[:230]
                    transaction_rejections.append(rejection)
                    # Preserve the *semantic* missing-payment diagnosis so
                    # the final bounded attempt does not return to a generic
                    # stat-only body. A failed typed reply supplies no
                    # authority evidence and is never accepted.
                    previous_issues = dict(previous_issues)
                    previous_issues["server_behavior"] = list(dict.fromkeys(
                        previous_issues["server_behavior"] + [
                            "ATOMIC_TYPED_TRANSACTION_REJECTED: " + rejection
                        ]
                    ))
                    continue
                system = dict(system, server_behavior=transaction_server)
            elif needs_state_repair:
                # A single big free-form correction often drops the actual
                # state write while repeating checks. Author three short,
                # independent source-owned operands, then reapply the SAME
                # semantic and request validators. No genre-specific effect
                # is supplied by the host.
                state_repair_attempted = True
                try:
                    state_server = author_state_mutation_repair(
                        router, action, str(system.get("server_behavior") or ""),
                        original_prompt=original_prompt,
                        diagnostics=previous_issues["server_behavior"],
                    )
                except (ValueError, TypeError) as exc:
                    previous_issues = dict(previous_issues)
                    previous_issues["server_behavior"] = list(dict.fromkeys(
                        previous_issues["server_behavior"] + [
                            "ATOMIC_STRUCTURED_STATE_REPAIR_REJECTED: "
                            + type(exc).__name__ + ": " + str(exc)[:210]
                        ]
                    ))
                    continue
                repaired_fields.add("server_behavior")
                system = dict(system, server_behavior=state_server)
            elif repair_field:
                repaired_fields.add(repair_field)
                previous_text = str(system.get(repair_field) or "")
                # 1,200 characters in a 360-token completion was an invalid
                # output contract. Restrict repair to the same compact budget
                # as original atomic field generation.
                cap = 450 if repair_field == "server_behavior" else 300
                try:
                    response = router.complete_json(
                        "Rewrite just ONE defective field of ONE source-owned "
                        "action. Keep all other fields intact. Output one short "
                        "JSON string property named " + repair_field + ". "
                        "For server_behavior, include the REAL server mutation, "
                        "its owner and invalid-input rejection. For "
                        "observable_result, show the actual changed state. "
                        "No new actions, no menus, no paraphrased errors. "
                        "Maximum " + str(cap) + " characters. JSON only.\n" +
                        json.dumps({
                            "original_source_quote": action["source_quote"],
                            "source_owned_action": action["action"],
                            "other_fields": {
                                key: value for key, value in system.items()
                                if key != repair_field
                            },
                            "rejected_field": previous_text[:500],
                            "validator_errors": previous_issues[repair_field],
                            "authority_replan_observations": (
                                authority_gaps or [])[:6],
                        }, ensure_ascii=False),
                        role="planner", temperature=0.0,
                        max_tokens=(280 if repair_field == "server_behavior" else 190),
                        json_schema={
                            "type": "object",
                            "properties": {repair_field: {
                                "type": "string", "minLength": 24 if repair_field ==
                                "server_behavior" else 18, "maxLength": cap,
                            }},
                            "required": [repair_field],
                            "additionalProperties": False,
                        },
                    )
                except (ValueError, TypeError) as exc:
                    response = None
                    repair_error = type(exc).__name__ + ": " + str(exc)[:140]
                else:
                    repair_error = ""
                patched = (
                    response.get(repair_field)
                    if isinstance(response, dict) else None
                )
                if (not isinstance(patched, str)
                        or not (24 if repair_field == "server_behavior"
                                else 18) <= len(patched.strip()) <= cap
                        or patched.strip() == previous_text.strip()):
                    # This is a rejected MODEL reply, not an error in the
                    # source contract. Previously we raised immediately here,
                    # aborting all sibling actions and the entire feature.
                    previous_issues = {
                        "format": [
                            "Invalid or repeated " + repair_field + " patch; "
                            "regenerate this source-owned action only. " +
                            repair_error
                        ],
                    }
                    system = None
                    continue
                system = dict(system, **{repair_field: patched.strip()})
            else:
                if getattr(router, "supports_host_standard_transport", False):
                    try:
                        system = author_compact_atomic_system(
                            router, action, previous_issues=previous_issues,
                            authority_gaps=authority_gaps,
                            original_prompt=original_prompt,
                        )
                    except (ValueError, TypeError) as exc:
                        # Never retry the WHOLE feature because one compact
                        # per-action JSON field reached the GGUF length cap.
                        previous_issues = {
                            "format": [type(exc).__name__ + ": " + str(exc)[:210]],
                        }
                        continue
                else:
                    response = router.complete_json(
                        "Describe ONLY ONE source-owned gameplay action. Return "
                        "JSON {systems:[{name,server_behavior,client_behavior,"
                        "observable_result,interaction,input_mode,world_entities}]}. "
                        "Exactly one system. Implement the real requested server "
                        "state transition and a distinct visible state change. "
                        "A menu, mode unlock, prerequisite or animation is NOT an "
                        "implemented world action. Never replace harvesting, "
                        "combat, or settlement ownership with toggles. "
                        "Keep world_entities an array of NAMES only; host owns "
                        "input transport, construction and routing. JSON only.\n" +
                        json.dumps({
                            "source_clause": source_clause,
                            "this_action": action,
                            "previous_rejection": previous_issues,
                            "last_invalid_system": system,
                            "authority_replan_observations": (
                                authority_gaps or [])[:6],
                        }, ensure_ascii=False),
                        role="planner", temperature=0.0,
                        max_tokens=600, json_schema=single_action_schema,
                    )
                    systems = response.get("systems") if isinstance(response, dict) else None
                    if (not isinstance(systems, list) or len(systems) != 1
                            or not isinstance(systems[0], dict)):
                        # A malformed atomic JSON envelope is a *local format*
                        # failure. Keep the other verified actions untouched and
                        # re-prompt only this action within its bounded budget.
                        # Never accept the first child of a multi-system response.
                        response_hash = json.dumps(
                            response, sort_keys=True, ensure_ascii=False,
                            default=str,
                        )
                        if response_hash in rejected_responses:
                            raise SourceActionBindingError(
                                "ATOMIC_LOCAL_REPAIR_NO_PROGRESS: " + str(index) +
                                ": repeated non-atomic model response"
                            )
                        rejected_responses.add(response_hash)
                        previous_issues = {
                            "format": ["Return exactly one system in the systems array; "
                                       "do not return an actions list or several systems."]
                        }
                        continue
                    system = dict(systems[0])
            signature = json.dumps(system, sort_keys=True, ensure_ascii=False)
            if signature in seen:
                # Same structured response after a targeted fix is a local
                # model non-progress event, not evidence that unrelated
                # already-verified sibling gameplay should be discarded.
                # Attach the actual rejected field diagnostics to the report.
                repeated_issues = _field_issues(
                    action, system, original_prompt,
                )
                raise SourceActionBindingError(
                    "ATOMIC_LOCAL_REPAIR_NO_PROGRESS: " + str(index) +
                    ": " + json.dumps({
                        "source_quote": action["source_quote"][:120],
                        "source_action": action["action"][:250],
                        "repeated_field_issues": repeated_issues,
                        "last_server_behavior": str(
                            system.get("server_behavior") or "")[:280],
                        "last_observable_result": str(
                            system.get("observable_result") or "")[:180],
                    }, ensure_ascii=False)[:1200]
                )
            seen.add(signature)
            previous_issues = _field_issues(action, system, original_prompt)
            if not previous_issues:
                # Recheck the same public bundle validator for compatibility.
                validate_atomic_system_ownership(
                    [action], [system], original_prompt=original_prompt
                )
                accepted.append(system)
                if retained_verified is not None:
                    retained_verified[owner] = dict(system)
                break
        else:
            # The outer architect can fail before assigning its draft, so the
            # failure ZIP previously contained NO authored model response.
            # Report the failing immutable source owner and last server claim
            # alongside the validator diagnosis. Never mislabel an exhausted
            # child as a successful facet or discard accepted siblings.
            diagnostics = {
                "source_quote": action["source_quote"],
                "source_action": action["action"][:220],
                "issues": previous_issues,
                "last_server_behavior": (
                    str(system.get("server_behavior") or "")[:360]
                    if isinstance(system, dict) else None
                ),
                "last_observable_result": (
                    str(system.get("observable_result") or "")[:180]
                    if isinstance(system, dict) else None
                ),
            }
            raise SourceActionBindingError(
                "ATOMIC_LOCAL_REPAIR_EXHAUSTED: " + str(index) + ": " +
                json.dumps(diagnostics, ensure_ascii=False)[:1300]
            )
    validate_atomic_system_ownership(
        actions, accepted, original_prompt=original_prompt
    )
    return accepted
