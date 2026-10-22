"""Genre-independent regression for classifier false positives.

Source lexical nouns do not authorize a prefab with different gameplay.
Dynamic/novel source requirements remain owned by their source facets.
"""
from roblox_mod_ai.planner import RobloxGameDesignPlanner


def _features(text):
    return RobloxGameDesignPlanner.__new__(
        RobloxGameDesignPlanner).detect_genres_and_features(text)


def test_weapon_upgrade_does_not_invent_combat_session():
    chosen = _features("Earn coins, purchase weapons and upgrade weapon power")
    assert chosen["is_combat"] is False
    assert chosen["is_simulator"] is False


def test_explicit_combat_remains_detected_from_action_language():
    assert _features("Fight hostile enemies")["is_combat"] is True
    assert _features("외계인과 싸움")["is_combat"] is True
    assert _features("적군 공격")["is_combat"] is True


def test_generic_resource_collection_does_not_spawn_coin_collectible_prefab():
    chosen = _features("Gather and collect space resources to craft parts")
    assert chosen["is_coin_collect"] is False
    assert chosen["is_simulator"] is False


def test_inventory_bag_is_not_click_simulator():
    assert _features("Expand a player's item bag")["is_simulator"] is False
    assert _features("클릭 시뮬레이터")["is_simulator"] is True


def test_specific_coin_source_still_authorizes_coin_collect():
    assert _features("Collect world coins")["is_coin_collect"] is True
    assert _features("동전 모으기")["is_coin_collect"] is True
