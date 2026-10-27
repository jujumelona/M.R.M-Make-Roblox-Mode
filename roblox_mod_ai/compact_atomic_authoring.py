"""Two short semantic completions per source-owned action for small GGUF models.

Do not request an entire long 'systems' object at once: on T4-local the
600-token JSON cap repeatedly truncated a one-action response. Each call
returns only real model-authored content, with the host compiling transport.
"""
from __future__ import annotations

import json
from typing import Any


_ATOMIC_SERVER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 4, "maxLength": 80},
        "server_behavior": {
            "type": "string", "minLength": 24, "maxLength": 600,
        },
        "world_entities": {
            "type": "array", "maxItems": 5,
            "items": {"type": "string", "maxLength": 48},
        },
    },
    "required": ["name", "server_behavior", "world_entities"],
    "additionalProperties": False,
}
_ATOMIC_OUTCOME_SCHEMA = {
    "type": "object",
    "properties": {
        "observable_result": {
            "type": "string", "minLength": 18, "maxLength": 360,
        },
    },
    "required": ["observable_result"],
    "additionalProperties": False,
}


def author_compact_atomic_system(
    router: Any, action: dict[str, str], *, previous_issues: dict[str, Any],
) -> dict[str, Any]:
    """One model-owned server mutation and one model-owned visible result.

    A completion that exceeds its independent small budget is rejected; the
    caller owns bounded local retries. No arbitrary host-synthesized gameplay
    or default server state mutations are introduced here.
    """
    server = router.complete_json(
        "Implement this ONE requested gameplay action only. Return short JSON "
        "{name,server_behavior,world_entities}. name is a brief unique action "
        "name. server_behavior (2-3 short sentences, under 600 characters) "
        "must specify validated input, real server-owned state mutation, "
        "and rejection of invalid requests. Avoid themes, menus, UI, "
        "other actions, speculative player-to-player exchange and Robux. "
        "world_entities is ONLY for concrete physical objects in "
        "Workspace, such as a mineable resource node, ship hull or an "
        "interaction terminal. Never put inventories, resource balances, "
        "wallets, credits, scores, abstract requests or player profile "
        "fields there; describe those as server-owned data in "
        "server_behavior. Use [] if the action has no physical target. "
        "For gathering, validate a real server-owned gatherable source, "
        "not a requested resource grant. The player cannot choose their "
        "own currency reward by supplying an amount. "
        "No other fields. JSON only.\n"
        + json.dumps({"source_quote": action["source_quote"],
                      "owned_action": action["action"],
                      "prior_issues": previous_issues}, ensure_ascii=False),
        role="planner", temperature=0.0, max_tokens=360,
        json_schema=_ATOMIC_SERVER_SCHEMA,
    )
    if (not isinstance(server, dict)
            or not all(key in server for key in (
                "name", "server_behavior", "world_entities"
            ))
            or not isinstance(server["name"], str)
            or not isinstance(server["server_behavior"], str)
            or not isinstance(server["world_entities"], list)
            or not 24 <= len(server["server_behavior"].strip()) <= 600
            or not 1 <= len(server["name"].strip()) <= 80
            or len(server["world_entities"]) > 5):
        raise ValueError("ATOMIC_COMPACT_SERVER_INVALID")

    outcome = router.complete_json(
        "For this ONE server-implemented action return ONLY short JSON "
        "{observable_result}. Describe visible changes to the named world "
        "object, inventory, ownership or currency. One sentence, less than "
        "360 characters. Do NOT restate the server algorithm or generate "
        "any additional action. JSON only.\n" +
        json.dumps({"source_quote": action["source_quote"],
                    "server_action": server["server_behavior"]},
                   ensure_ascii=False),
        role="planner", temperature=0.0, max_tokens=190,
        json_schema=_ATOMIC_OUTCOME_SCHEMA,
    )
    observable = (
        outcome.get("observable_result")
        if isinstance(outcome, dict) else None
    )
    if (not isinstance(observable, str)
            or not 18 <= len(observable.strip()) <= 360):
        raise ValueError("ATOMIC_COMPACT_OUTCOME_INVALID")
    return {
        "name": server["name"].strip(),
        "server_behavior": server["server_behavior"].strip(),
        "observable_result": observable.strip(),
        "world_entities": server["world_entities"],
    }
