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


def test_space_launch_is_not_disguised_as_another_ship_upgrade_purchase():
    from roblox_mod_ai.semantic_preservation import (
        source_intent_conflicts, source_outcome_conflicts,
    )
    source = "그렇게해서 우주로 나갈수있고"
    wrong = (
        "The server validates the player's currency balance and buys "
        "a ship performance upgrade. The client displays an upgrade menu."
    )
    assert any("SPACE_TRAVEL_DROPPED" in error for error in
               source_intent_conflicts(source, wrong,
                                       require_implementation=False))
    assert any("SPACE_TRAVEL_DROPPED" in error for error in
               source_intent_conflicts(source, wrong))
    assert any("SPACE_TRAVEL_DROPPED" in error for error in
               source_outcome_conflicts(source, wrong))
    correct = (
        "After verified construction and fuel checks, the server launches "
        "the player's spacecraft into space and changes their location."
    )
    assert not source_intent_conflicts(source, correct)
    assert not source_outcome_conflicts(
        source, "The player sees the spacecraft launch into space.")
    # Intent alone does not mean a generic 'space mode' label requires launch.
    assert not source_intent_conflicts(
        "우주모드 자원 파밍", "Mine resource nodes in the space game")


def test_source_classifier_cannot_certify_missing_space_departure():
    from roblox_mod_ai.source_decomposition import valid_chunk_classification
    chunk = [{"chunk_id": "chunk-007",
              "source_span": "그렇게해서 우주로 나갈수있고"}]
    wrong = {"behaviors": [{
        "chunk_id": "chunk-007",
        "intent": "Buy spaceship parts and improve ship performance",
        "english_query": "Roblox server ship upgrade catalog"
    }]}
    assert valid_chunk_classification(wrong, chunk) == {}
    correct = {"behaviors": [{
        "chunk_id": "chunk-007",
        "intent": "Launch the spacecraft into space after assembly",
        "english_query": "Roblox server validated space launch travel"
    }]}
    assert "chunk-007" in valid_chunk_classification(correct, chunk)



def test_when_arrived_in_space_does_not_make_every_planet_miner_a_ship_launcher():
    from roblox_mod_ai.semantic_preservation import source_intent_conflicts
    # Conditional subordinate clause is the scope of a downstream mechanic.
    condition = "우주로 나가면 다른행성의 특수 광물"
    mineral = (
        "The server validates mining on an other-planet deposit, removes "
        "one mineral unit and adds it to the player's inventory."
    )
    assert source_intent_conflicts(condition, mineral) == []
    battle = "우주로 나가면 외계인과 싸움 식민지화가 가능"
    design = (
        "The server validates alien NPC damage and records the player's "
        "established persistent colony settlement on the destination planet."
    )
    assert source_intent_conflicts(battle, design) == []
    # In contrast explicit launch as its own requested action needs movement.
    assert any("SPACE_TRAVEL_DROPPED" in e for e in
               source_intent_conflicts(
                   "그렇게해서 우주로 나갈수있고",
                   "The server buys a ship speed upgrade."))
