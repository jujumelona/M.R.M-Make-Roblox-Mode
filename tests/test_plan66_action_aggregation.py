"""Plan 66: bounded action retries must accumulate, never overwrite progress.

The outputs below are abridged from the user's failed space-game request.
The aggregation is generic; source contracts decide whether a subset is
actually complete.  Source-unsafe candidates are discarded, not certified.
"""
from roblox_mod_ai.source_action_aggregation import (
    collect_source_action_candidates, choose_complete_source_actions,
)
from roblox_mod_ai.request_semantics import request_semantic_errors
from roblox_mod_ai.semantic_preservation import source_intent_conflicts


SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)
OWNED = [{"id": "req-001", "statement": SOURCE}]


def _action(name, server, result):
    return {"name": name, "server_behavior": server,
            "observable_result": result, "world_entities": ["Craft"]}


BUILD = _action(
    "Craft section construction",
    "Server checks the resource inventory before creating a new craft section; "
    "it rejects missing resources, then adds the approved part to the craft.",
    "A newly constructed section appears attached to the craft model.",
)
PURCHASE = _action(
    "Craft section purchase",
    "Server validates the player's purchase against the currency balance; "
    "on success it deducts the exact cost and records the section as owned.",
    "The purchased section is listed in inventory and the balance decreases.",
)
SALE = _action(
    "Craft section sale",
    "Server validates the section belongs to the player; then it transfers "
    "the section value to their currency balance and removes the owned section.",
    "The sold section disappears and the player's balance increases.",
)
GATHER = _action(
    "source-owned-planet-resource-gather",
    "On gather input the server validates a reachable planet resource node, "
    "depletes the real resource source and awards harvested ore to inventory.",
    "The ore node is depleted and the player's resource inventory increases.",
)
PEER = _action(
    "Resource-Trade Exchange",
    "On server-authoritative trade completion, deduct the offered resource "
    "amount from the seller's owned inventory and credit buyer's balance.",
    "Seller's resources fall and buyer's credits increase.",
)


def test_plan66_first_attempt_is_incomplete_but_pool_preserves_it():
    first = collect_source_action_candidates(
        [], [BUILD, PURCHASE, SALE], original_request=SOURCE,
    )
    assert len(first) == 3
    assert choose_complete_source_actions(OWNED, first) is None


def test_plan66_second_attempt_combines_gather_with_build_and_purchase():
    first = collect_source_action_candidates(
        [], [BUILD, PURCHASE, SALE], original_request=SOURCE,
    )
    second = collect_source_action_candidates(
        first, [GATHER], original_request=SOURCE,
    )
    assert len(second) == 4
    chosen = choose_complete_source_actions(OWNED, second)
    assert chosen is not None
    assert 2 <= len(chosen) <= 3
    names = {row["name"] for row in chosen}
    assert "Craft section construction" in names
    assert "source-owned-planet-resource-gather" in names
    assert "Craft section sale" in names, "Money earning cannot be purchase-only"\n    assert "Craft section purchase" not in names
    combined_server = " ".join(row["server_behavior"] for row in chosen)
    assert source_intent_conflicts(SOURCE, combined_server) == []


def test_repeated_actions_do_not_fake_coverage_or_exhaust_pool():
    first = collect_source_action_candidates(
        [], [BUILD], original_request=SOURCE,
    )
    repeated = collect_source_action_candidates(
        first, [dict(BUILD, name="RenamedBuild"), BUILD],
        original_request=SOURCE,
    )
    assert len(repeated) == 1
    assert choose_complete_source_actions(OWNED, repeated) is None


def test_unrequested_peer_trade_is_excluded_before_aggregation():
    assert any("UNREQUESTED_PEER_TRADE" in error
               for error in request_semantic_errors(PEER, SOURCE))
    pool = collect_source_action_candidates(
        [BUILD, GATHER], [PEER], original_request=SOURCE,
    )
    assert PEER not in pool
    assert choose_complete_source_actions(OWNED, pool) is None


def test_same_server_effect_different_names_not_counted_twice():
    first = collect_source_action_candidates(
        [], [BUILD], original_request=SOURCE,
    )
    pool = collect_source_action_candidates(
        first, [dict(BUILD, name="Construction2")],
        original_request=SOURCE,
    )
    assert pool == first


def test_no_pretend_completion_for_only_gather_plus_trade():
    pool = collect_source_action_candidates(
        [], [GATHER, PURCHASE], original_request=SOURCE,
    )
    assert choose_complete_source_actions(OWNED, pool) is None
