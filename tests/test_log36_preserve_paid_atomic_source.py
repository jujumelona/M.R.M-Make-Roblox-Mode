"""Log36 regression: the model-authored ship payment was lost in a rewrite.

Real source contract (from the 36th ZIP):
"Server upgrades the spaceship's performance state and debits the
authenticated buyer's owned currency by the server-priced cost in one
atomic transaction."

Only the observable UI wording may be newly authored by a 9B model.
"""
from roblox_mod_ai.atomic_action_authoring import author_verified_atomic_systems
from roblox_mod_ai.compact_atomic_authoring import author_compact_atomic_system
from roblox_mod_ai.paid_atomic_source_contract import (
    preserved_paid_server_behavior,
)

SOURCE = "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"
SHIP = {
    "source_quote": "구매 등으로 업그레이드 확장",
    "action": (
        "Server upgrades the spaceship's performance state and debits "
        "the authenticated buyer's owned currency by the server-priced "
        "cost in one atomic transaction."
    ),
}
CREW = {
    "source_quote": "성능을 거래 구매 등으로",
    "action": (
        "Server upgrades the crew's performance state and atomically "
        "debits the buyer's owned funds or materials at the server price."
    ),
}


class OneOutcomeRouter:
    supports_host_standard_transport = True

    def __init__(self):
        self.prompts = []

    def complete_json(self, prompt, **kwargs):
        self.prompts.append(prompt)
        assert "server_action" in prompt, (
            "Do not ask the local model to rewrite an already verified "
            "purchase debit and upgrade in unstructured server_behavior"
        )
        target = "spaceship" if "spaceship" in prompt else "crew"
        return {
            "observable_result": (
                "After the successful purchase, the player's owned " +
                target + " performance improves and the currency balance "
                "decreases by the server-approved purchase cost."
            )
        }


def test_log36_verified_paid_ship_action_keeps_both_effects_without_server_rewrite():
    router = OneOutcomeRouter()
    result = author_compact_atomic_system(
        router, SHIP, previous_issues={}, original_prompt=SOURCE,
    )
    assert len(router.prompts) == 1
    assert result["name"].startswith("SourceOwnedPaid")
    assert SHIP["action"] in result["server_behavior"]
    assert "debits" in result["server_behavior"]
    assert "spaceship" in result["server_behavior"]
    assert "currency" in result["server_behavior"]
    assert result["world_entities"] == []


def test_log36_semantic_pipeline_accepts_ship_and_crew_without_duplicate_generation():
    router = OneOutcomeRouter()
    schema = {"type": "object", "properties": {
        "systems": {"type": "array", "items": {"type": "object"}}
    }}
    retained = {}
    results = author_verified_atomic_systems(
        router, [CREW, SHIP], source_clause=SOURCE,
        original_prompt=SOURCE, json_schema=schema,
        retained_verified=retained,
    )
    assert len(results) == 2
    assert len(router.prompts) == 2
    assert all("debits" in s["server_behavior"] for s in results)
    assert results[0]["server_behavior"].find("crew") >= 0
    assert results[1]["server_behavior"].find("spaceship") >= 0
    assert len(retained) == 2


def test_log36_unpaid_or_unowned_actions_cannot_bypass_model_authoring():
    unpaid = dict(SHIP, action="Server upgrades the spaceship's performance state.")
    negated = dict(SHIP, action=(
        "Server upgrades the spaceship but never debits the buyer's "
        "owned currency balance."
    ))
    missing_delivery = dict(SHIP, action=(
        "Server debits the buyer's owned currency balance for the purchase."
    ))
    forged_source = dict(SHIP, source_quote="buy the dragon")
    for row in (unpaid, negated, missing_delivery, forged_source):
        assert preserved_paid_server_behavior(
            row, original_prompt=SOURCE,
        ) is None


def test_log36_saved_payment_source_does_not_create_real_catalog_or_world_evidence():
    server = preserved_paid_server_behavior(SHIP, original_prompt=SOURCE)
    assert server is not None
    # A semantic statement is NOT a built catalog/provider and must still
    # go through the independent production authority gate.
    assert "server-owned price or recipe" in server
    assert "catalog_id =" not in server
    assert "SetState(" not in server
