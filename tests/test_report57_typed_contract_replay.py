"""Replays the actual failure shape from plan_failure_logs (16).

Regression fixtures are permitted to use the uploaded scenario: production
code MUST NOT branch on it. This exercises the real facet planner with THREE
independent systems and local-model shared-schema output shape.
"""
from __future__ import annotations

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.typed_action_contract import SCHEMA


def test_report57_three_source_owned_actions_survive_inactive_input_metadata(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    source = "거래 등으로"
    research = {
        "ledger": {
            "original_prompt": source,
            "requirements": [
                {"id": "req-002", "statement": source, "source": "user_prompt"},
            ],
            "facets": [{"id": "trade-facet", "requirements": ["req-002"],
                        "source_span": source,
                        "search_query": "Roblox trade goods and in-game credits"}],
        },
        "evidence": [],
    }
    server_actions = [
        {
            "name": "Trade",
            "server_behavior": (
                "Validate the player's trade request against server-authoritative "
                "inventory and balance, then atomically transfer items and credits "
                "between approved players; reject missing items or cancelled trades."
            ),
            "client_behavior": "",
            "observable_result": (
                "The player's inventory and credit balance change after the trade."
            ),
            "interaction": "request_response",
            "input_mode": "custom",
            "world_entities": [],
        },
        {
            "name": "Buy",
            "server_behavior": (
                "Validate player balance against server-owned item price, "
                "deduct credits and add the purchased item to inventory."
            ),
            "client_behavior": "",
            "observable_result": (
                "Player credits decrease and the new item appears in inventory."
            ),
            "interaction": "request_response",
            "input_mode": "custom",
            "world_entities": [],
        },
        {
            "name": "Sell",
            "server_behavior": (
                "Validate player ownership of an inventory item and "
                "server-owned sale price, remove the item and credit the player."
            ),
            "client_behavior": "",
            "observable_result": (
                "The item disappears from inventory and the balance increases."
            ),
            "interaction": "request_response",
            "input_mode": "custom",
            "world_entities": [],
        },
    ]

    class RecordedSmallModel:
        supports_typed_action_contract = True
        def __init__(self):
            self.calls = []
        def complete_json(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            if len(self.calls) == 1:
                return {"systems": server_actions}
            assert kwargs["json_schema"] == SCHEMA
            assert kwargs["max_tokens"] <= 500
            if len(self.calls) > 4:
                raise AssertionError("Must not regenerate full game systems")
            # The local JSON grammar exposes inactive min/max/options on TEXT
            # fields, exactly the representation that previously caused 3
            # identical failures.
            key = ("peerName", "itemName", "itemName")[len(self.calls) - 2]
            return {
                "inputs": [
                    {"id": key, "label": "Choose action target", "type": "text",
                     "min": 0, "max": 120, "options": []},
                    {"id": "quantity", "label": "Quantity", "type": "integer",
                     "min": 1, "max": 10, "options": []},
                ],
                "target": {"kind": "none", "name": ""},
                "state_changes": [
                    {"scope": "player", "key": "inventory.items", "operation": "set"},
                    {"scope": "player", "key": "wallet.credits", "operation": "set"},
                ],
            }

    model = RecordedSmallModel()
    result = RobloxDynamicArchitect(model).design(source, research, [])
    assert len(model.calls) == 4  # 1 original + 3 short typed contracts
    assert len(result["host_typed_actions"]) == 3
    assert len(result["host_actions"]) == 3
    assert research["architecture_attempts"][0]["passed"]
    assert len(research["architecture_attempts"][0]["typed_contract_attempts"]) == 3
    assert all(x["passed"] for x in research["architecture_attempts"][0]["typed_contract_attempts"])
    for spec in result["host_typed_actions"].values():
        assert all("min" not in field for field in spec["contract"]["inputs"]
                   if field["type"] == "text")
