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
    r"식민|정착|개척|coloniz|colonis|colon(?:y|ies)|settlem|found(?:ing)?\s+(?:a\s+)?colony|outpost",
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
# A route/status flag alone does not move a character or a vehicle into the
# requested playable destination. This catches "player.state = in_space"
# plans that never launch/teleport/relocate anything. It is an early prose
# acceptance gate, not a substitute for real Studio movement testing.
_SPACE_WORLD_CHANGE = re.compile(
    r"\b(?:launch\w*|depart\w*|fl(?:y|ies|ew)|travel\w*|teleport\w*|"
    r"transport\w*|mov(?:e|es|ed|ing)|relocat\w*|transfer\w*|"
    r"warp\w*|enter\w*|arriv\w*)\b.{0,120}"
    r"\b(?:space|orbit|orbital|planet|world|zone)\b|"
    r"\b(?:space|orbit|orbital|planet|world|zone)\b.{0,75}"
    r"\b(?:launch\w*|depart\w*|travel\w*|teleport\w*|"
    r"mov(?:e|es|ed|ing)|relocat\w*|warp\w*|enter\w*)\b|"
    r"\b(?:set|sets|change|changes|update|updates)\b.{0,65}"
    r"\b(?:position|location|world|zone|region|scene|destination)\b.{0,65}"
    r"\b(?:space|orbit|orbital|planet)\b|"
    r"(?:우주|궤도|행성)(?:로|에|까지)?\s*(?:진입|이동|출발|도착|비행|워프|발사)",
    re.I,
)
# Leaving/ejecting the passenger from an unchanged vehicle is not the same
# mechanic as a requested launch or vehicle-borne departure into space.
_SPACE_ABANDONMENT = re.compile(
    r"\b(?:player|pilot|passenger|crew|avatar|character)\b.{0,65}"
    r"\b(?:leav(?:e|es|ing|es?)|exit\w*|eject\w*|disembark\w*)\b"
    r".{0,70}\b(?:ship|spaceship|spacecraft|shuttle|vessel|rocket)\b|"
    r"\b(?:eject\w*|disembark\w*)\b.{0,90}"
    r"\b(?:player|pilot|passenger|crew|avatar|character)\b|"
    r"\b(?:ship|spaceship|spacecraft|shuttle|vessel|rocket)\b.{0,45}"
    r"\bno longer carrying\b",
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
    r"coloniz|colonis|settlem|outpost|colon(?:y|ies)|found(?:s|ing)?|"
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



# A planet full of "special minerals" is a source-owned resource
# interaction, not a second ship-arrival event. Production proposal 33
# certified a ship relocation module as mineral-gathering gameplay.
_PLANET_SPECIAL_MINERAL_SOURCE = re.compile(
    r"(?:다른\s*행성|외계\s*행성).{0,85}(?:특수\s*광물|광물)|"
    r"\b(?:other|alien|distant)\s+planets?\b.{0,85}"
    r"\b(?:special\s+)?(?:ore|mineral|resource)s?\b",
    re.I,
)
_PLANET_MINERAL = re.compile(
    r"\b(?:ore|mineral|deposit|resource)s?\b|광물|광석|자원",
    re.I,
)
_MINERAL_INTERACTION = re.compile(
    r"\b(?:min(?:e|es|ed|ing)|harvest\w*|gather\w*|"
    r"extract\w*|collect\w*|acquir\w*|pickup|"
    r"pick\s+up|discover\w*)\b|채굴|수집|획득|채취|파밍",
    re.I,
)
_MINERAL_RESULT = re.compile(
    r"\b(?:inventory|cargo|resource\s+count|stored|collected|"
    r"newly\s+mined|yield|harvest|extract|mine\w*|deplet\w*)\b|"
    r"인벤토리|화물|채굴|획득|자원\s*(?:증가|수량)|고갈",
    re.I,
)

def source_planetary_mineral_errors(
    source_span: str, description: str, *,
    outcome: bool = False,
) -> list[str]:
    """Require a *real* mineral mechanic for planet-ore requests.

    Do not treat ship movement, a new mode flag, an inventory-only sale, or
    access to a planet as collecting the requested planetary resource.
    """
    if not _PLANET_SPECIAL_MINERAL_SOURCE.search(str(source_span or "")):
        return []
    output = str(description or "")
    if not _PLANET_MINERAL.search(output) or (
        not outcome and not _MINERAL_INTERACTION.search(output)
    ):
        return [
            "PLANETARY_MINERAL_MECHANIC_DROPPED: other-planet minerals "
            "require extraction, harvesting or obtaining the minerals; "
            "relocating a spacecraft alone does not implement them"
        ]
    if outcome and not _MINERAL_RESULT.search(output):
        return [
            "PLANETARY_MINERAL_RESULT_MISSING: show harvested planetary "
            "minerals in inventory/cargo or a depleted mineral source"
        ]
    return []



# When a source names several purchasable/upgradable subsystems, duplicating
# one of them does not cover the others. Plan 33 implemented TWO weapon
# changes but silently omitted crew and spacecraft performance.
_UPGRADE_EFFECT = re.compile(
    r"\b(?:upgrad\w*|purchas\w*|buy|buys|bought|trade\w*|"
    r"improv\w*|enhanc\w*|increas\w*|recruit\w*|hir(?:e|es|ed)|"
    r"assign\w*|equip\w*)\b|"
    r"업그레이드|구매|거래|고용|영입|강화|확장|향상",
    re.I,
)
_UPGRADE_OBJECTS = {
    "weapon": re.compile(r"\b(?:weapon|gun|armament)s?\b|무기", re.I),
    "crew": re.compile(r"\b(?:crew|crewmember|crew\s+member|recruit|sailor)s?\b|선원", re.I),
    "ship": re.compile(r"\b(?:ship|spacecraft|spaceship|vessel|engine|thruster)s?\b|우주선", re.I),
}


def source_multi_upgrade_errors(
    source_span: str, description: str, *,
    require_implementation: bool = True,
) -> list[str]:
    """Preserve every explicitly enumerated upgrade/purchase category."""
    src = str(source_span or "")
    if not (
        _UPGRADE_EFFECT.search(src)
        and all(pattern.search(src) for pattern in _UPGRADE_OBJECTS.values())
    ):
        return []
    text = str(description or "")
    failures = []
    for name, pattern in _UPGRADE_OBJECTS.items():
        matches = [
            sentence for sentence in re.split(r"[.!?;\n]+", text)
            if pattern.search(sentence)
        ]
        if not matches or (require_implementation and not any(
            _UPGRADE_EFFECT.search(sentence) for sentence in matches
        )):
            failures.append(
                "SOURCE_PURCHASABLE_SUBSYSTEM_DROPPED: " + name +
                " must have a separately described acquisition, upgrade "
                "or performance effect; repeating another subsystem "
                "does not satisfy it"
            )
    return failures


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
    errors.extend(source_planetary_mineral_errors(source, text))
    errors.extend(source_multi_upgrade_errors(
        source, text, require_implementation=require_implementation,
    ))
    # Conditional arrival ("when you go to space, gather minerals") scopes
    # its downstream gameplay; it does not require each downstream feature
    # to implement launch as well. A standalone "can depart into space"
    # still requires a real launch/travel behavior.
    scoped_source = re.sub(r"우주로\s*나가면", "", source)
    if _DEPART_SPACE.search(scoped_source):
        # The same source-owned movement predicate is shared by architecture,
        # fidelity review and Luau ownership assignment. Do not insist on
        # exact English verb order as a condition for accepting vehicle travel.
        from .world_motion_contract import (
            has_vehicle_motion_effect, has_vehicle_arrival_evidence,
        )
        world_effect = (
            has_vehicle_motion_effect(text) if require_implementation else False
        )
        visible_arrival = (
            has_vehicle_arrival_evidence(text)
            if not require_implementation else False
        )
        if not (_SPACE_INTENT.search(text) or world_effect or visible_arrival):
            errors.append(
                "SPACE_TRAVEL_DROPPED: user requested departing into space, "
                "not another ship purchase or upgrade menu"
            )
        elif require_implementation and not (
            _SPACE_WORLD_CHANGE.search(text) or world_effect
        ):
            errors.append(
                "SPACE_TRAVEL_STATE_MISSING: setting a player status to in-space "
                "is not a physical launch, location transfer or world transition"
            )
        if _SPACE_ABANDONMENT.search(text):
            errors.append(
                "SPACE_TRAVEL_REVERSED: ejecting a passenger from the ship "
                "does not fulfill departing into space aboard the ship"
            )
    # Spending/selling EXISTING inventory for earned coins is not evidence
    # that the user can mine, harvest or gather NEW resources. This was the
    # exact gameplay inversion in proposal 48: a "farming" module only
    # decremented the resource balance and credited currency.
    gathering_requested = re.search(
        r"자원\s*(?:파밍|채굴|수집|획득)|자원파밍|광물\s*(?:채굴|수집)|"
        r"\b(?:resource\s+farm\w*|mining|mine\s+resources?|"
        r"gather\s+resources?|harvest\s+resources?)\b",
        source, re.I,
    )
    inventory_sale = re.search(
        r"(?:decrement|deduct|subtract|consume|remove)\w*"
        r".{0,85}\b(?:resource|ore|mineral)\b.{0,40}"
        r"\b(?:balance|quantity|amount|count|inventory)\b|"
        r"(?:decrement|deduct|subtract|consume|remove)\w*"
        r".{0,55}\b(?:requested\s+amount|owned\s+resources?)\b",
        text, re.I,
    )
    paid_instead = re.search(
        r"(?:increment|credit|award|increase)\w*"
        r".{0,70}\b(?:currency|coins?|credits?)\b",
        text, re.I,
    )
    real_gathering = re.search(
        r"\b(?:mine|harvest|extract|gather|collect|gathered|harvested)\w*"
        r".{0,75}\b(?:node|deposit|ore|world|ground|mineral|resource)\b|"
        r"\b(?:resource|ore|mineral)\b.{0,50}"
        r"\b(?:node|deposit|spawn|mine|harvest|gather|collect|extract)\w*\b",
        text, re.I,
    )
    if (require_implementation and gathering_requested and inventory_sale
            and paid_instead and not real_gathering):
        errors.append(
            "RESOURCE_FARMING_DROPPED: the server only sells existing "
            "resources for currency and never acquires new resources "
            "from an authoritative gatherable source"
        )
    if require_implementation and gathering_requested and not real_gathering:
        # A craft recipe consuming existing inventory is NOT the resource
        # gathering mechanic explicitly requested. Prior validations only
        # rejected the narrower "sell stock for coins" inversion, so a
        # craft-only plan silently passed even after mining was discarded.
        errors.append(
            "RESOURCE_GATHER_ACTION_MISSING: resource farming requires a "
            "server-owned gather/harvest/mine effect on a real resource "
            "source, not only using previously owned crafting materials"
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
            def commits_new_settlement(sentence: str) -> bool:
                if not (colony_noun.search(sentence)
                        and state_action.search(sentence)):
                    return False
                # A prerequisite is not a write. Real model output said
                # "requires an already recorded colony before settlement"
                # and passed because "recorded" matched the write regex.
                # Reject guard-only text while allowing a subsequent,
                # explicit commit (e.g. "then records the new colony").
                guard = re.search(
                    r"\b(?:requires?|checks?|validates?|verif(?:y|ies))\b"
                    r".{0,180}\b(?:already|existing|previously|before)\b",
                    sentence, re.I,
                )
                later_commit = re.search(
                    r"\b(?:then|and|on success)\s+"
                    r"(?:(?:the|a)\s+)?(?:server\s+)?"
                    r"(?:records?|persists?|saves?|establishes?|creates?|"
                    r"founds?|claims?|constructs?|stores?|sets?)\b",
                    sentence, re.I,
                )
                if guard and not later_commit:
                    return False
                if re.search(
                    r"\b(?:no|not|never|without)\s+(?:\w+\s+){0,5}"
                    r"(?:record|persist|sav|establish|creat|found|claim|construct)",
                    sentence, re.I,
                ):
                    return False
                return True

            durable = any(commits_new_settlement(sentence)
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
    errors = [
        error for error in source_intent_conflicts(
            source_span, described_result, require_implementation=False
        )
        if not error.startswith("PLANETARY_MINERAL_MECHANIC_DROPPED:")
    ]
    errors.extend(source_planetary_mineral_errors(
        source_span, described_result, outcome=True,
    ))
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
