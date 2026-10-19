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
                "client_behavior": "", "interaction": "none",
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
