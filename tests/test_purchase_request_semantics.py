"""Uploaded proposal turned earned game currency into unsolicited Robux sales."""
import json

import pytest

from roblox_mod_ai.dynamic_architect import (
    DynamicDesignError, RobloxDynamicArchitect, _clean_model_json,
)


def _case(statement="채굴로 모은 게임 돈으로 우주선을 구매하고 업그레이드한다"):
    ledger = {"original_prompt": statement,
              "requirements": [{"id": "r-upgrade", "statement": statement}],
              "facets": [{"id": "f-upgrade", "requirements": ["r-upgrade"],
                          "source_span": statement}]}
    raw = {"modules": [{"name": "UpgradeShip", "role": "server",
                        "requirement_ids": ["r-upgrade"],
                        "facet_ids": ["f-upgrade"],
                        "behavior": "Validate the player's Robux balance through MarketplaceService before upgrading the ship."}],
           "remotes": [], "world_objects": [],
           "acceptance": [{"requirement_id": "r-upgrade",
                           "observable_result": "Server purchases and upgrades the ship."}],
           "acceptance_facets": [{"facet_id": "f-upgrade",
                                  "observable_result": "Server applies the purchased ship upgrade."}]}
    return ledger, raw


@pytest.mark.parametrize("user_request", [
    "채굴로 모은 게임 돈으로 우주선을 구매하고 업그레이드한다",
    "Buy spaceship parts with credits earned by mining",
    "Robux를 사용하지 않고 게임 돈으로 우주선 구매",
    "Upgrade ships without using Robux; use game credits",
    "Do not charge Robux for the spaceship",
    "Don't use Robux; buy with earned credits",
    "Robux isn't allowed; use earned credits",
    "Robux is not allowed; use earned credits",
    "로벅스가 아닌 게임에서 모은 돈으로 구매",
])
def test_in_game_purchases_cannot_be_replaced_with_robux(user_request):
    ledger, raw = _case(user_request)
    with pytest.raises(DynamicDesignError, match="UNREQUESTED_MONETIZATION"):
        _clean_model_json(raw, ledger, set())


def test_explicit_robux_request_is_not_blocked_as_an_in_game_purchase():
    ledger, raw = _case("Sell a ship paint game pass for Robux")
    assert _clean_model_json(raw, ledger, set())["modules"]


