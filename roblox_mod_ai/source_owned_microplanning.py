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
                                               "minLength": 24, "maxLength": 80},
                            "received_mutation": {"type": "string",
                                                  "minLength": 24, "maxLength": 80},
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
                    or not 24 <= len(given.strip()) <= 80
                    or not 24 <= len(received.strip()) <= 80):
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
            # Existing source-binding ABI limits actions to 220 chars.
            # Restrict each model effect rather than bypassing the ABI or
            # cutting off one of the state mutations.
            kind = ("purchase" if re.search(
                r"구매|구입|\b(?:purchas\w*|buy|bought)\b", quote, re.I,
            ) else "trade")
            corrected = (
                "Server validates and executes the requested " + kind + ": " +
                given.strip().rstrip(".; ") + "; then " +
                received.strip().rstrip(".; ") + "."
            )
            if len(corrected) > 220:
                evidence.append("OWNED_EXCHANGE_ACTION_TOO_LONG")
                continue
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



def _recover_explicit_market_exchange(
    router: Any, source: str, raw: list[dict[str, str]],
    gaps: list[str], max_actions: int, evidence: list[str],
) -> list[dict[str, str]] | None:
    """Compile an explicitly authorized resource-for-money exchange.

    The source, not a weak planner response, authorizes both asset classes.
    This generic server-market contract is only used when the original text
    requests trading, resource gathering and earning money. It never invents
    P2P state, Robux, a fixed price or a new asset class. A proposed action
    is accepted only if the normal source binder and WHOLE-clause semantic
    checks prove it strictly improves coverage without losing sibling work.
    """
    if not any(str(g).startswith("SOURCE_TRADE_ACTION_MISSING:")
               for g in gaps):
        return None
    from .request_semantics import source_action_authorizations
    permissions = source_action_authorizations(source)
    if not permissions["earned_resource_market"] or permissions["peer_asset_exchange"]:
        return None
    market_word = re.compile(
        r"거래|교환|판매|매매|\b(?:trad(?:e|es|ing)|exchang(?:e|es|ing)|"
        r"barter\w*|sell\w*|sold)\b", re.I,
    )
    if not market_word.search(source):
        return None
    spans = eligible_atomic_action_spans(source)
    source_quotes = {span["id"]: span["quote"] for span in spans}
    action = (
        "Server trades collected resources for money at a server-priced market: "
        "it deducts owned resource inventory and credits earned currency "
        "to the same player's balance."
    )
    # Do not replace a valid construction or upgrade action merely because
    # its English description happens to mention a purchase or trade.
    eligible = [
        i for i, row in enumerate(raw)
        if market_word.search(source_quotes.get(row.get("source_id"), ""))
        and market_word.search(row.get("action", ""))
    ]
    # Start with the narrowest, source-specific existing owner, not a broad
    # compound sentence that might also implement ship construction.
    eligible.sort(key=lambda i: len(source_quotes.get(raw[i].get("source_id"), "")))
    trials: list[list[dict[str, str]]] = []
    for i in eligible:
        next_rows = [dict(row) for row in raw]
        next_rows[i]["action"] = action
        trials.append(next_rows)
    if len(raw) < max_actions:
        occupied = {source_quotes.get(row.get("source_id")) for row in raw}
        market_spans = [
            span for span in spans if market_word.search(span["quote"])
            and span["quote"] not in occupied
        ]
        # Exact lexical ownership: never manufacture a source ID. The shortest
        # original market phrase is the strongest evidence of this obligation.
        for span in sorted(market_spans, key=lambda s: (len(s["quote"]), s["start"]))[:2]:
            trials.append([*raw, {"source_id": span["id"], "action": action}])
    for candidate in trials:
        try:
            bound = verify_or_bind_actions(
                router, source, candidate,
                require_complete=False, max_actions=max_actions,
            )
        except SourceActionBindingError as exc:
            evidence.append("SOURCE_MARKET_OWNER_INVALID: " + str(exc)[:150])
            continue
        after = _coverage_issues(source, bound)
        if _coverage_improves(gaps, after):
            return candidate
        evidence.append("SOURCE_MARKET_NO_COVERAGE_PROGRESS: " +
                        "; ".join(after[:2])[:150])
    return None



