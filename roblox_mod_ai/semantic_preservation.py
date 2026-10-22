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
        # Every action has to affect the requested world state. Global
        # mentions such as "record currency" + "show colonization feedback"
        # must NOT accidentally certify a colony because both phrases appear
        # somewhere in one 2000-character multi-feature module description.
        # Require an establishment/ownership/saved-state action linked to
        # the colony IN THE SAME SENTENCE.
        colony_noun = re.compile(
            r"coloniz\\w*|colonis\\w*|colon(?:y|ies)|settlem\\w*|"
            r"outpost\\w*|식민\\w*|정착\\w*|개척\\w*",
            re.I,
        )
        state_action = re.compile(
            r"persist\\w*|sav\\w*|record\\w*|claim\\w*|"
            r"found(?:s|ed|ing)?|establish\\w*|construct\\w*|"
            r"creat\\w*|stor\\w*|mark\\w*|\bset\\b|"
            r"건설\\w*|기록\\w*|저장\\w*|설립\\w*|"
            r"소유권\\w*|점령\\w*",
            re.I,
        )
        sentences = re.split(r"[.!?;\\n]+", text)
        durable = any(colony_noun.search(sentence) and
                      state_action.search(sentence)
                      for sentence in sentences)
        if not _INTENT_COLONY.search(text) or not durable:
            errors.append(
                "SETTLEMENT_DROPPED: source requires a recorded or established "
                "colony state, not only a colony label, validation or UI"
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
