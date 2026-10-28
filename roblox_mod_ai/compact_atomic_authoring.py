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



def host_verified_resource_market(
    action: dict[str, str], *, original_prompt: str,
) -> dict[str, Any] | None:
    """Compile a source-authorized owned-resource sale as one atomic system.

    A common, precisely specified server transaction does not need a weak
    small model to rewrite the same two required state mutations. No Roblox
    execution is claimed here: Luau, persistence, runtime and security gates
    remain independently required later.
    """
    import re
    from .request_semantics import (
        source_action_authorizations, request_semantic_errors,
    )
    from .semantic_preservation import (
        source_intent_conflicts, source_outcome_conflicts,
    )

    if not isinstance(action, dict) or not isinstance(original_prompt, str):
        return None
    quote = action.get("source_quote")
    owned = action.get("action")
    if not isinstance(quote, str) or not isinstance(owned, str):
        return None
    if quote not in original_prompt:
        return None
    auth = source_action_authorizations(original_prompt)
    if not auth["earned_resource_market"] or auth["peer_asset_exchange"]:
        return None
    # This exact combined source quote was re-bound to a genuine original
    # source span by the host microplanner. Do not guess whether an unrelated
    # purchase, P2P trade or passive money counter is a resource market.
    if not (re.search(r"돈\s*모으|돈\s*벌|코인\s*모으|"
                      r"\b(?:earn|save|collect)\s+(?:money|coins?)\b", quote, re.I)
            and re.search(r"거래|판매|교환|\b(?:trade|sell|sale|exchange)\b",
                          quote, re.I)):
        return None
    if not all((
        re.search(r"\b(?:resource|ore|mineral|inventory)\b", owned, re.I),
        re.search(r"\b(?:money|currency|coins?|credits?)\b", owned, re.I),
        re.search(r"\b(?:deduct|debit|subtract|consume)\w*\b", owned, re.I),
        re.search(r"\b(?:credit|add|award|pay)\w*\b", owned, re.I),
    )):
        return None
    server = (
        "When the authenticated player requests a resource sale, the server "
        "verifies the selected owned resource, positive quantity, stock and "
        "server-owned market price. On acceptance it atomically deducts the "
        "sold resource inventory and credits earned money to that same "
        "player's authoritative currency balance; invalid, duplicate and "
        "insufficient-stock requests change neither balance."
    )
    outcome = (
        "After a successful trade, the player's owned resource inventory "
        "decreases by the sold quantity and the earned money balance "
        "increases by the server-priced payout; rejected requests change "
        "neither displayed balance."
    )
    result = {
        "name": "OwnedResourceMarketSale",
        "server_behavior": server,
        "observable_result": outcome,
        "world_entities": [],
    }
    # This is not an unconditional shortcut. Every same public source,
    # outcome and authorization validator must approve it before reuse.
    if (source_intent_conflicts(quote, server)
            or source_intent_conflicts(owned, server)
            or source_outcome_conflicts(quote, outcome)
            or source_outcome_conflicts(owned, outcome)
            or request_semantic_errors(result, original_prompt)):
        return None
    return result



def author_compact_atomic_system(
    router: Any, action: dict[str, str], *, previous_issues: dict[str, Any],
    authority_gaps: list[dict[str, Any]] | None = None,
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
                      "prior_issues": previous_issues,
                      # Forward only the current SOURCE facet's previously
                      # observed implementation authority defects; atomic
                      # planners bypass the outer 'task' prompt entirely.
                      "authority_replan_observations": (
                          authority_gaps or [])[:6]}, ensure_ascii=False),
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
