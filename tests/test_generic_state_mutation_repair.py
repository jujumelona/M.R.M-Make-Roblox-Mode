"""A model-authored positive state write is preserved independently of genre.

These regressions exercise the same public source/ownership validators used
by the real M.R.M architect. No source-specific answer is injected by host code.
"""
from __future__ import annotations

import json

import pytest

from roblox_mod_ai.atomic_state_mutation_repair import author_state_mutation_repair
from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems
from roblox_mod_ai.host_architecture import HOST_OWNED_SEMANTIC_FACET_SCHEMA

ACTION = {
    "source_quote": "식민지화등",
    "action": "Server marks a planet as colonized.",
}
SOURCE = "행성 탐사와 식민지화등을 할 수 있는 게임"

GOOD = {
    "validated_input": "the authenticated player's planet ownership and proximity to a valid server-owned planet",
    "state_mutation": "records a newly established colony on that planet in the player's persistent settlement ownership state",
    "rejected_input": "unknown planets, duplicate claims, or unauthorized requests without changing saved state",
}


class RepairRouter:
    supports_host_standard_transport = True
    supports_atomic_state_mutation_repair = True

    def __init__(self, patch=None):
        self.patch = GOOD if patch is None else patch
        self.prompts = []

    def complete_json(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "Repair ONE already source-authorized server action" in prompt:
            return self.patch
        if "For this ONE server-implemented action" in prompt:
            return {"observable_result":
                "The target planet now has a newly established colony settlement owned by the player."}
        if "Implement this ONE requested gameplay action" in prompt:
            return {"name": "PlanetSettlement", "world_entities": [],
                "server_behavior":
                    "The server validates the player's planet target and requires an already recorded colony before allowing a colonization request."}
        raise AssertionError("Unexpected generic model call: " + prompt[:100])


def test_model_authored_state_commit_is_independently_validated():
    router = RepairRouter()
    result = author_state_mutation_repair(
        router, ACTION, "Server validates an already existing colony.",
        original_prompt=SOURCE,
        diagnostics=["SETTLEMENT_DROPPED: must record new colony state"],
    )
    assert GOOD["state_mutation"] in result
    assert "server validates" in result.lower()
    assert len(router.prompts) == 1


@pytest.mark.parametrize("mutation", [
    "the server validates the already registered and preexisting settlement status",
    "the server shows the colonization menu and its generic progress badge",
    "the server does not record or create any new colony state after the request",
])
def test_guard_only_ui_and_negated_writes_cannot_pass(mutation):
    bad = {**GOOD, "state_mutation": mutation}
    with pytest.raises(ValueError, match="ATOMIC_STATE_REPAIR_"):
        author_state_mutation_repair(
            RepairRouter(patch=bad), ACTION, "An invalid prior claim",
            original_prompt=SOURCE, diagnostics=["Missing actual state effect"])


def test_failed_server_field_repair_is_scoped_to_only_that_action():
    router = RepairRouter()
    result = author_verified_atomic_systems(
        router, [ACTION], source_clause=SOURCE, original_prompt=SOURCE,
        json_schema=HOST_OWNED_SEMANTIC_FACET_SCHEMA,
    )
    assert len(result) == 1
    assert GOOD["state_mutation"] in result[0]["server_behavior"]
    assert len(router.prompts) == 3
    assert sum("Repair ONE already source-authorized" in p
               for p in router.prompts) == 1


def test_generic_repair_also_handles_unrelated_npc_combat():
    class CombatRouter:
        def complete_json(self, prompt, **kwargs):
            return {
                "validated_input": "the authenticated attacker and an existing server-controlled hostile NPC target",
                "state_mutation": "reduces the alien NPC enemy's authoritative health after a validated player attack",
                "rejected_input": "out of range, dead or unauthorized targets without applying damage",
            }

    action = {"source_quote": "외계인과 싸움",
              "action": "Player fights hostile alien NPC enemies."}
    fixed = author_state_mutation_repair(
        CombatRouter(), action, "The server checks an enemy target",
        original_prompt="외계인과 싸움", diagnostics=["No NPC health state mutation"],
    )
    assert "reduces the alien NPC enemy" in fixed
    assert "unauthorized" in fixed
