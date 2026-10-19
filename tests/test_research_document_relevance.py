"""Official Creator documentation must match a requested mechanic.

The returned document and excerpt must both be real. A valid Roblox Creator
domain alone is not evidence for combat/shop/currency correctness.
"""
from roblox_mod_ai.pre_design_research import (
    _FOCUSED_DOC_QUERY,
    _documentation_relevant,
)


def test_shop_cloud_inventory_is_not_grounded_ingame_purchase():
    assert not _documentation_relevant(
        "shop",
        "https://create.roblox.com/docs/cloud/guides/inventory.md",
        "Retrieve creator or player inventory assets with Cloud API",
    )
    assert _documentation_relevant(
        "shop",
        "https://create.roblox.com/docs/reference/engine/classes/ProximityPrompt.md",
        "Triggered fires when player interacts with prompt",
    )


def test_avatar_validation_is_not_combat_evidence():
    assert not _documentation_relevant(
        "combat",
        "https://create.roblox.com/docs/art/characters/validation-tool.md",
        "Avatar mesh layers, UVs and accessory cages",
    )
    assert _documentation_relevant(
        "combat",
        "https://create.roblox.com/docs/reference/engine/classes/Humanoid.md",
        "Humanoid:TakeDamage applies damage to a Humanoid",
    )


def test_conceptual_authority_page_is_not_coin_pickup_api():
    assert not _documentation_relevant(
        "coins",
        "https://create.roblox.com/docs/projects/server-authority.md",
        "Server-authoritative prediction and replay",
    )
    assert _documentation_relevant(
        "coins",
        "https://create.roblox.com/docs/reference/engine/classes/BasePart.md",
        "BasePart.Touched is a signal when a part makes contact",
    )


def test_unknown_novel_facets_remain_searchable_without_fake_success():
    assert _documentation_relevant("intent-user-game-facet",
        "https://create.roblox.com/docs/reference/engine/classes/Terrain.md",
        "Terrain APIs")
    for facet in ("coins", "shop", "combat", "leaderboard"):
        assert facet in _FOCUSED_DOC_QUERY
