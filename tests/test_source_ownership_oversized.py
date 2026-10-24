"""Regression: source-ownership fallback must recover a 3-action facet
even when the smaller model replies with one extra context-only system."""
import pytest

from roblox_mod_ai.source_ownership_review import (
    SOURCE_OWNERSHIP_REVIEW_SCHEMA,
    SourceOwnershipReviewError,
    ground_source_ownership,
)


def _candidate(name):
    return {
        "name": name,
        "server_behavior": (
            "Server verifies the request and changes the named world entity "
            "after checking all current gameplay preconditions."
        ),
        "observable_result": "The corresponding entity changes visibly.",
    }


def test_four_candidates_preserve_all_three_owned_actions():
    systems = [
        _candidate("Unrelated second launch"),
        _candidate("Planet mining"),
        _candidate("Alien fight"),
        _candidate("Colony founding"),
    ]
    source = "채굴 외계인 전투 식민지 건설"
    evidence = [
        {"index": 0, "owned": False, "source_quote": "", "server_quote": ""},
        *[
            {"index": i, "owned": True,
             "source_quote": quote,
             "server_quote": systems[i]["server_behavior"][:40]}
            for i, quote in [(1, "채굴"), (2, "외계인 전투"), (3, "식민지 건설")]
        ],
    ]
    scoped, rejected = ground_source_ownership(
        {"systems": systems}, {"bindings": evidence}, source_clause=source,
    )
    assert [row["name"] for row in scoped["systems"]] == [
        "Planet mining", "Alien fight", "Colony founding",
    ]
    assert rejected == ["Unrelated second launch"]
    assert SOURCE_OWNERSHIP_REVIEW_SCHEMA["properties"]["bindings"]["maxItems"] >= 4


def test_more_than_three_owned_actions_must_not_be_accepted_silently():
    systems = [_candidate(f"Action{i}") for i in range(4)]
    source = "mining and combat and colonization and harvesting"
    bindings = [
        {"index": i, "owned": True, "source_quote": "combat",
         "server_quote": s["server_behavior"][:40]}
        for i, s in enumerate(systems)
    ]
    with pytest.raises(SourceOwnershipReviewError,
                       match="more than 3 source-owned"):
        ground_source_ownership(
            {"systems": systems}, {"bindings": bindings}, source_clause=source,
        )
