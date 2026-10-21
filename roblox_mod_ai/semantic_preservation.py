"""Source-to-intent semantic preservation, independent of game titles/IDs.

Grammar/source-span coverage alone cannot prove gameplay meaning. Check only
unambiguous, broadly reusable mechanics where a mistaken role changes the
actual game objective (NPC enemies vs PvP, persistent settlements vs UI).
Unrecognized mechanics remain the planner's job; this is not a full translator.
"""
from __future__ import annotations

import re


# A broadly applicable gameplay vocabulary, not a particular prompt/template.
# Include common Korean terms because source spans may be Korean while a
# small model's architecture prose is written in English.
_COLONIZATION = re.compile(
    r"식민|정착|개척|coloniz|colonis|settlem|found(?:ing)?\s+(?:a\s+)?colony|outpost",
    re.I,
)
_HOSTILE = re.compile(
    r"외[계게]인|괴물|몬스터|적군|적\s*npc|alien|enemy|enemies|monsters?|"
    r"hostile|creatures?|non[- ]player\s+enem(?:y|ies)",
    re.I,
)
_COMBAT = re.compile(r"전투|싸움|공격|fight|combat|battle|shoot|attack", re.I)
_INTENT_COLONY = re.compile(
    r"coloniz|colonis|settlem|outpost|colony|found(?:s|ing)?|"
    r"식민|정착|개척", re.I,
)
_INTENT_HOSTILE = re.compile(
    r"alien|enemy|enemies|monsters?|non[- ]player|npc|hostile|"
    r"creature|외[계게]인|괴물|몬스터|적군", re.I,
)
_ONLY_PLAYER_TARGET = re.compile(
    r"(?:attacks?|damages?|shoots?|hits?|target(?:s|ed)?)\s+"
    r"(?:the\s+|other\s+|another\s+|target\s+)?players?\b|"
    r"(?:opposing|target)\s+player['’]?s?\s+(?:health|position)|\bpvp\b",
    re.I,
)


def source_intent_conflicts(source_span: str, described_intent: str) -> list[str]:
    """Return only high-confidence missing/contradictory gameplay obligations.

    Require the *source's* actual mechanic to survive translation. For an
    ambiguous source span, do not guess what the user requested.
    """
    source = str(source_span or "").casefold()
    text = str(described_intent or "").casefold()
    errors = []
    if _COLONIZATION.search(source):
        # Merely displaying a colony menu is not colonization. Require a
        # meaningful state-changing action, not the noun alone.
        durable_action = re.search(
            r"persist\w*|sav\w*|record\w*|claim\w*|found(?:s|ed|ing)?|"
            r"establish\w*|construct\w*|creat\w*|grant\w*|settle\w*|"
            r"marks?\s+(?:the\s+)?planet\s+(?:as\s+)?coloniz\w*|"
            r"식민지화(?:하|되)|정착(?:지)?\s*건설|정착(?:지)?\s*기록",
            text, re.I,
        )
        if not _INTENT_COLONY.search(text) or not durable_action:
            errors.append(
                "SETTLEMENT_DROPPED: source requires a persistent settlement "
                "state change, not only a colony label or UI"
            )
    if _HOSTILE.search(source) and _COMBAT.search(source):
        if not _INTENT_HOSTILE.search(text):
            errors.append("NPC_COMBAT_DROPPED: enemy combat changed into another target")
        elif _ONLY_PLAYER_TARGET.search(text) and not re.search(
            r"(?:players?\s+(?:attack|fight|shoot|hit)\s+(?:aliens?|enemies|monsters?|npcs?))|"
            r"(?:damage|attack|fight|shoot|hit)\s+(?:aliens?|enemies|monsters?|npcs?)", text, re.I
        ):
            errors.append("NPC_COMBAT_TARGET_AMBIGUOUS: player targets replace hostile NPCs")
    return errors
