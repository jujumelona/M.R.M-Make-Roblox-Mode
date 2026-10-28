"""Source-bound semantic source for concrete world-resource inventory acquisition.

This is NOT a world builder, ore generator, gameplay implementation or proof
that the purported deposit/owner actually exists in Workspace. The 37th
run authored a complete source-owned extraction action, then a separate 9B
free-form re-authoring loop repeated the same invalid third system until
ATOMIC_LOCAL_REPAIR_NO_PROGRESS. Preserve ONLY already authored grounded
input, world origin, positive player-owned inventory mutation.

The independent world-entity, authority-producer, Luau and Studio gates stay
responsible for proving the physical target and actual code.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .semantic_preservation import source_intent_conflicts, source_outcome_conflicts
from .request_semantics import request_semantic_errors


_EXTRACT = re.compile(
    r"\b(?:extract\w*|min(?:e|es|ed|ing)|harvest\w*|"
    r"gather\w*|collect\w*)\b|채굴|채취|수확|수집", re.I,
)
_WORLD_ORIGIN = re.compile(
    r"\b(?:deposits?|veins?|nodes?|mineable|harvestable|"
    r"source[- ]owned\s+(?:resource|mineral|ore)|"
    r"world[- ](?:owned|resource))\b|광맥|광산|채굴지|자원\s*노드",
    re.I,
)
_RESOURCE = re.compile(
    r"\b(?:ores?|minerals?|resources?|materials?|crops?|wood|logs?)\b|"
    r"광물|광석|자원|재료|목재|작물", re.I,
)
_OWNED_INVENTORY = re.compile(
    r"\b(?:owned|player['’]?s?)\b.{0,85}\b(?:inventory|cargo|"
    r"resource\s+balance)\b|"
    r"\b(?:inventory|cargo)\b.{0,70}\b(?:player|owned)\b|"
    r"플레이어.{0,45}(?:인벤토리|보유량)|보유\s*(?:자원|광물)",
    re.I,
)
_GAIN = re.compile(
    r"\b(?:increment\w*|increas\w*|add\w*|credit\w*|"
    r"award\w*|deposit\w*|store\w*|gain\w*|receiv\w*)\b|"
    r"추가|증가|획득|적립", re.I,
)
# A harvested physical world resource can be transferred INTO owned inventory
# without an explicit "increment" verb. Keep this narrow: "extracts" alone,
# an inventory popup, or an unowned recipient does not constitute a gain.
_EXTRACT_TO_OWNED_INVENTORY = re.compile(
    r"\b(?:extract|extracts|harvest|harvests|mine|mines|gather|gathers)\b"
    r".{0,110}\binto\s+(?:the\s+)?player['’]s\s+owned\s+"
    r"(?:resource\s+)?(?:inventory|cargo)\b",
    re.I,
)


_NEGATION = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|doesn't|"
    r"unchanged|pretend|fake)\b.{0,95}\b(?:extract|mine|"
    r"harvest|gather|collect|increment|increase|add|credit|"
    r"inventory|resource|deposit)\w*\b",
    re.I,
)


def preserved_world_inventory_extraction(
    action: dict[str, str], *, original_prompt: str,
) -> dict[str, Any] | None:
    """Retain a complete model-authored physical extraction + inventory gain.

    Do not synthesize the ore location, reward quantity, world asset name,
    ownership record or any new gameplay operation. The host is only
    preserving the exact world effect already articulated by the model.
    """
    if not isinstance(action, dict) or not isinstance(original_prompt, str):
        return None
    quote, owned = action.get("source_quote"), action.get("action")
    if not isinstance(quote, str) or not isinstance(owned, str):
        return None
    if not quote or quote not in original_prompt or len(owned) > 260:
        return None
    if (_NEGATION.search(owned) or not all(regex.search(owned) for regex in (
            _EXTRACT, _WORLD_ORIGIN, _RESOURCE, _OWNED_INVENTORY))
            or not (_GAIN.search(owned)
                    or _EXTRACT_TO_OWNED_INVENTORY.search(owned))):
        return None
    if (source_intent_conflicts(quote, owned)
            or request_semantic_errors(owned, original_prompt)):
        return None
    server = (
        "The authenticated player's extraction request is accepted only "
        "after the server checks the real server-owned world resource "
        "source, proximity, positive available yield and the player's "
        "authority; invalid or repeated requests produce no state change. "
        "On valid extraction, " + owned.strip().rstrip(".; ") + "."
    )
    outcome = (
        "After accepted world-resource extraction, the player's owned "
        "inventory increases by the resource quantity actually extracted "
        "from the validated world deposit; rejected requests change nothing."
    )
    if len(server) > 600:
        return None
    if (source_intent_conflicts(quote, server)
            or source_intent_conflicts(owned, server)
            or source_outcome_conflicts(quote, outcome)
            or source_outcome_conflicts(owned, outcome)):
        return None
    result = {
        "name": "SourceOwnedExtraction" + hashlib.sha256(
            (quote + "\0" + owned).encode("utf-8")
        ).hexdigest()[:10],
        "server_behavior": server,
        "observable_result": outcome,
        # A generic 'deposit' is a class of origin, not proof that a named
        # asset exists; we MUST NOT fabricate a Workspace binding here.
        "world_entities": [],
    }
    if request_semantic_errors(result, original_prompt):
        return None
    return result
