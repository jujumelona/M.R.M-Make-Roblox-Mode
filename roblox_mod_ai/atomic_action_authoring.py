"""Bounded, per-action semantic authoring for small local planning models.

The source-owned atomic action list is immutable. A failed observable result
is repaired locally, never by regenerating unrelated gameplay actions or
discarding already validated siblings. Does NOT certify generated Luau.
"""
from __future__ import annotations

import json
from typing import Any

from .atomic_action_quotes import (
    SourceActionBindingError, validate_atomic_system_ownership,
)
from .semantic_preservation import (
    source_intent_conflicts, source_outcome_conflicts,
)
from .request_semantics import request_semantic_errors


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
) -> list[dict[str, Any]]:
    """Author and repair just the rejected action, never successful siblings.

    A single invalid field can be rewritten with a bounded one-field schema;
    both-invalid fields trigger a fresh one-action design, not full-facet
    regeneration. The host ALWAYS reruns the actual ownership validators.
    """
    if not 1 <= max_attempts_per_action <= 3:
        raise ValueError("Invalid bounded atomic action budget")
    accepted: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not all(isinstance(action.get(key), str)
                   for key in ("source_quote", "action")):
            raise SourceActionBindingError(
                "ATOMIC_ACTION_SOURCE_OWNER_INVALID: " + str(index)
            )
        system: dict[str, Any] | None = None
        seen: set[str] = set()
        previous_issues: dict[str, list[str]] = {}
        for attempt in range(max_attempts_per_action):
            repair_field = (
                next(iter(previous_issues))
                if system is not None and len(previous_issues) == 1
                and next(iter(previous_issues)) in
                ("server_behavior", "observable_result")
                else None
            )
            if repair_field:
                previous_text = str(system.get(repair_field) or "")
                response = router.complete_json(
                    "Correct ONLY the failing " + repair_field +
                    " of ONE previously authored game action. Keep its "
                    "meaning, actual server-side effects and source identity. "
                    "If observable_result is failing, show the actual changed "
                    "world or inventory/ownership state, NOT a menu, ability "
                    "unlock, notification or unchanged prerequisite. "
                    "The previous field was rejected; DO NOT repeat it. "
                    "Return JSON with ONLY the corrected field.\n" +
                    json.dumps({
                        "source_clause": source_clause,
                        "original_source_quote": action["source_quote"],
                        "source_owned_action": action["action"],
                        "verified_other_fields": {
                            key: value for key, value in system.items()
                            if key != repair_field
                        },
                        "rejected_field": previous_text,
                        "exact_validator_errors": previous_issues[repair_field],
                    }, ensure_ascii=False),
                    role="planner", temperature=0.0,
                    max_tokens=360,
                    json_schema={
                        "type": "object",
                        "properties": {
                            repair_field: {"type": "string", "maxLength": 1200}
                        },
                        "required": [repair_field],
                        "additionalProperties": False,
                    },
                )
                patched = (
                    response.get(repair_field)
                    if isinstance(response, dict) else None
                )
                if not isinstance(patched, str) or not patched.strip():
                    raise SourceActionBindingError(
                        "ATOMIC_LOCAL_REPAIR_INVALID: " + str(index) +
                        ": " + repair_field
                    )
                system = dict(system, **{repair_field: patched.strip()})
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
                    }, ensure_ascii=False),
                    role="planner", temperature=0.0,
                    max_tokens=600, json_schema=json_schema,
                )
                systems = response.get("systems") if isinstance(response, dict) else None
                if (not isinstance(systems, list) or len(systems) != 1
                        or not isinstance(systems[0], dict)):
                    raise SourceActionBindingError(
                        "ATOMIC_ACTION_IMPLEMENTATION_INVALID: " + str(index) +
                        ": exactly one system required"
                    )
                system = dict(systems[0])
            signature = json.dumps(system, sort_keys=True, ensure_ascii=False)
            if signature in seen:
                raise SourceActionBindingError(
                    "ATOMIC_LOCAL_REPAIR_NO_PROGRESS: " + str(index)
                )
            seen.add(signature)
            previous_issues = _field_issues(action, system, original_prompt)
            if not previous_issues:
                # Recheck the same public bundle validator for compatibility.
                validate_atomic_system_ownership(
                    [action], [system], original_prompt=original_prompt
                )
                accepted.append(system)
                break
        else:
            raise SourceActionBindingError(
                "ATOMIC_LOCAL_REPAIR_EXHAUSTED: " + str(index) + ": " +
                json.dumps(previous_issues, ensure_ascii=False)[:850]
            )
    validate_atomic_system_ownership(
        actions, accepted, original_prompt=original_prompt
    )
    return accepted
