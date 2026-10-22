"""Regression: uploaded plan_failure_logs (3) echoed all 12 game systems
while planning only '우주모드 인데'. Scope by source ownership, not by truncating
JSON or weakening the player-driven Remote/ProximityPrompt validator.
"""
import copy

import pytest

from roblox_mod_ai.facet_scope import scope_semantic_systems
from roblox_mod_ai.host_architecture import (
    HostArchitectureError, expand_semantic_facet,
)


FACETS = [
    {"id": "intent-6538dffbed", "source_span": "우주모드 인데",
     "search_query": "Roblox Create a space mode in Roblox using a themed environment, space-themed assets, and a dedicated game mode setup."},
    {"id": "intent-bf63077ddc", "source_span": "자원파밍 돈모으기",
     "search_query": "Roblox Implement resource mining and gathering mechanics with a currency economy using Roblox game currency."},
    {"id": "intent-bc3c37df3b", "source_span": "거래 등으로",
     "search_query": "Roblox Implement player-to-player trading using a Roblox Marketplace or custom trading system."},
    {"id": "intent-d0d5034a70", "search_query": "Roblox Allow players to build a spaceship section by section using modular parts."},
    {"id": "intent-fc74616758", "search_query": "Roblox Support weapon and crew customization for the spaceship."},
    {"id": "intent-7409ae1aa2", "search_query": "Roblox Implement upgrade and expansion mechanics using earned game currency purchases."},
    {"id": "intent-90a24a77b3", "search_query": "Roblox Enable players to launch their spaceship into space after upgrades."},
    {"id": "intent-382cc52574", "search_query": "Roblox Unlock special planet minerals after launching to space."},
    {"id": "intent-c9496ed4c5", "search_query": "Roblox Implement alien combat encounters in space."},
    {"id": "intent-4cd2b88da4", "search_query": "Roblox Support planet colonization and multiple gameplay activities."},
]


def passive_mode():
    return {"name": "Space Mode Setup",
            "server_behavior": (
                "The server owns the dedicated space-mode state: it enables "
                "the themed environment, space-themed assets, and dedicated "
                "game-mode setup automatically when the world initializes."),
            "client_behavior": "",
            "interaction": "none", "input_mode": "custom",
            "observable_result": (
                "The player sees a themed environment and its dedicated "
                "space mode world setup."), "world_entities": []}


def echo_model():
    systems = [passive_mode()]
    for name in (
        "Resource Mining", "Currency Accumulation", "Trading",
        "Ship Part Construction", "Weapon Upgrade", "Crew Upgrade",
        "Ship Performance Upgrade", "Ship Expansion", "Space Travel",
        "Alien Combat", "Colonization",
    ):
        systems.append({
            "name": name,
            "server_behavior": (
                "The server validates player " + name +
                " actions and updates gameplay state after those actions."),
            "client_behavior": "The client displays the space-themed environment.",
            "interaction": "none",
            "input_mode": "custom",
            "observable_result": "The player sees game activity and a space themed result.",
            "world_entities": [],
        })
    return {"systems": systems}


def test_actual_twelve_system_echo_is_reduced_to_owned_mode_without_changing_its_rules():
    oversized = echo_model()
    sliced, ignored = scope_semantic_systems(
        oversized, facet=FACETS[0], all_facets=FACETS)
    assert oversized["systems"] != sliced["systems"]
    assert len(oversized["systems"]) == 12
    assert sliced["systems"] == [oversized["systems"][0]]
    assert len(ignored) == 11
    assert "Resource Mining" in ignored
    assert "Alien Combat" in ignored
    assert "Space Travel" in ignored
    # The host still constructs real architecture from the unchanged behavior.
    planned = expand_semantic_facet(
        sliced, facet_id=FACETS[0]["id"], requirement_ids=["req-001"],
        source_requirements=[{"id": "req-001", "statement": "우주모드 인데"}],
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
    )
    assert len(planned["modules"]) == 1
    assert not planned["remotes"]
    assert "themed environment" in planned["modules"][0]["behavior"]


def test_scoping_does_not_forge_missing_player_input():
    oversized = echo_model()
    target = FACETS[1]
    scoped, _ = scope_semantic_systems(oversized, facet=target, all_facets=FACETS)
    assert [s["name"] for s in scoped["systems"]] == ["Resource Mining"]
    with pytest.raises(HostArchitectureError, match="interaction=none"):
        expand_semantic_facet(
            scoped, facet_id=target["id"], requirement_ids=["req-002"],
            source_requirements=[{"id": "req-002", "statement": "자원파밍 돈모으기"}],
            reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
        )


def test_no_confident_source_aligned_system_fails_closed():
    only_alien = {"systems": [copy.deepcopy(echo_model()["systems"][-2]),
                             copy.deepcopy(echo_model()["systems"][-1])]}
    with pytest.raises(ValueError, match="SCOPED_SYSTEM_UNATTRIBUTED"):
        scope_semantic_systems(only_alien, facet=FACETS[0], all_facets=FACETS)


def test_distinct_mechanics_under_one_exact_source_clause_can_be_kept():
    target = FACETS[1]
    rich = {"systems": [
        {"name": "Resource Mining", "server_behavior": "Server validates mining."},
        {"name": "Currency Economy", "server_behavior": "Server validates earnings."},
        {"name": "Alien Combat", "server_behavior": "Server validates combat."},
    ]}
    result, ignored = scope_semantic_systems(
        rich, facet=target, all_facets=FACETS)
    assert [x["name"] for x in result["systems"]] == [
        "Resource Mining", "Currency Economy"]
    assert ignored == ["Alien Combat"]


def test_single_system_is_not_silently_rewritten():
    raw = {"systems": [passive_mode()]}
    got, ignored = scope_semantic_systems(raw, facet=FACETS[0], all_facets=FACETS)
    assert got is raw
    assert ignored == []


