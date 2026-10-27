"""Source-complete, small-output action decomposition for local planning models.

Never ask a 9B model for a 1,400-token multi-system architecture. It chooses
immutable original-source span IDs and SHORT action labels. The host checks
each attribution, adds only uncovered requested actions, then asks for a
separate short server/outcome contract for every verified action.

No heuristic genre actions or fabricated gameplay are inserted as defaults.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .atomic_action_quotes import (
    SourceActionBindingError, eligible_atomic_action_spans,
    verify_or_bind_actions,
)
from .semantic_preservation import (
    source_intent_conflicts, distinct_upgrade_action_gaps,
)

_MAX_ACTIONS = 6

_ACTION = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "action": {"type": "string", "minLength": 8, "maxLength": 150},
    },
    "required": ["source_id", "action"],
    "additionalProperties": False,
}


def _schema(*, minimum: int, maximum: int, allowed: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"actions": {
            "type": "array", "minItems": minimum, "maxItems": maximum,
            "items": {"type": "object", "properties": {
                **_ACTION["properties"],
                "source_id": {"type": "string", "enum": allowed},
            }, "required": _ACTION["required"], "additionalProperties": False},
        }},
        "required": ["actions"], "additionalProperties": False,
    }


def _call(router: Any, prompt: str, *, candidate_ids: list[str],
          minimum: int, maximum: int, tokens: int) -> list[dict[str, str]]:
    response = router.complete_json(
        prompt, role="planner", temperature=0.0,
        max_tokens=tokens,
        json_schema=_schema(
            minimum=minimum, maximum=maximum, allowed=candidate_ids,
        ),
    )
    rows = response.get("actions") if isinstance(response, dict) else None
    if (not isinstance(rows, list) or not minimum <= len(rows) <= maximum
            or any(not isinstance(row, dict) for row in rows)):
        raise SourceActionBindingError("ATOMIC_SOURCE_ACTION_REPLY_INVALID")
    return rows


def _coverage_issues(source: str, bound: list[dict[str, str]]) -> list[str]:
    # At action-plan stage there is no Luau yet. Nevertheless every planned
    # action must CLAIM its concrete authoritative effect; accepting vague
    # labels here would drop farming, earning or trades whose absence the
    # source validator can detect only in implementation mode.
    claims = [row["action"] for row in bound]
    return [
        *source_intent_conflicts(
            source, ". ".join(claims), require_implementation=True,
        ),
        *distinct_upgrade_action_gaps(source, claims),
    ]


def needs_compound_microplanning(source: str) -> bool:
    """Use small atomic planning only when the SOURCE requires several
    independently testable effects. Single-action sources keep their normal
    route; we never fabricate a second action just to fill a schema.
    """
    issues = source_intent_conflicts(
        source, "", require_implementation=True,
    )
    return len({item.split(":", 1)[0] for item in issues}) >= 2


# General source-language anchors for already reported semantic gaps. The
# original source, not an error label or LLM invention, authorizes an action.
# This lexicon merely chooses a short EXISTING source quote; gameplay behavior
# still comes from the model and must pass the unchanged semantic validators.
_GAP_QUOTE_PATTERNS = {
    "SOURCE_TRADE_ACTION_MISSING": r"거래|교환|판매|매매|\b(?:trade|exchange|barter|purchase|sell)\b",
    "SOURCE_PURCHASE_PAYMENT_MISSING": r"구매|구입|매입|\b(?:purchas\w*|buy|bought)\b",
    "RESOURCE_GATHER_ACTION_MISSING": r"자원\s*파밍|자원\s*채굴|광물|채굴|\b(?:mining|gather|harvest)\b",
    "SOURCE_CURRENCY_EARNING_MISSING": r"돈\s*모으|돈\s*벌|코인|화폐|\b(?:earn|money|currency)\b",
    "SOURCE_SECTION_BUILD_MISSING": r"부위|부품|조립|제작|만들|\b(?:section|part|build|assembl)\w*\b",
    "SOURCE_PURCHASABLE_SUBSYSTEM_DROPPED": r"무기|선원|우주선|\b(?:weapon|crew|ship)\b",
    "SOURCE_DISTINCT_UPGRADE_ACTION_MISSING": r"무기|선원|우주선|\b(?:weapon|crew|ship)\b",
    "SETTLEMENT_DROPPED": r"식민|정착|개척|\b(?:colonize|settle|colony)\b",
    "PLANETARY_MINERAL_MECHANIC_DROPPED": r"광물|광석|자원|\b(?:mineral|ore)\b",
}


def _focused_source_span(
    source: str, missing: str, spans: list[dict[str, str]],
    occupied: set[str],
) -> dict[str, str] | None:
    code = missing.split(":", 1)[0]
    expression = _GAP_QUOTE_PATTERNS.get(code)
    if code in {"SOURCE_PURCHASABLE_SUBSYSTEM_DROPPED",
                "SOURCE_DISTINCT_UPGRADE_ACTION_MISSING"}:
        category = re.search(r"\b(weapon|crew|ship)\b", missing, re.I)
        if category:
            expression = {
                "weapon": r"무기|\bweapon(?:s)?\b",
                "crew": r"선원|\bcrew\b",
                "ship": r"우주선|\bship\b",
            }[category.group(1).lower()]
    if not expression:
        return None
    pattern = re.compile(expression, re.I)
    # Require the claimed concept to exist in the user's ORIGINAL words.
    if not pattern.search(source):
        return None
    matching = [row for row in spans
                if row["quote"] not in occupied
                and pattern.search(row["quote"])]
    return min(matching, key=lambda row: (
        len(row["quote"]), row.get("start", 0)
    )) if matching else None


def _focused_missing_action(
    router: Any, source: str, missing: str,
    spans: list[dict[str, str]], occupied: set[str],
    prior_rejections: list[str],
) -> dict[str, str] | None:
    """Host selects exact source ownership; model supplies ONE effect string.

    Plan 71 retried a ~923-token 48-source-ID prompt three times and got the
    same 29-token short answer, never satisfying SOURCE_TRADE_ACTION_MISSING.
    An action author does not need to classify 48 indices to explain ONE
    explicitly requested mechanic.
    """
    row = _focused_source_span(source, missing, spans, occupied)
    if row is None:
        return None
    response = router.complete_json(
        "Write ONE concrete server gameplay action for this exact ORIGINAL "
        "source phrase. Reply JSON {action:string} only. In one short "
        "sentence specify the server-side input validation, the real "
        "owned state change and what is transferred/earned/built. "
        "A shop menu or an unchanged status is NOT gameplay. "
        "Do not include ANY other action. No Roblox code, no source IDs. "
        "Return the action in English, 35-160 characters. JSON only.\n" +
        json.dumps({
            "source_quote": row["quote"],
            "required_effect": missing,
            "rejected_previous": prior_rejections[-2:],
        }, ensure_ascii=False),
        role="planner", temperature=0.0, max_tokens=160,
        json_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "minLength": 35, "maxLength": 160},
            },
            "required": ["action"], "additionalProperties": False,
        },
    )
    action = response.get("action") if isinstance(response, dict) else None
    if not isinstance(action, str) or not 35 <= len(action.strip()) <= 160:
        raise SourceActionBindingError(
            "ATOMIC_FOCUSED_ACTION_FORMAT_INVALID: " +
            row["quote"][:50],
        )
    return {"source_id": row["id"], "action": action.strip()}


_PURCHASE_ACTION = re.compile(
    r"\b(?:purchas\w*|buy|bought|trad(?:e|es|ing)|"
    r"exchang\w*|hire\w*)\b|구매|거래|고용", re.I,
)
_OWNED_UPGRADE_ACTION = re.compile(
    r"\b(?:upgrad\w*|improv\w*|enhanc\w*|equip\w*|recruit\w*|"
    r"install\w*|acquir\w*)\b|업그레이드|강화|확장|영입|장착", re.I,
)
_TRANSACTION_TARGETS = {
    "weapon": re.compile(r"\b(?:weapon|gun|armament)s?\b|무기", re.I),
    "crew": re.compile(r"\b(?:crew|recruit|hire|sailor)s?\b|선원", re.I),
    "ship": re.compile(r"\b(?:ship|spacecraft|spaceship|engine|thruster)s?\b|우주선", re.I),
}


def _coverage_improves(before: list[str], after: list[str]) -> bool:
    """All old obligations except at least one stay met; no new gap appears."""
    return set(after) < set(before)


def _repair_owned_purchase_effect(
    router: Any, source: str, raw: list[dict[str, str]],
    gaps: list[str], max_actions: int, evidence: list[str],
) -> list[dict[str, str]] | None:
    """Modify ONLY an existing purchase whose payment is absent.

    Buying an upgrade and paying for it are *one* gameplay action.
    Treating an unpaid purchase as an entirely NEW fourth action caused
    plan-73's duplicate-action rejection and repeated missing-payment loop.
    """
    if not any(error.startswith("SOURCE_PURCHASE_PAYMENT_MISSING:")
               for error in gaps):
        return None
    # Raw router actions carry source_id, while the authoritative source_quote
    # is filled in ONLY by verify_or_bind_actions. Never index the raw action
    # by source_quote (plan-74 KeyError retried three times).
    source_quotes = {
        item["id"]: item["quote"] for item in eligible_atomic_action_spans(source)
    }
    for index, row in enumerate(raw):
        old = row["action"]
        targets = {name for name, pattern in _TRANSACTION_TARGETS.items()
                   if pattern.search(old)}
        if not (_PURCHASE_ACTION.search(old) or
                (_OWNED_UPGRADE_ACTION.search(old) and targets)):
            continue
        try:
            response = router.complete_json(
                "Correct ONE EXISTING source-owned purchase or upgrade "
                "action. Keep the SAME target and result, but describe "
                "real server-authoritative payment: validate the owner's "
                "balance, debit actual money/materials at the approved "
                "price and deliver the purchased upgrade. Do not create "
                "another action, invent a second player or free currency, "
                "or replace a weapon upgrade with crew/ship upgrades. "
                "Output JSON {action:string} ONLY, 35-190 characters.\n" +
                json.dumps({
                    "original_source": source,
                    "unchanged_source_quote": (
                        row.get("source_quote") or
                        source_quotes.get(row.get("source_id"), "")
                    ),
                    "existing_action_to_repair": old,
                    "missing_contract": [
                        error for error in gaps if error.startswith(
                            "SOURCE_PURCHASE_PAYMENT_MISSING:"
                        )
                    ],
                }, ensure_ascii=False),
                role="planner", temperature=0.0, max_tokens=180,
                json_schema={
                    "type": "object",
                    "properties": {"action": {
                        "type": "string", "minLength": 35,
                        "maxLength": 190,
                    }},
                    "required": ["action"],
                    "additionalProperties": False,
                },
            )
        except (ValueError, TypeError) as exc:
            evidence.append(
                "EXISTING_PURCHASE_PATCH_INVALID: " + str(exc)[:170]
            )
            continue
        repaired = response.get("action") if isinstance(response, dict) else None
        if not isinstance(repaired, str) or not 35 <= len(repaired) <= 190:
            evidence.append("EXISTING_PURCHASE_PATCH_INVALID_FORMAT")
            continue
        if not _PURCHASE_ACTION.search(repaired):
            evidence.append("EXISTING_PURCHASE_ACTION_REPLACED")
            continue
        if any(not _TRANSACTION_TARGETS[name].search(repaired)
               for name in targets):
            evidence.append("EXISTING_PURCHASE_TARGET_REPLACED")
            # One scoped response must never be reused to patch a sibling.
            return None
        candidate = [dict(item) for item in raw]
        candidate[index]["action"] = repaired.strip()
        try:
            bound = verify_or_bind_actions(
                router, source, candidate,
                require_complete=False, max_actions=max_actions,
            )
        except SourceActionBindingError as exc:
            evidence.append(
                "EXISTING_PURCHASE_OWNER_INVALID: " + str(exc)[:180]
            )
            continue
        remaining = _coverage_issues(source, bound)
        if not _coverage_improves(gaps, remaining):
            evidence.append(
                "EXISTING_PURCHASE_NO_COVERAGE_PROGRESS: " +
                "; ".join(remaining[:2])
            )
            continue
        return candidate
    return None



def _repair_incomplete_owned_exchange(
    router: Any, source: str, raw: list[dict[str, str]],
    gaps: list[str], max_actions: int, evidence: list[str],
) -> list[dict[str, str]] | None:
    """Repair one previously source-bound exchange without adding fake actions.

    A generic "change currency" claim is not a trade. Instead of repeatedly
    asking a 9B model for a whole new action (often the same 29-token answer),
    request the TWO missing state effects as bounded fields. Preserve the
    source ID, all sibling actions and all already-met source obligations.
    This is NOT a game-specific template and NEVER invents actual prices.
    """
    if not any(str(issue).startswith("SOURCE_TRADE_ACTION_MISSING:")
               for issue in gaps):
        return None
    from .atomic_transaction_repair import (
        _DEBIT, _PAYMENT_ASSET, _DELIVERY, _NEGATIVE,
    )
    source_quotes = {
        row["id"]: row["quote"] for row in eligible_atomic_action_spans(source)
    }
    ranked = []
    for i, row in enumerate(raw):
        quote = row.get("source_quote") or source_quotes.get(row.get("source_id"), "")
        action = row.get("action", "")
        if not (_PURCHASE_ACTION.search(quote)
                or _PURCHASE_ACTION.search(action)):
            continue
        # Prefer the source span specifically declaring an exchange, then
        # the already-source-owned action. Never rewrite unrelated siblings.
        ranked.append((not bool(_PURCHASE_ACTION.search(quote)), i))
    for _priority, i in sorted(ranked)[:2]:
        row = raw[i]
        quote = row.get("source_quote") or source_quotes.get(row.get("source_id"), "")
        for _attempt in range(2):
            try:
                reply = router.complete_json(
                    "Repair one EXISTING source-owned economic exchange with "
                    "TWO actual server-owned state mutations, never a menu or "
                    "a mere balance mention. Return JSON object "
                    "{given_mutation, received_mutation}, each describing an "
                    "affirmative concrete change on the authenticated player's "
                    "owned inventory or wallet. For a sale, subtract an owned "
                    "item/resource and credit earned currency. For a purchase, "
                    "deduct the approved owned payment and deliver the item. "
                    "Choose the direction only from the ORIGINAL source clause "
                    "and preserved action, without inventing another player, "
                    "Robux, prices, unrelated assets or a new gameplay action. "
                    "Preserve the previously accepted action target, and "
                    "never repeat the rejected vague claim. JSON only.\n"
                    + json.dumps({
                        "source_clause": source,
                        "immutable_source_quote": quote,
                        "existing_action": row["action"],
                        "missing_validation": gaps[:3],
                        "prior_rejections": evidence[-2:],
                    }, ensure_ascii=False),
                    role="planner", temperature=0.0, max_tokens=230,
                    json_schema={
                        "type": "object",
                        "properties": {
                            "given_mutation": {"type": "string",
                                               "minLength": 24, "maxLength": 180},
                            "received_mutation": {"type": "string",
                                                  "minLength": 24, "maxLength": 180},
                        },
                        "required": ["given_mutation", "received_mutation"],
                        "additionalProperties": False,
                    },
                )
            except (ValueError, TypeError, RuntimeError) as exc:
                evidence.append("OWNED_EXCHANGE_EFFECT_RESPONSE_INVALID: " +
                                str(exc)[:160])
                continue
            given = reply.get("given_mutation") if isinstance(reply, dict) else None
            received = reply.get("received_mutation") if isinstance(reply, dict) else None
            if (not isinstance(given, str) or not isinstance(received, str)
                    or not 24 <= len(given.strip()) <= 180
                    or not 24 <= len(received.strip()) <= 180):
                evidence.append("OWNED_EXCHANGE_EFFECT_FIELDS_INVALID")
                continue
            debit = _DEBIT.search(given)
            if (not debit or not _PAYMENT_ASSET.search(
                    given[debit.start():debit.end()+100])
                    or not _DELIVERY.search(received)
                    or _NEGATIVE.search(given)
                    or _NEGATIVE.search(received)):
                evidence.append("OWNED_EXCHANGE_EFFECT_NO_DUAL_MUTATION")
                continue
            corrected = (
                "For this requested trade or purchase, the server validates "
                "the authenticated player's owned items, available balance "
                "and authorized exchange amount and rejects insufficient "
                "or duplicate attempts; on success " +
                given.strip().rstrip(".; ") + "; then " +
                received.strip().rstrip(".; ") + "."
            )
            candidate = [dict(item) for item in raw]
            candidate[i]["action"] = corrected
            try:
                verified = verify_or_bind_actions(
                    router, source, candidate,
                    require_complete=False, max_actions=max_actions,
                )
            except SourceActionBindingError as exc:
                evidence.append("OWNED_EXCHANGE_SOURCE_REJECTED: " +
                                str(exc)[:160])
                continue
            after = _coverage_issues(source, verified)
            if not _coverage_improves(gaps, after):
                evidence.append("OWNED_EXCHANGE_NO_COVERAGE_PROGRESS: " +
                                "; ".join(after[:2]))
                continue
            return candidate
    return None


def complete_source_owned_actions(
    router: Any, source: str, *, initial_actions: Any = None,
    max_actions: int = _MAX_ACTIONS,
) -> list[dict[str, str]]:
    """Bind 2-3 first actions, append ONLY missing independent source effects.

    Early attempts can be incomplete without being thrown away. The final
    bundle *must* pass the exact existing whole-clause semantic validator.
    """
    if not 2 <= max_actions <= _MAX_ACTIONS:
        raise SourceActionBindingError("ATOMIC_ACTION_BOUND_INVALID")
    spans = eligible_atomic_action_spans(source)
    by_id = {s["id"]: s["quote"] for s in spans}
    if len(spans) < 2:
        raise SourceActionBindingError("ATOMIC_SOURCE_SPANS_INSUFFICIENT")
    if initial_actions is None:
        initial_actions = _call(
            router,
            "From the ORIGINAL source clause choose 2-3 DISTINCT requested "
            "player/server actions. Return ONLY JSON {actions:[{source_id,action}]}. "
            "Each action is a SHORT sentence stating its own authoritative "
            "server-side state change and target, and source_id selects "
            "a matching exact source-text anchor. Do not write Luau code, "
            "invent genre mechanics, or treat a condition as an action. "
            "Preserve different requested upgrade targets separately. JSON only.\n"
            + json.dumps({
                "source": source,
                "source_spans": [
                    {"id": s["id"], "quote": s["quote"]} for s in spans
                ],
            }, ensure_ascii=False),
            candidate_ids=list(by_id), minimum=2, maximum=3, tokens=340,
        )
    raw = list(initial_actions)
    bound = verify_or_bind_actions(
        router, source, raw, require_complete=False, max_actions=max_actions,
    )
    failed_proposals: set[str] = set()
    rejection_evidence: list[str] = []
    while True:
        gaps = _coverage_issues(source, bound)
        if not gaps:
            return verify_or_bind_actions(
                router, source, raw, max_actions=max_actions,
            )
        # Fix a missing payment on the SAME existing upgrade, not by
        # inventing a separate payment-only action and consuming a slot.
        patched_existing = _repair_owned_purchase_effect(
            router, source, raw, gaps, max_actions, rejection_evidence,
        )
        if patched_existing is not None:
            raw = patched_existing
            bound = verify_or_bind_actions(
                router, source, raw,
                require_complete=False, max_actions=max_actions,
            )
            continue
        # An existing action can be corrected even when all six action slots
        # are occupied. New gameplay actions, unlike local field repairs,
        # must respect the source-owned maximum.
        if len(raw) >= max_actions:
            break
        occupied = {row["source_quote"] for row in bound}
        candidates = [
            {"id": s["id"], "quote": s["quote"]}
            for s in spans if s["quote"] not in occupied
        ]
        if not candidates:
            raise SourceActionBindingError("ATOMIC_SOURCE_NO_DISTINCT_CANDIDATES")
        # Two attempts to supply ONE missing effect. A failed reply never
        # replaces previously bound actions or sends them back for rewriting.
        appended = False
        for _ in range(2):
            try:
                additions = _call(
                    router,
                    "The accepted actions below remain FROZEN. Source coverage "
                "is missing specific requested mechanics. Supply EXACTLY ONE "
                "NEW source-owned action implementing the FIRST missing "
                "mechanic. The action must explicitly name the server-owned "
                "state it changes (such as an owned inventory, currency, "
                "component or target world object). Choose an unused "
                "source_id that actually supports it. Do not repeat an "
                "existing subsystem as another requested subsystem. "
                "Do not include accepted actions "
                "in the reply. Return ONLY JSON {actions:[{source_id,action}]}. "
                "No server code or invented game systems. JSON only.\n"
                + json.dumps({
                    "original_source": source,
                    "accepted_actions": bound,
                    "missing_source_obligations": gaps[:4],
                    "available_source_spans": candidates,
                    "invalid_actions_to_avoid": list(failed_proposals)[-3:],
                }, ensure_ascii=False),
                    candidate_ids=[s["id"] for s in candidates],
                    minimum=1, maximum=1, tokens=180,
                )
            except (ValueError, TypeError) as exc:
                # A truncated local JSON completion is not permission to
                # discard the accepted source actions or the entire facet.
                rejection_evidence.append(
                    "LOCAL_ACTION_FORMAT_INVALID: " + str(exc)[:180],
                )
                continue
            proposed = additions[0]
            proposed_signature = json.dumps(proposed, sort_keys=True,
                                             ensure_ascii=False)
            if proposed_signature in failed_proposals:
                rejection_evidence.append("REPEATED_ACTION: " + str(proposed)[:200])
                continue
            try:
                checked = verify_or_bind_actions(
                    router, source, [*raw, proposed],
                    require_complete=False, max_actions=max_actions,
                )
            except SourceActionBindingError as exc:
                failed_proposals.add(proposed_signature)
                rejection_evidence.append(str(exc)[:250] + " ACTION: " + str(proposed)[:180])
                continue
            after = _coverage_issues(source, checked)
            # Semantic coverage must ACTUALLY improve. Adding a duplicate
            # upgrade word or renaming an existing action is not progress.
            if not _coverage_improves(gaps, after):
                failed_proposals.add(proposed_signature)
                rejection_evidence.append("NO_COVERAGE_PROGRESS: " + "; ".join(after[:3]) + " ACTION: " + str(proposed)[:160])
                continue
            raw.append(proposed)
            bound = checked
            appended = True
            break
        if not appended:
            # Last-resort repair is narrower in INFORMATION, not a silent
            # policy relaxation: choose an exact source-owned word in host
            # code, ask the model for one effect ONLY, and validate with the
            # very same complete source + individual attribution checks.
            for _ in range(2):
                try:
                    replacement = _focused_missing_action(
                        router, source, gaps[0], spans, occupied,
                        rejection_evidence,
                    )
                except (ValueError, TypeError, StopIteration) as exc:
                    rejection_evidence.append(
                        "FOCUSED_REPLY_INVALID: " + str(exc)[:160],
                    )
                    continue
                if replacement is None:
                    break
                try:
                    checked = verify_or_bind_actions(
                        router, source, [*raw, replacement],
                        require_complete=False, max_actions=max_actions,
                    )
                except SourceActionBindingError as exc:
                    rejection_evidence.append(
                        "FOCUSED_OWNER_INVALID: " + str(exc)[:200],
                    )
                    continue
                after = _coverage_issues(source, checked)
                if not _coverage_improves(gaps, after):
                    rejection_evidence.append(
                        "FOCUSED_NO_PROGRESS: " +
                        "; ".join(after[:2]) +
                        " ACTION: " + replacement["action"][:160],
                    )
                    continue
                raw.append(replacement)
                bound = checked
                appended = True
                break
        if not appended:
            # Last structured repair: an existing source-owned action can
            # contain an incomplete exchange. Repair it in place; do not
            # burn another action slot or discard independently valid actions.
            replacement_actions = _repair_incomplete_owned_exchange(
                router, source, raw, gaps, max_actions, rejection_evidence,
            )
            if replacement_actions is not None:
                raw = replacement_actions
                bound = verify_or_bind_actions(
                    router, source, raw,
                    require_complete=False, max_actions=max_actions,
                )
                continue
            raise SourceActionBindingError(
                "ATOMIC_SOURCE_MISSING_ACTION_UNRESOLVED: " +
                "; ".join(gaps[:3]) +
                " | rejected: " +
                json.dumps(rejection_evidence[-4:], ensure_ascii=False)[:850],
            )
    remaining = _coverage_issues(source, bound)
    if remaining:
        raise SourceActionBindingError(
            "ATOMIC_SOURCE_MAX_ACTIONS_INCOMPLETE: " +
            "; ".join(remaining[:4]),
        )
    return verify_or_bind_actions(
        router, source, raw, max_actions=max_actions,
    )