def _combine_derived_market_income(
    router: Any, source: str, raw: list[dict[str, str]],
    *, max_actions: int,
) -> list[dict[str, str]]:
    """Avoid two currency writers for a single resource-sale/earn loop.

    The original source must contain *adjacent*, unmodified words for money
    accumulation and trade, and must authorize resource-market settlement.
    A standalone income action with an independently specified origin (e.g.
    mining payout, quest, salary or kill reward) is not merged. The combined
    source quote is an existing ORIGINAL source span, never a synthetic ID.

    This is a source-owned action-planning rewrite, NOT successful Luau
    verification. Every replacement is re-bound and fully revalidated.
    """
    from .request_semantics import source_action_authorizations
    perms = source_action_authorizations(source)
    if not perms["earned_resource_market"] or perms["peer_asset_exchange"]:
        return raw
    spans = eligible_atomic_action_spans(source)
    by_id = {row["id"]: row["quote"] for row in spans}
    by_quote = {row["quote"]: row["id"] for row in spans}
    money_quote = re.compile(
        r"^(?:돈\s*모으기?|돈\s*벌기?|코인\s*모으기?|"
        r"earn(?:ing)?\s+(?:money|coins?|credits?)|"
        r"save\s+money)$", re.I,
    )
    trade_quote = re.compile(
        r"^(?:거래|판매|교환|trade|trading|sell|sale|exchange)$", re.I,
    )
    independent_income_origin = re.compile(
        r"\b(?:mine|mining|harvest|gather|quest|mission|salary|wage|"
        r"bounty|combat|kill|enemy|alien|job|salary|reward\s+for)\b|"
        r"채굴|퀘스트|임무|급여|전투|몬스터|현상금", re.I,
    )
    unrelated_trade_target = re.compile(
        r"\b(?:ship|crew|weapon|component|upgrade|recruit|part)\b|"
        r"우주선|선원|무기|부품|업그레이드", re.I,
    )
    settlement = (
        "Server executes an authenticated resource trade at an approved "
        "server price: validates available owned resources, deducts "
        "the sold resource inventory and credits earned money to the "
        "same player's authoritative balance."
    )
    # An original span can already contain both words. Patch only that
    # existing trade/income owner if it is a vague currency updater, before
    # attempting to merge two distinct income and trade source spans.
    combo_quote = re.compile(
        r"^(?:돈\s*모으기?|돈\s*벌기?|코인\s*모으기?)"
        r"\s+(?:거래|판매|교환)$", re.I,
    )
    for index, row in enumerate(raw):
        quote = by_id.get(row.get("source_id"), "")
        if (not combo_quote.fullmatch(quote.strip())
                or unrelated_trade_target.search(row.get("action", ""))
                or independent_income_origin.search(row.get("action", ""))):
            continue
        old_action = str(row.get("action", ""))
        if (re.search(r"\b(?:deduct|debit|subtract|consume)\w*\b", old_action, re.I)
                and re.search(r"\b(?:credit|award|pay|increase)\w*\b", old_action, re.I)
                and re.search(r"\b(?:resource|ore|inventory)\b", old_action, re.I)
                and re.search(r"\b(?:money|currency|coins?|credits?)\b", old_action, re.I)):
            continue
        revised = [dict(item) for item in raw]
        revised[index]["action"] = settlement
        try:
            checked = verify_or_bind_actions(
                router, source, revised,
                require_complete=False, max_actions=max_actions,
            )
        except SourceActionBindingError:
            continue
        before = _coverage_issues(
            source, verify_or_bind_actions(
                router, source, raw, require_complete=False,
                max_actions=max_actions,
            ),
        )
        after = _coverage_issues(source, checked)
        if not after or _coverage_improves(before, after):
            return revised
    if len(raw) < 3:
        return raw
    for money_i, income in enumerate(raw):
        iq = by_id.get(income.get("source_id"), "")
        if not money_quote.fullmatch(iq.strip()):
            continue
        if independent_income_origin.search(income.get("action", "")):
            continue
        for trade_i, trade in enumerate(raw):
            if money_i == trade_i:
                continue
            tq = by_id.get(trade.get("source_id"), "")
            if not trade_quote.fullmatch(tq.strip()):
                continue
            if unrelated_trade_target.search(trade.get("action", "")):
                continue
            combined = iq + " " + tq
            combined_id = by_quote.get(combined)
            if combined_id is None or combined not in source:
                continue
            # Do not rewrite an already valid, source-owned two-effect sale.
            # A money-only action may misleadingly satisfy the whole-facet
            # currency validator while the independent trade lacks a receipt.
            action = trade.get("action", "")
            low = action.casefold()
            already_settles = (
                bool(re.search(r"\b(?:deduct|debit|subtract|consume)\w*\b", low))
                and bool(re.search(r"\b(?:credit|award|pay|increase)\w*\b", low))
                and bool(re.search(r"\b(?:resource|ore|inventory)\b", low))
                and bool(re.search(r"\b(?:money|currency|coins?|credits?|balance)\b", low))
            )
            candidate = [dict(row) for i, row in enumerate(raw) if i != money_i]
            replacement_i = trade_i - (1 if money_i < trade_i else 0)
            candidate[replacement_i]["source_id"] = combined_id
            if not already_settles:
                candidate[replacement_i]["action"] = settlement
            try:
                checked = verify_or_bind_actions(
                    router, source, candidate,
                    max_actions=max_actions,
                )
            except SourceActionBindingError:
                continue
            if not _coverage_issues(source, checked):
                return candidate
    return raw




