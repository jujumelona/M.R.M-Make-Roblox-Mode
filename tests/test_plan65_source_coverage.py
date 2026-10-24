"""Regression: do not lose mining/trading after source-scoped filtering.

The user-requested spaceship cannot be treated as implementable if the plan
merely consumes already-owned resources without giving players a way to obtain
and exchange those resources.
"""
from roblox_mod_ai.semantic_preservation import source_intent_conflicts


SPACE_FARM = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)


def test_plan65_craft_only_must_not_cover_original_gathering_and_trade():
    craft_only = (
        "Server validates the requested craft section and required resources "
        "against existing inventory. On approval it consumes the resources, "
        "adds the section to the craft, and updates the section list."
    )
    issues = source_intent_conflicts(SPACE_FARM, craft_only)
    assert any("RESOURCE_GATHER_ACTION_MISSING" in x for x in issues)
    assert any("SOURCE_TRADE_ACTION_MISSING" in x for x in issues)


def test_real_harvest_and_trade_do_cover_the_source_mechanics():
    complete = (
        "Server validates resource deposits for harvest and mines the ore "
        "node, depletes the world resource source, and grants harvested "
        "resources to player inventory. Server validates a trade purchase or "
        "sale, transfers the item and credits currency for sold minerals. "
        "Server checks gathered resources before adding the crafted section "
        "to the owned spacecraft."
    )
    issues = source_intent_conflicts(SPACE_FARM, complete)
    assert not any("RESOURCE_GATHER_ACTION_MISSING" in x for x in issues), issues
    assert not any("SOURCE_TRADE_ACTION_MISSING" in x for x in issues), issues


def test_menu_does_not_replace_actual_purchase():
    source = "거래 구매"
    proposal = "Server opens a trade menu with buttons and tooltips."
    assert any("SOURCE_TRADE_ACTION_MISSING" in x
               for x in source_intent_conflicts(source, proposal))


def test_generic_non_economy_game_has_no_spurious_economy_obligations():
    assert source_intent_conflicts(
        "Player jumps across floating platforms to checkpoints",
        "Server records a completed checkpoint and moves player respawn position",
    ) == []