def test_full_architect_keeps_valid_first_facet_and_processes_later_facet(monkeypatch):
    from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect

    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.delenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", raising=False)
    ledger = {
        "original_prompt": "우주모드 인데 자원파밍 돈모으기",
        "requirements": [
            {"id": "req-001", "statement": "우주모드 인데", "source": "user_prompt"},
            {"id": "req-002", "statement": "자원파밍 돈모으기", "source": "user_prompt"},
        ],
        "facets": [
            dict(FACETS[0], requirements=["req-001"]),
            dict(FACETS[1], requirements=["req-002"]),
        ],
    }

    class Model:
        def __init__(self):
            self.calls = 0

        def complete_json(self, prompt, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return echo_model()
            return {"systems": [{
                "name": "Resource Mining",
                "server_behavior": (
                    "The server validates mining distance to a real resource node "
                    "and grants earned resource and currency on success."),
                "client_behavior": (
                    "The player targets an ore node, presses mine, and sees the "
                    "server confirmed earned resource and currency."),
                "interaction": "event", "input_mode": "custom",
                "world_entities": ["OreNode"],
                "observable_result": (
                    "The player mines an ore node and receives a confirmed "
                    "earned resource reward and currency gain."),
            }]}

    model = Model()
    evidence = {"ledger": ledger, "evidence": []}
    result = RobloxDynamicArchitect(model).design(
        ledger["original_prompt"], evidence, [])
    assert model.calls == 2
    assert len(result["modules"]) == 3  # passive mode + mining server + client
    assert len(result["remotes"]) == 1
    assert len(result["world_objects"]) == 1
    assert len(evidence["architecture_attempts"]) == 2
    assert all(row["passed"] for row in evidence["architecture_attempts"])
    assert len(evidence["architecture_attempts"][0]["out_of_scope_systems_ignored"]) == 11
    assert set(result["acceptance"]) == {"req-001", "req-002"}


def test_multilingual_untranslated_facet_keeps_two_genuine_phases():
    facet = {"id": "source-012-07-0", "source_span": "꽃을 심고 물을 줘서 자라게 한다"}
    raw = {"systems": [
        {"name": "GardenPhase0", "server_behavior": "Grow first plant"},
        {"name": "GardenPhase1", "server_behavior": "Water the plant"},
    ]}
    selected, ignored = scope_semantic_systems(
        raw, facet=facet, all_facets=[facet])
    assert selected is raw
    assert ignored == []


def test_multilingual_untranslated_facet_does_not_assume_unrelated_mechanics():
    facet = {"id": "source-012-07-0", "source_span": "꽃을 심고 물을 줘서 자라게 한다"}
    raw = {"systems": [
        {"name": "GardenPhase0", "server_behavior": "Grow first plant"},
        {"name": "AlienCombatPhase0", "server_behavior": "Fight an alien"},
    ]}
    with pytest.raises(ValueError, match="SCOPED_SYSTEM_UNATTRIBUTED"):
        scope_semantic_systems(raw, facet=facet, all_facets=[facet])


def test_source_ownership_handles_two_distinct_actions_with_morphological_names():
    """Two real actions from one clause must survive despite shared nouns."""
    facets = [
        {"id": "gather", "search_query":
         "Travel into space and gather rare minerals from planets"},
        {"id": "claim", "search_query":
         "Fight aliens and colonize planets as part of a space adventure"},
        {"id": "trade", "search_query":
         "Buy equipment from a trading station"},
    ]
    response = {"systems": [
        {"name": "Alien Combat", "server_behavior": "Server checks alien combat"},
        {"name": "Planet Colonization", "server_behavior": "Server checks claims"},
        {"name": "Resource Mining", "server_behavior": "Server checks extraction"},
    ]}
    scoped, discarded = scope_semantic_systems(
        response, facet=facets[1], all_facets=facets,
    )
    assert [s["name"] for s in scoped["systems"]] == [
        "Alien Combat", "Planet Colonization",
    ]
    assert discarded == ["Resource Mining"]
    assert len(response["systems"]) == 3


def test_direct_action_outweighs_context_copied_into_competing_facet():
    """Do not drop a builder because trade context also mentions building."""
    facets = [
        {"id": "trade", "search_query":
         "Trade to build ship sections, upgrade weapons and expand capacity"},
        {"id": "build", "search_query":
         "Build ship sections part by part, then trade to upgrade weapons"},
        {"id": "upgrade", "search_query":
         "Upgrade ship weapons and components with the earned currency"},
    ]
    response = {"systems": [
        {"name": "Ship Section Builder", "server_behavior": "Install ship parts"},
        {"name": "Ship Upgrade Trader", "server_behavior": "Purchase upgrades"},
    ]}
    scoped, discarded = scope_semantic_systems(
        response, facet=facets[1], all_facets=facets,
    )
    assert [s["name"] for s in scoped["systems"]] == [
        "Ship Section Builder",
    ]
    assert discarded == ["Ship Upgrade Trader"]


def test_shared_generic_word_cannot_claim_foreign_action():
    """Unique topical evidence is necessary for a one-word name overlap."""
    facets = [
        {"id": "construct", "search_query":
         "Build ship sections into a working vessel"},
        {"id": "battle", "search_query":
         "Fight enemy ships and control the battle area"},
    ]
    response = {"systems": [
        {"name": "Ship Combat", "server_behavior": "Attack other vessels"},
        {"name": "Enemy Ships", "server_behavior": "Spawn enemy vessels"},
    ]}
    with pytest.raises(ValueError, match="SCOPED_SYSTEM_UNATTRIBUTED"):
        scope_semantic_systems(response, facet=facets[0], all_facets=facets)