def _replace_weak_owner_with_stronger_overlapping_action(
    router: Any, source: str, raw: list[dict[str, str]], *,
    max_actions: int,
) -> list[dict[str, str]]:
    """Repair a weak atomic action, never append its effect as a duplicate.

    The model often chooses a *broader* overlapping quote for a stronger
    implementation of an already owned feature. Example: "resource farming"
    only granted inventory, so it appended a real mineable-node harvest under
    "resource farming earn money". The broader quote then requires money in
    the harvest, even though the separate verified trade supplies the money.

    Reuse only the existing shorter immutable owner. Require strict semantic
    improvement for that exact quote and no lost whole-clause obligations.
    Never use keyword overlap alone as proof of an executable mechanic.
    """
    if len(raw) < 3:
        return raw
    source_ids = {
        span["id"]: span["quote"]
        for span in eligible_atomic_action_spans(source)
    }
    try:
        before_bound = verify_or_bind_actions(
            router, source, raw, require_complete=False,
            max_actions=max_actions,
        )
    except SourceActionBindingError:
        return raw
    before_gaps = set(_coverage_issues(source, before_bound))
    for new_i, candidate in enumerate(raw):
        broader = source_ids.get(candidate.get("source_id"), "")
        replacement = candidate.get("action", "")
        if not broader or not isinstance(replacement, str):
            continue
        for old_i, original in enumerate(raw):
            if new_i == old_i:
                continue
            narrower = source_ids.get(original.get("source_id"), "")
            old_action = original.get("action", "")
            if (not narrower or not isinstance(old_action, str)
                    or len(broader) <= len(narrower)):
                continue
            # Both are unchanged source spans and the shorter phrase must
            # occur at a complete whitespace-delimited boundary, not merely
            # share a substring or an unrelated gameplay keyword.
            if not re.search(
                r"(?<!\S)" + re.escape(narrower) + r"(?!\S)", broader,
            ):
                continue
            old_errors = set(source_intent_conflicts(
                narrower, old_action, require_implementation=True,
            ))
            new_errors = set(source_intent_conflicts(
                narrower, replacement, require_implementation=True,
            ))
            if not old_errors or not new_errors < old_errors:
                continue
            proposed = [dict(row) for i, row in enumerate(raw) if i != new_i]
            remapped = old_i - (1 if new_i < old_i else 0)
            proposed[remapped]["action"] = replacement
            try:
                verified = verify_or_bind_actions(
                    router, source, proposed, require_complete=False,
                    max_actions=max_actions,
                )
            except SourceActionBindingError:
                continue
            # Full-clause protection: replacing a separate income/payment or
            # independently requested second world action is NOT permitted
            # when it introduces a missing obligation elsewhere.
            if set(_coverage_issues(source, verified)) <= before_gaps:
                return proposed
    return raw


