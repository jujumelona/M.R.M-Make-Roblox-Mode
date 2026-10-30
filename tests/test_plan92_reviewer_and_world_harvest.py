"""Plan 92 regression: do not confuse reviewer formatting with missing mechanics.

Offline semantic contracts only. No game code or Roblox Studio playtest claim.
"""
from roblox_mod_ai.semantic_preservation import source_intent_conflicts
from roblox_mod_ai.dynamic_architect import (
    _ground_source_fidelity_review,
    _review_with_host_semantic_fallback,
)

SOURCE = "자원파밍"
ACTIVE_HARVEST = (
    "Validate that the request references a server-owned ResourceNode instance "
    "in Workspace, is within range, and has not already been harvested. "
    "When the player's server-authenticated extraction succeeds, the server "
    "marks the authoritative node as harvested and extracts 3 units of ore "
    "into the player's owned resource inventory."
)
ACTIVE_OUTCOME = (
    "The player's owned resource inventory increases by the quantity "
    "actually extracted from the world resource deposit."
)


def test_world_source_then_extraction_no_longer_false_negative():
    assert source_intent_conflicts(SOURCE, ACTIVE_HARVEST) == []
    prior_model_source = (
        "The authenticated player's extraction request is accepted only after "
        "the server checks the real server-owned world resource source, "
        "proximity, positive available yield and the player's authority. "
        "On valid extraction, the server marks the world source as harvested "
        "and extracts the corresponding resource into the player's inventory."
    )
    assert source_intent_conflicts(SOURCE, prior_model_source) == []


def test_node_mentioned_without_positive_extraction_is_not_harvest():
    invalid = (
        "Validate a ResourceNode within reach that has not yet been harvested. "
        "An open menu displays the current inventory; no resources are gathered."
    )
    issues = source_intent_conflicts(SOURCE, invalid)
    assert any("RESOURCE_GATHER_ACTION_MISSING" in x for x in issues), issues


def test_inventory_grant_without_world_origin_is_not_harvest():
    invalid = "The server increases the player's resources by the client-requested amount."
    issues = source_intent_conflicts(SOURCE, invalid)
    assert any("RESOURCE_GATHER_ACTION_MISSING" in x for x in issues), issues


def test_same_model_bad_quote_is_not_a_reason_to_rewrite_gameplay():
    reviewer = {
        "covered": True,
        "server_quote": "The model says a source was harvested.",
        "outcome_quote": "The player's inventory has increased visibly.",
        "missing": "",
    }
    assert _ground_source_fidelity_review(
        reviewer, ACTIVE_HARVEST, ACTIVE_OUTCOME
    ).startswith("Unsupported ")
    issue, used = _review_with_host_semantic_fallback(
        reviewer, {"statement": SOURCE}, ACTIVE_HARVEST, ACTIVE_OUTCOME,
    )
    assert issue == ""
    assert used is True


def test_unquoted_review_cannot_accept_unimplemented_harvest():
    reviewer = {
        "covered": True, "server_quote": "Invented server claim",
        "outcome_quote": "Invented outcome claim", "missing": "",
    }
    issue, used = _review_with_host_semantic_fallback(
        reviewer, SOURCE, "The server shows a shop menu.",
        "The player can see shop products.",
    )
    assert used is False
    assert "RESOURCE_GATHER_ACTION_MISSING" in issue


def test_reviewer_genuine_rejection_still_fails_closed():
    reviewer = {
        "covered": False, "server_quote": "",
        "outcome_quote": "", "missing": "No world harvest state change",
    }
    issue, used = _review_with_host_semantic_fallback(
        reviewer, SOURCE, ACTIVE_HARVEST, ACTIVE_OUTCOME,
    )
    assert "Unimplemented source action" in issue
    assert used is False


def test_exact_grounded_quotes_do_not_invoke_fallback():
    reviewer = {
        "covered": True,
        "server_quote": "marks the authoritative node as harvested",
        "outcome_quote": "owned resource inventory increases by the quantity",
        "missing": "",
    }
    issue, used = _review_with_host_semantic_fallback(
        reviewer, SOURCE, ACTIVE_HARVEST, ACTIVE_OUTCOME,
    )
    assert issue == ""
    assert used is False
