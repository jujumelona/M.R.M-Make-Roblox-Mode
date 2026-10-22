"""Detect lost objectives in source-first game planning, not prompt hashes."""
from roblox_mod_ai.semantic_preservation import source_intent_conflicts
from roblox_mod_ai.source_decomposition import (
    source_chunks, valid_chunk_classification,
)
from roblox_mod_ai.request_contract import validate_model_behaviors


def test_combined_enemy_and_settlement_source_is_not_pvp_only():
    source = "Fight alien enemies and colonize a planet with a settlement"
    assert source_intent_conflicts(
        source, "The player shoots another player. Player health decreases.")
    assert source_intent_conflicts(
        source, "Players defeat alien enemies and receive XP.")
    assert not source_intent_conflicts(
        source, "Players defeat hostile NPC aliens, colonize the planet "
        "and record a persistent settlement.")


def test_game_specific_korean_request_preserves_enemy_and_settlement_roles():
    for source, wrong in (
        ("외계인과 싸움", "Damage the target player and send PvP hit results"),
        ("식민지화", "Show the combat UI and enable a map"),
        ("몬스터와 전투", "Another player loses hitpoints and respawns"),
    ):
        assert source_intent_conflicts(source, wrong)
    assert not source_intent_conflicts(
        "몬스터와 전투", "The player attacks enemy NPC monsters within range")


def test_source_chunks_do_not_lose_independent_gameplay_actions():
    statement = "외계인과 싸움 식민지화등 여러가지가"
    chunks = source_chunks(statement)
    assert " ".join(chunks) == statement
    assert any("싸움" in row for row in chunks)
    assert any("식민지화" in row for row in chunks)
    # Exact word boundaries in natural language need not isolate every action.
    # If a chunk owns both, its ONE classification must still retain BOTH
    # obligations. The 9B game planner may then create distinct server actions.
    for chunk in chunks:
        if "싸움" in chunk and "식민지화" in chunk:
            wrong = {"behaviors": [{
                "chunk_id": "both",
                "intent": "Alien NPC combat",
                "english_query": "Roblox hostile NPC fight",
            }]}
            assert valid_chunk_classification(
                wrong, [{"chunk_id": "both", "source_span": chunk}]
            ) == {}
            correct = {"behaviors": [{
                "chunk_id": "both",
                "intent": "Fight alien NPCs and colonize the planet",
                "english_query": "Roblox NPC combat and colony settlement",
            }]}
            assert "both" in valid_chunk_classification(
                correct, [{"chunk_id": "both", "source_span": chunk}]
            )


def test_classifier_must_keep_settlement_and_hostile_npc_owners():
    original = [
        {"chunk_id": "chunk-001", "source_span": "외계인과 싸움"},
        {"chunk_id": "chunk-002", "source_span": "식민지화등"},
    ]
    bad = {"behaviors": [
        {"chunk_id": "chunk-001",
         "intent": "Validate the attack position against another player and apply damage",
         "english_query": "Roblox server PvP target player health"},
        {"chunk_id": "chunk-002", "intent": "Show a map selection interface",
         "english_query": "Roblox screen GUI map button"},
    ]}
    assert valid_chunk_classification(bad, original) == {}
    valid = {"behaviors": [
        {"chunk_id": "chunk-001",
         "intent": "Damage alien NPC enemies with server-confirmed hits",
         "english_query": "Roblox damage non-player enemy humanoid"},
        {"chunk_id": "chunk-002",
         "intent": "Colonize a planet and persist a settlement with an owner",
         "english_query": "Roblox persistent settlement world ownership"},
    ]}
    result = valid_chunk_classification(valid, original)
    assert set(result) == {"chunk-001", "chunk-002"}


def test_whole_clause_classifier_cannot_claim_pvp_as_npc_combat():
    source = "Fight alien enemies and colonize a planet"
    sections = [
        {"source_span": "Fight alien enemies",
         "intent": "Deal damage to other players in PvP",
         "english_query": "Roblox PvP player health combat"},
        {"source_span": "and colonize a planet",
         "intent": "Colonize a planet and persist its settlement",
         "english_query": "Roblox colony settlement state"},
    ]
    assert not validate_model_behaviors(source, sections)
