"""Source-request constraints shared by research, design and source acceptance.

Buying/trading in a game does not imply Roblox platform monetization. These
checks target the concrete uploaded misinterpretation, not arbitrary gameplay.
"""
from __future__ import annotations

import re
from typing import Any

_MONETIZATION = re.compile(
    r"\b(?:robux|marketplaceservice|game\s*passes?|developer\s+products?|"
    r"real[- ]money|paid\s+access)\b|로벅스|로부스|현금\s*결제|유료\s*결제|게임\s*패스",
    re.IGNORECASE,
)


def _positive_monetization(text: str) -> bool:
    text = re.sub(r"(?i)\b(don|doesn|isn|aren|wasn|weren|shouldn|mustn|can|won)['’]t\b",
                  lambda match: {"don": "do", "doesn": "does", "isn": "is", "aren": "are",
                                 "wasn": "was", "weren": "were", "shouldn": "should",
                                 "mustn": "must", "can": "can", "won": "will"}[match.group(1).lower()] + " not", text)
    for mention in _MONETIZATION.finditer(text):
        before = text[max(0, mention.start() - 30):mention.start()]
        after = text[mention.end():mention.end() + 28]
        if re.search(r"\b(?:no|without|never|avoid|disable|prohibit)\b(?:\W+\w+){0,3}\W*$|"
                     r"\b(?:do|does|must|should|will)\s+not\b(?:\W+\w+){0,3}\W*$", before, re.I):
            continue
        if re.match(r"(?:을|를|는|은|가|이)?\s*(?:사용하지|쓰지|없이|금지|불가|없|안\s*쓰|아닌|아니라|말고)|"
                    r"\s+(?:(?:is|are)\s+)?(?:not\s+(?:used|allowed|required|enabled)|disabled|forbidden)", after, re.I):
            continue
        return True
    return False


def request_semantic_errors(value: Any, original_prompt: str) -> list[str]:
    """Reject unsolicited platform monetization with a repairable diagnosis."""
    if _positive_monetization(original_prompt):
        return []

    def values(item: Any):
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for child in item.values():
                yield from values(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                yield from values(child)

    if any(_positive_monetization(text) for text in values(value)):
        return [
            "UNREQUESTED_MONETIZATION: the original user did not request Robux, "
            "game passes or real-money products. Implement buying/trading with "
            "the game's earned currency and owned items. Do not introduce "
            "MarketplaceService or a Robux balance API."
        ]
    return []