def _enforce_atomic_purchase_ownership(
    router: Any, source: str, bound: list[dict[str, str]], *,
    max_actions: int,
) -> list[dict[str, str]]:
    """Make every purchase-owned UPGRADE one paid transaction before authoring.

    Log35's aggregate source coverage accepted an unpaid CREW performance
    action because a separate WEAPON payment action mentioned purchase.
    Per-child codegen then (correctly) refused the unpaid crew upgrade three
    times. A different action's debit cannot discharge this action's
    obligation. Repair just the source-bound atomic contract, not its siblings
    or executable Luau, and check the same public provenance validator.
    """
    accepted = [dict(row) for row in bound]
    baseline_gaps = set(_coverage_issues(source, accepted))
    for index, owner in enumerate(accepted):
        quote, action = owner["source_quote"], owner["action"]
        # Do not turn ordinary earned currency, stand-alone world actions,
        # or non-purchase combat into a purchasable upgrade.
        if not (_PURCHASE_ACTION.search(quote)
                and _OWNED_UPGRADE_ACTION.search(action)
                and any(p.search(action)
                        for p in _TRANSACTION_TARGETS.values())):
            continue
        missing = [
            err for err in source_intent_conflicts(quote, action)
            if err.startswith(("SOURCE_PURCHASE_PAYMENT_MISSING:",
                               "SOURCE_TRADE_ACTION_MISSING:"))
        ]
        if not missing:
            continue
        errors = []
        for _ in range(2):
            try:
                reply = router.complete_json(
                    "Rewrite only this EXISTING, original-source-owned UPGRADE "
                    "action as ONE atomic purchase/trade. The upgrade and its "
                    "payment MUST be the same server transaction. Validate "
                    "the authenticated buyer's owned money/materials, deduct "
                    "the server-priced cost, and upgrade the SAME owned "
                    "weapon, crew or ship target as the current action. "
                    "The buyer does not supply the price or currency reward. "
                    "No second player, new action, unrequested item, Luau or "
                    "world entity. Return JSON {action:string}, 50-220 chars. "
                    "Keep the same target and source quote. JSON only.\n"
                    + json.dumps({
                        "source_quote": quote, "existing_action": action,
                        "original_clause": source,
                        "missing_effects": missing,
                        "prior_rejections": errors[-2:],
                    }, ensure_ascii=False),
                    role="planner", temperature=0.0, max_tokens=190,
                    json_schema={
                        "type": "object", "properties": {"action": {
                            "type": "string", "minLength": 50,
                            "maxLength": 220,
                        }}, "required": ["action"],
                        "additionalProperties": False,
                    },
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                errors.append(type(exc).__name__ + ": " + str(exc)[:150])
                continue
            revised = reply.get("action") if isinstance(reply, dict) else None
            if not isinstance(revised, str) or not 50 <= len(revised.strip()) <= 220:
                errors.append("INVALID_PAID_UPGRADE_ACTION_REPLY")
                continue
            if any(p.search(action) and not p.search(revised)
                   for p in _TRANSACTION_TARGETS.values()):
                errors.append("PAID_UPGRADE_TARGET_REPLACED")
                continue
            if source_intent_conflicts(quote, revised):
                errors.append("PAID_UPGRADE_STILL_LACKS_EFFECTS")
                continue
            trial = [dict(row) for row in accepted]
            trial[index]["action"] = revised.strip()
            try:
                admitted = verify_or_bind_actions(
                    router, source, trial, require_complete=False,
                    max_actions=max_actions,
                )
            except SourceActionBindingError as exc:
                errors.append("PAID_UPGRADE_SOURCE_REJECTED: " + str(exc)[:160])
                continue
            if not set(_coverage_issues(source, admitted)) <= baseline_gaps:
                errors.append("PAID_UPGRADE_DROPPED_ANOTHER_SOURCE_EFFECT")
                continue
            accepted = admitted
            break
        else:
            raise SourceActionBindingError(
                "ATOMIC_PAID_UPGRADE_OWNER_UNRESOLVED: " + quote +
                "; " + "; ".join(errors[-2:]))
    return accepted


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
        # A stronger harvest/upgrade/other source action must replace a weak
        # existing owner before a multiword quote is assigned to a duplicate.
        # This preserves the independently accepted siblings and avoids
        # demanding unrelated effects from the broad quotation.
        promoted = _replace_weak_owner_with_stronger_overlapping_action(
            router, source, raw, max_actions=max_actions,
        )
        if promoted is not raw:
            raw = promoted
            bound = verify_or_bind_actions(
                router, source, raw, require_complete=False,
                max_actions=max_actions,
            )
        # Consolidate an adjacent, source-authorized market income even when
        # the model's money-only action currently fails whole-clause coverage.
        # This prevents wasting attempts "fixing" the independent currency
        # mint instead of routing earnings through the sale itself.
        consolidated = _combine_derived_market_income(
            router, source, raw, max_actions=max_actions,
        )
        if consolidated is not raw:
            raw = consolidated
            bound = verify_or_bind_actions(
                router, source, raw,
                require_complete=False, max_actions=max_actions,
            )
        gaps = _coverage_issues(source, bound)
        if not gaps:
            complete = verify_or_bind_actions(
                router, source, raw, max_actions=max_actions,
            )
            return _enforce_atomic_purchase_ownership(
                router, source, complete, max_actions=max_actions,
            )
        # Resolve explicitly source-authorized resource markets at the host
        # contract layer before spending model retries on fabricated P2P
        # proposals. Never soften the existing attribution/fidelity gates.
        market_recovery = _recover_explicit_market_exchange(
            router, source, raw, gaps, max_actions, rejection_evidence,
        )
        if market_recovery is not None:
            raw = market_recovery
            bound = verify_or_bind_actions(
                router, source, raw,
                require_complete=False, max_actions=max_actions,
            )
            continue
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
            # A full source-owned action roster cannot append another action.
            # It CAN repair an incomplete existing transaction in place.
            rewritten = _repair_incomplete_owned_exchange(
                router, source, raw, gaps, max_actions, rejection_evidence,
            )
            if rewritten is not None:
                raw = rewritten
                bound = verify_or_bind_actions(
                    router, source, raw,
                    require_complete=False, max_actions=max_actions,
                )
                continue
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
    complete = verify_or_bind_actions(
        router, source, raw, max_actions=max_actions,
    )
    return _enforce_atomic_purchase_ownership(
        router, source, complete, max_actions=max_actions,
    )
