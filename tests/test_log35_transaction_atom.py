"""35th failure: purchase and owned upgrade were split into unrelated effects.

The input ZIP's quoted crew action was "Server upgrades the crew's
performance state." under the SOURCE "성능을 거래 구매 등으로", while a separate
weapon-only debit made aggregate source coverage appear sufficient.
"""
import json

from roblox_mod_ai.source_owned_microplanning import (
    _enforce_atomic_purchase_ownership,
)
from roblox_mod_ai.atomic_action_authoring import (
    author_verified_atomic_systems,
)


SOURCE = "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장"


class PaidActionRouter:
    def __init__(self):
        self.prompts = []

    def complete_json(self, prompt, **kwargs):
        self.prompts.append(prompt)
        assert "source_quote" in prompt
        prior = json.loads(prompt.split("\n")[-1])
        prior_action = prior["existing_action"]
        target = "crew" if "crew" in prior_action else "ship"
        return {"action": (
            "On purchase the server validates the buyer's owned " + target +
            " and catalog price, deducts owned currency from the buyer's "
            "balance and upgrades the owned " + target + " performance state."
        )}


def test_35_purchase_and_upgrade_must_be_one_atomic_source_action():
    router = PaidActionRouter()
    original = [
        {"source_quote": "성능을 거래 구매 등으로",
         "action": "Server upgrades the crew's performance state."},
        {"source_quote": "구매 등으로 업그레이드 확장",
         "action": "Server upgrades the spaceship's performance state."},
    ]
    corrected = _enforce_atomic_purchase_ownership(
        router, SOURCE, original, max_actions=6,
    )
    assert len(corrected) == 2
    assert len(router.prompts) == 2
    assert all("deducts owned currency" in row["action"] for row in corrected)
    assert "crew" in corrected[0]["action"]
    assert "ship" in corrected[1]["action"] or "spaceship" in corrected[1]["action"]
    assert all(row["source_quote"] == original[i]["source_quote"]
               for i, row in enumerate(corrected))


class TransactionRetryRouter:
    supports_host_standard_transport = True

    def __init__(self):
        self.calls = []

    def complete_json(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        index = len(self.calls)
        if index == 1:
            return {
                "name": "UpgradeOwnedCrew",
                "server_behavior": (
                    "Server validates the authenticated buyer and modifies "
                    "the player's owned crew performance state but does not "
                    "record any purchase debit."
                ),
                "world_entities": [],
            }
        if index == 2:
            return {
                "observable_result": (
                    "The purchased crew performance increases and the "
                    "player sees the improved owned crew statistics."
                )
            }
        if index == 3:
            # 9B first structure reply still does not describe actual debit.
            return {
                "payment_mutation": (
                    "The server records the approved purchase request "
                    "without modifying the player's wallet."
                ),
                "received_mutation": (
                    "The server upgrades the buyer's owned crew "
                    "performance state and saves its level."
                ),
            }
        if index == 4:
            assert "ATOMIC_TRANSACTION_NO_AUTHORIZED_PAYMENT" in prompt
            return {
                "payment_mutation": (
                    "The server deducts the server-approved catalog cost "
                    "from the buyer's owned currency balance."
                ),
                "received_mutation": (
                    "The server upgrades the buyer's owned crew "
                    "performance state and saves its level."
                ),
            }
        raise AssertionError("Unexpected additional LLM call")


def test_35_bounded_second_structured_debit_repair_salvages_existing_outcome():
    router = TransactionRetryRouter()
    action = {
        "source_quote": "성능을 거래 구매 등으로",
        "action": "Server upgrades the crew's performance state.",
    }
    schema = {"type": "object", "properties": {
        "systems": {"type": "array", "items": {"type": "object"}}
    }}
    verified = {}
    results = author_verified_atomic_systems(
        router, [action], source_clause=SOURCE,
        original_prompt=SOURCE, json_schema=schema,
        retained_verified=verified, max_attempts_per_action=3,
    )
    assert len(router.calls) == 4
    assert len(results) == 1
    assert "deducts" in results[0]["server_behavior"].lower()
    assert "crew" in results[0]["server_behavior"].lower()
    assert verified[(action["source_quote"], action["action"])] == results[0]


def test_35_atomic_repair_preserves_original_purchase_source_and_target():
    router = PaidActionRouter()
    original = [
        {"source_quote": "성능을 거래 구매 등으로",
         "action": "Server upgrades the crew's performance state."},
        {"source_quote": "구매 등으로 업그레이드 확장",
         "action": "Server upgrades the spaceship's performance state."},
    ]
    result = _enforce_atomic_purchase_ownership(
        router, SOURCE, original, max_actions=6,
    )
    assert original[0]["action"] == "Server upgrades the crew's performance state."
    assert original[1]["action"] == "Server upgrades the spaceship's performance state."
    assert result is not original
    assert all("server" in x["action"].lower() for x in result)
