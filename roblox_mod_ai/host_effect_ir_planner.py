"""Convert bounded numeric gameplay semantics to checked executable data.

This is a *generic*, optional planner: no item names, game genres, or prompt
keyword branches. Unsupported actions go to the existing bounded code writer.
A model never authors the Lua shell, Remote, client validation, or persistence.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .typed_action_contract import validate_contract, TypedActionContractError

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}\Z")
_NAMESPACE = "RMMGameplayState"

_EFFECT_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "uses_quantity": {"type": "boolean"},
        "quantity_max": {"type": "integer"},
        "changes": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "properties": {
                "field": {"type": "string"},
                "operation": {"type": "string", "enum": ["increment", "decrement", "set"]},
                "source": {"type": "string", "enum": ["constant", "quantity"]},
                "constant": {"type": "integer"},
                "multiplier": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["field", "operation", "source", "constant", "multiplier", "limit"],
        }},
    },
    "required": ["supported", "uses_quantity", "quantity_max", "changes"],
}


def compile_effect_data(candidate: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Strictly validate the model's numeric data before creating an IR."""
    if not isinstance(candidate, dict) or set(candidate) != set(_EFFECT_SCHEMA["required"]):
        raise ValueError("DECLARATIVE_EFFECT_INVALID_ROOT")
    if candidate["supported"] is not True:
        raise ValueError("DECLARATIVE_EFFECT_UNSUPPORTED")
    uses_input = candidate["uses_quantity"]
    limit_input = candidate["quantity_max"]
    changes = candidate["changes"]
    if (type(uses_input) is not bool or type(limit_input) is not int
            or not 1 <= limit_input <= 1000000
            or not isinstance(changes, list) or not 1 <= len(changes) <= 5):
        raise ValueError("DECLARATIVE_EFFECT_INVALID_INPUT_OR_CHANGES")
    inputs = ([{"id": "quantity", "label": "Quantity", "type": "integer",
                "min": 1, "max": limit_input}] if uses_input else [])
    declared = []
    effects = []
    used = set()
    ever_read_input = False
    for row in changes:
        if not isinstance(row, dict) or set(row) != {
                "field", "operation", "source", "constant", "multiplier", "limit"}:
            raise ValueError("DECLARATIVE_EFFECT_INVALID_CHANGE")
        field, operation, source = row["field"], row["operation"], row["source"]
        max_value, multiplier, constant = row["limit"], row["multiplier"], row["constant"]
        if (not isinstance(field, str) or not _IDENTIFIER.fullmatch(field)
                or field in used or operation not in ("increment", "decrement", "set")
                or source not in ("constant", "quantity")
                or type(max_value) is not int or not 1 <= max_value <= 1000000000
                or type(multiplier) is not int or not 1 <= multiplier <= 1000000
                or type(constant) is not int or not 0 <= constant <= max_value):
            raise ValueError("DECLARATIVE_EFFECT_INVALID_STATE_OR_AMOUNT")
        used.add(field)
        if source == "constant" and operation != "set" and constant == 0:
            raise ValueError("DECLARATIVE_EFFECT_ZERO_MUTATION")
        if source == "quantity":
            if not uses_input or limit_input * multiplier > max_value:
                raise ValueError("DECLARATIVE_EFFECT_UNBOUNDED_QUANTITY")
            ever_read_input = True
            amount = ({"input": "quantity"} if multiplier == 1
                      else {"input": "quantity", "multiplier": multiplier})
        else:
            if multiplier != 1:
                raise ValueError("DECLARATIVE_EFFECT_UNUSED_MULTIPLIER")
            amount = {"constant": constant}
        declared.append({"scope": "player",
                         "key": _NAMESPACE + "." + field, "operation": operation})
        effects.append({"field": field, "operation": operation,
                        "amount": amount, "limit": max_value})
    if uses_input and not ever_read_input:
        raise ValueError("DECLARATIVE_EFFECT_IGNORED_QUANTITY")
    contract = {"inputs": inputs, "target": {"kind": "none"},
                "state_changes": declared}
    try:
        contract = validate_contract(contract, world_entities=[])
    except TypedActionContractError as exc:
        raise ValueError("DECLARATIVE_EFFECT_INVALID_CONTRACT: " + str(exc)) from exc
    program = {"schema": "rmm/transaction-effect-v1",
               "namespace": _NAMESPACE, "changes": effects}
    return contract, program


def try_plan_effect_data(router: Any, system: dict[str, Any],
                         source_requirements: list[dict[str, Any]]
                         ) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """One small bounded JSON call, with safe fallback for nonnumeric actions.

    Unstructured platform operations, NPC behavior, world transitions and
    interactions requiring choices cannot be reduced to this numeric IR.
    """
    if (os.environ.get("RMM_ENABLE_DECLARATIVE_EFFECTS", "1") == "0"
            or not getattr(router, "supports_declarative_effect_program", False)
            or not isinstance(system, dict)
            or system.get("input_mode") != "custom"
            or system.get("interaction") != "request_response"
            or system.get("world_entities")
            or system.get("action_choices")):
        return None
    source = [row.get("statement", "") for row in source_requirements
              if isinstance(row, dict)]
    try:
        response = router.complete_json(
            "Determine if this Roblox gameplay action can be FULLY represented "
            "by 1-5 bounded integer state changes to a single player profile. "
            "If it involves objects, movement, NPCs, physics, relationships, "
            "combat or other effects, set supported=false. "
            "Do not hallucinate mechanics or discard required effects. "
            "For supported=true provide ALL effects, one row per changed "
            "field. Source=constant uses constant; source=quantity uses "
            "validated integer quantity with bounded multiplier. Use "
            "short stable ASCII field IDs and explicit positive limits. "
            "No scripts, no Remote definitions.\n" +
            json.dumps({"source": source,
                        "behavior": system.get("server_behavior", ""),
                        "outcome": system.get("observable_result", "")},
                       ensure_ascii=False),
            role="planner", temperature=0.0, max_tokens=550,
            json_schema=_EFFECT_SCHEMA,
        )
        if not isinstance(response, dict) or response.get("supported") is not True:
            return None
        compiled_contract, program = compile_effect_data(response)
        # An AI-proposed numeric program may not omit, rename or reorder an
        # already declared effect. This is purely typed-IR equivalence; no
        # keyword interpretation, genre condition, or prompt-specific path.
        predeclared = system.get("action_contract")
        if isinstance(predeclared, dict):
            declared = predeclared.get("state_changes")
            if declared is not None:
                if not isinstance(declared, list):
                    return None
                if declared:
                    expected = [
                        (row.get("scope"), row.get("key"), row.get("operation"))
                        for row in declared if isinstance(row, dict)
                    ]
                    actual = [
                        (row["scope"], row["key"], row["operation"])
                        for row in compiled_contract["state_changes"]
                    ]
                    if len(expected) != len(declared) or expected != actual:
                        return None
        return compiled_contract, program
    except (TypeError, ValueError, KeyError, AttributeError, RuntimeError):
        # An unverified interpretation is NEVER materialized as gameplay.
        # The ordinary bounded action coder still owns unsupported mechanics.
        return None