def test_scoped_design_retains_full_request_to_resolve_fragment_meaning(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.delenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", raising=False)
    original = "광물을 팔아서 돈을 모으고 그 돈으로 우주선 성능을 구매해서 업그레이드"
    ledger, _ = _case("그 돈으로 우주선 성능을 구매해서 업그레이드")
    ledger["original_prompt"] = original
    payloads = []
    class Model:
        def complete_json(self, prompt, **options):
            payloads.append(json.loads(prompt.split("\n")[-1]))
            return {"systems": [{
                "name": "UpgradeShip", "server_behavior":
                    "Validate the earned credit balance and apply the requested spaceship upgrade on the server.",
                "client_behavior": "Player selects a spaceship upgrade and confirms the purchase, then sees the server-confirmed result.",
                "interaction": "request_response", "input_mode": "custom",
                "observable_result": "Server applies the purchased ship upgrade.",
                "world_entities": [],
            }]}
    RobloxDynamicArchitect(Model()).design(original, {"ledger": ledger, "evidence": []}, [])
    assert payloads[0]["game_context"].get("original_request") == original
    assert payloads[0]["source_requirements"] == ledger["requirements"]


def test_architect_repairs_unrequested_monetization_using_actual_diagnostic(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.delenv("RMM_LEGACY_ARCHITECTURE_PROTOCOL", raising=False)
    ledger, raw = _case()
    calls = []
    class Model:
        def complete_json(self, prompt, **options):
            calls.append(prompt)
            if len(calls) == 2:
                assert "UNREQUESTED_MONETIZATION" in prompt
                raw["modules"][0]["behavior"] = (
                    "Validate the earned game currency balance and apply purchased ship upgrades on the server.")
            return raw
    research = {"ledger": ledger, "evidence": []}
    design = RobloxDynamicArchitect(Model()).design(ledger["original_prompt"], research, [])
    assert len(calls) == 2
    assert "earned game currency" in design["modules"][0].description
    assert [r["passed"] for r in research["architecture_attempts"]] == [False, True]


@pytest.mark.parametrize("user_prompt", [
    "광물을 거래해서 돈을 모으고 우주선을 제작",
    "Trade resources for earned credits and expand a vehicle",
    "아이템 거래 등으로 모드를 진행한다",
])
def test_vague_trading_does_not_authorize_new_peer_to_peer_economy(user_prompt):
    from roblox_mod_ai.request_semantics import request_semantic_errors
    model = {"systems": [{
        "name": "Player-to-Player Trading",
        "server_behavior": (
            "Validate both players' inventories and exchange their items. "
            "Persist both players' balances after a counteroffer is accepted."
        ),
    }]}
    errors = request_semantic_errors(model, user_prompt)
    assert any("UNREQUESTED_PEER_TRADE" in error for error in errors)


@pytest.mark.parametrize("user_prompt", [
    "플레이어끼리 아이템 거래하고 교환할 수 있게",
    "Allow players to trade items with each other",
    "Players trade parts and earned credits",
])
def test_explicit_peer_to_peer_trades_are_still_allowed(user_prompt):
    from roblox_mod_ai.request_semantics import request_semantic_errors
    model = {"systems": [{
        "name": "Player-to-Player Trading",
        "server_behavior": "The server validates both players' inventories."
    }]}
    assert not any("UNREQUESTED_PEER_TRADE" in e
                   for e in request_semantic_errors(model, user_prompt))


def test_scoped_architect_repairs_unsolicited_peer_trade_without_replanning_all(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    prompt = "Mine resources and trade them for earned credits"
    ledger = {
        "original_prompt": prompt,
        "requirements": [
            {"id": "req-001", "statement": "trade them for earned credits",
             "source": "user_prompt"}],
        "facets": [
            {"id": "intent-resource-exchange", "requirements": ["req-001"],
             "source_span": "trade them for earned credits",
             "search_query": "Roblox server resource sale catalog"}],
    }

    class MiniModel:
        def __init__(self):
            self.calls = []
        def complete_json(self, query, **_options):
            self.calls.append(query)
            if len(self.calls) == 1:
                return {"systems": [{
                    "name": "Player-to-Player Trading",
                    "server_behavior": (
                        "The server validates both players' inventories and "
                        "sends a counteroffer before persisting both profiles."
                    ),
                    "client_behavior": (
                        "The player offers another player's inventory items "
                        "and awaits the peer trade decision."
                    ),
                    "interaction": "request_response", "input_mode": "custom",
                    "observable_result": "Both player inventories change on acceptance.",
                    "world_entities": [],
                }]}
            assert "UNREQUESTED_PEER_TRADE" in query
            return {"systems": [{
                "name": "ResourceExchange",
                "server_behavior": (
                    "The server validates the selected catalog item, the user's "
                    "owned resource quantity, and a server-fixed sale price, "
                    "debits the resource and credits earned game currency."
                ),
                "client_behavior": (
                    "The player selects a resource to sell to the game market "
                    "and sees the new server-confirmed coin balance."
                ),
                "interaction": "request_response", "input_mode": "custom",
                "observable_result": "Sold resources decrease and earned credits increase.",
                "world_entities": [],
            }]}
    model = MiniModel()
    research = {"ledger": ledger, "evidence": []}
    result = RobloxDynamicArchitect(model).design(prompt, research, [])
    assert len(model.calls) == 2
    assert len(result["modules"]) == 2
    assert all("both players" not in m.description.casefold()
               for m in result["modules"])
    assert [x["passed"] for x in research["architecture_attempts"]] == [False, True]
