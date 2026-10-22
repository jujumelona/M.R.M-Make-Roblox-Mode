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
# Departing the starting world and entering playable space is its OWN
# gameplay obligation. Paying for ship upgrades does not fulfil a requested
# launch/travel action, even though both appear in the same sentence.
_DEPART_SPACE = re.compile(
    r"우주(?:로|에)\s*(?:나가|나갈|나간|출발|진입|이동|날아|갈\s*수)|"
    r"(?:launch|depart|fly|travel|go|enter)\s+(?:(?:the|into|to|outer)\s+)*space|"
    r"space\s+(?:travel|launch|departure|flight|flight\s+mode)",
    re.I,
)
_SPACE_INTENT = re.compile(
    r"(?:launch\w*|depart\w*|teleport\w*|transition\w*|travel\w*|fly|flies|flight|enter\w*|go|goes)\b"
    r".{0,65}\b(?:space|orbit|planet)\b|"
    r"\b(?:space|orbit|planet)\b.{0,45}"
    r"\b(?:launch\w*|depart\w*|teleport\w*|transition\w*|travel\w*|fly|flies|flight|arrival)\b|"
    r"우주\s*(?:진입|이동|출발|여행|비행|도달)|우주로\s*(?:나가|갈|출발|진입|이동|여행|비행)|"
    r"행성\s*(?:이동|도착|진입)|발사",
    re.I,
)
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


def source_intent_conflicts(
    source_span: str,
    described_intent: str,
    *,
    require_implementation: bool = True,
) -> list[str]:
    """Check fidelity at the appropriate stage, without inventing mechanics.

    During source classification (`require_implementation=False`), establish
    *what* the user requested: recognizing a colony does not yet require a
    concrete save operation. During authored implementation and acceptance,
    require an actual settlement state transition. Conflating both stages
    made valid source interpretations fail and blocked all code generation.
    """
    source = str(source_span or "").casefold()
    text = str(described_intent or "").casefold()
    errors = []
    # Conditional arrival ("when you go to space, gather minerals") scopes
    # its downstream gameplay; it does not require each downstream feature
    # to implement launch as well. A standalone "can depart into space"
    # still requires a real launch/travel behavior.
    scoped_source = re.sub(r"우주로\\s*나가면", "", source)
    if _DEPART_SPACE.search(scoped_source) and not _SPACE_INTENT.search(text):
        errors.append(
            "SPACE_TRAVEL_DROPPED: user requested departing into space, "
            "not another ship purchase or upgrade menu"
        )
    if _COLONIZATION.search(source):
        if not _INTENT_COLONY.search(text):
            errors.append("SETTLEMENT_DROPPED: user requested colony settlement gameplay")
        elif require_implementation:
            # Every action has to affect the requested world state. Global
            # mentions such as "record currency" + "show colonization feedback"
            # must NOT accidentally certify a colony because both phrases appear
            # somewhere in one 2000-character multi-feature module description.
            # Require an establishment/ownership/saved-state action linked to
            # the colony IN THE SAME SENTENCE.
            colony_noun = re.compile(
                r"coloniz\w*|colonis\w*|colon(?:y|ies)|settlem\w*|"
                r"outpost\w*|식민\w*|정착\w*|개척\w*",
                re.I,
            )
            state_action = re.compile(
                r"persist\w*|sav\w*|record\w*|claim\w*|"
                r"found(?:s|ed|ing)?|establish\w*|construct\w*|"
                r"creat\w*|stor\w*|mark\w*|\bset\b|"
                r"건설\w*|기록\w*|저장\w*|설립\w*|"
                r"소유권\w*|점령\w*",
                re.I,
            )
            sentences = re.split(r"[.!?;\n]+", text)
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


# Observable outcomes and authoritative state contracts answer different
# questions. A client can faithfully display that a planet *became colonized*
# without redundantly saying how a DataStore entry was committed. However a
# menu that merely displays "colonization success" is not evidence that
# ownership or world state changed.
_COLONY_VISIBLE_CHANGE = re.compile(
    r"(?:\b(?:planet|world|territory|outpost|settlement|colony)\b"
    r".{0,90}\b(?:becomes?|became|is now|was|turns?|is marked|has been|"
    r"now|established|settled|colonized|colonised|claimed|owned|built)\b"
    r".{0,90}\b(?:coloniz\w*|colonis\w*|settle\w*|establish\w*|"
    r"claim\w*|own\w*|built|created)\b)|"
    r"(?:\b(?:coloniz\w*|colonis\w*|settlement|colony|territory)\b"
    r".{0,95}\b(?:state|status|level|ownership|progress|territory)\b"
    r".{0,95}\b(?:changes?|updated|increases?|established|confirmed|"
    r"acquired|claimed|now owned)\b)|"
    r"(?:\b(?:colony|settlement|territory)\b"
    r".{0,95}\b(?:established|created|built|founded|now owned|claimed)\b)|"
    r"(?:\b(?:establish\w*|found\w*|claim\w*|creat\w*|build\w*|built)\b"
    r".{0,95}\b(?:colony|settlement|territory)\b)|"
    r"(?:\b(?:planet|world|colony|settlement)\b"
    r".{0,95}\b(?:new owner|new ownership|now owned|claimed territory)\b)|"
    r"(?:행성.{0,35}(?:식민지화|정착지|소유권).{0,35}"
    r"(?:완료|변경|확립|생성|확정|획득))",
    re.I,
)
# "planet becomes colonized" is a particularly common client status signal.
_PLANET_BECOMES_COLONIZED = re.compile(
    r"\b(?:planet|world)\b.{0,55}\b(?:becomes?|became|is now|"
    r"has been|was)\s+(?:fully\s+)?coloniz(?:ed|ed\b|able)|"
    r"\b(?:planet|world)\b.{0,55}\b(?:colonized|colonised)\b",
    re.I,
)


def source_outcome_conflicts(source_span: str, described_result: str) -> list[str]:
    """Validate a visible state consequence without confusing it with storage.

    The host separately validates server authority using
    source_intent_conflicts(require_implementation=True). An outcome must
    identify an actual observable consequence of the requested mechanic,
    not merely an unrelated saving operation or a generic success notification.
    """
    errors = source_intent_conflicts(
        source_span, described_result, require_implementation=False
    )
    if _COLONIZATION.search(source_span) and not (
        _COLONY_VISIBLE_CHANGE.search(described_result)
        or _PLANET_BECOMES_COLONIZED.search(described_result)
    ):
        errors.append(
            "SETTLEMENT_RESULT_MISSING: describe the changed planet, "
            "settlement or ownership state visible to the player, "
            "not just a colony menu or a generic success message"
        )
    return errors
