"""Plan 67: a source clause can require four independently triggered actions.

A raw model response remains limited to three; only a host-selected bundle
which actually covers the complete original clause may expand beyond three.
"""
import pytest

from roblox_mod_ai.host_architecture import (
    HostArchitectureError, expand_semantic_facet,
)
from roblox_mod_ai.semantic_preservation import source_intent_conflicts
from roblox_mod_ai.source_action_aggregation import (
    collect_source_action_candidates, choose_complete_source_actions,
)

SOURCE = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
    "우주선을 부위마다 만들어서 만들수있고"
)
REQUIREMENTS = [{"id": "req-001", "statement": SOURCE}]


def _system(name, server, outcome):
    return {
        "name": name,
        "server_behavior": server,
        "observable_result": outcome,
        "world_entities": [],
        "interaction": "request_response",
        "input_mode": "custom",
        "client_behavior": (
            "The player chooses " + name +
            " and the client displays a server-confirmed update."
        ),
    }


BUILD = _system(
    "CraftSectionBuild",
    "Server verifies available craft materials, then adds the selected "
    "section to the craft's server-owned parts; invalid builds are rejected.",
    "The ship has a visibly attached newly constructed section.",
)
MINE = _system(
    "MineralSourceHarvest",
    "Server validates a player's range to an ore deposit then mines ore "
    "from the world node, consumes the deposit and awards ore inventory.",
    "The deposit visually depletes and the player has more ore in inventory.",
)
EARN = _system(
    "EarnIngameCurrency",
    "Server validates the amount of mined ore delivered for a reward and "
    "credits money to the player-owned balance; invalid claims are rejected.",
    "After a validated ore delivery the player's earned money increases.",
)
TRADE = _system(
    "CatalogTrade",
    "Server validates a priced catalog purchase, deducts credits from the "
    "player balance and transfers the purchased item into owned inventory.",
    "The bought item appears in inventory and the coin balance decreases.",
)


def test_real_uploaded_builder_is_not_a_false_missing_section():
    actual_server = (
        "Server validates that the player is in space mode and that the "
        "requested section is a valid craft part; on success it adds the "
        "section to the craft's server-owned parts and rejects invalid or "
        "already-built sections."
    )
    errors = source_intent_conflicts(SOURCE, actual_server)
    assert not any("SOURCE_SECTION_BUILD_MISSING" in error for error in errors)


def test_four_distinct_source_obligations_cannot_be_squeezed_into_three():
    pool = collect_source_action_candidates(
        [], [BUILD, MINE, EARN, TRADE], original_request=SOURCE,
    )
    assert len(pool) == 4
    assert choose_complete_source_actions(REQUIREMENTS, pool) is None
    selected = choose_complete_source_actions(
        REQUIREMENTS, pool, max_actions=6,
    )
    assert selected is not None
    assert {row["name"] for row in selected} == {
        "CraftSectionBuild", "MineralSourceHarvest",
        "EarnIngameCurrency", "CatalogTrade",
    }


def _expand(raw, *, cap=3):
    return expand_semantic_facet(
        raw, facet_id="intent-four-actions",
        requirement_ids=["req-001"],
        source_requirements=REQUIREMENTS,
        reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
        max_systems=cap,
    )


def test_host_rejects_untrusted_four_system_payload_by_default():
    with pytest.raises(HostArchitectureError, match="SCOPED_FEATURE_TOO_LARGE"):
        _expand({"systems": [BUILD, MINE, EARN, TRADE]})


def test_host_can_compile_four_source_complete_actions_after_source_selection():
    selected = choose_complete_source_actions(
        REQUIREMENTS, [BUILD, MINE, EARN, TRADE], max_actions=6,
    )
    assert selected is not None
    result = _expand({"systems": selected}, cap=6)
    assert len([m for m in result["modules"] if m["role"] == "server"]) == 4
    assert len(result["remotes"]) == 4
