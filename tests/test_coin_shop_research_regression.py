"""Regressions from the 2026-10-19 coin/shop/arena failure ZIP.

A model's suggested API searches are research hints, not new game systems.
"""
from __future__ import annotations

import copy
import hashlib

import pytest

from roblox_mod_ai.request_contract import implementation_facets
from roblox_mod_ai.host_architecture import HostArchitectureError, expand_semantic_facet
from roblox_mod_ai.planner import RobloxGameDesignPlanner


PROMPT = "코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나 게임을 만들어줘."


def _search_only_ledger():
    clauses = ["코인 수집", "상점 시스템", "리더보드가 포함된 검투 아레나 게임을 만들어줘."]
    requirements = [
        {"id": f"req-{i:03d}", "statement": text, "source": "user_prompt"}
        for i, text in enumerate(clauses, 1)
    ]
    facets = [
        {"id": "coins", "requirements": ["req-001"], "implementation_key": "is_coin_collect"},
        {"id": "shop", "requirements": ["req-002"], "implementation_key": "is_shop"},
        {"id": "combat", "requirements": ["req-003"], "implementation_key": "is_combat"},
        {"id": "leaderboard", "requirements": ["req-003"], "implementation_key": "is_leaderboard"},
        # These three are exact search suggestions from the failure proposal.
        {"id": "semantic-data", "requirements": ["req-001"], "model_query_only": True,
         "search_query": "Roblox DataStore2 collection save load coins"},
        {"id": "semantic-store", "requirements": ["req-002"], "model_query_only": True,
         "search_query": "Roblox MarketplaceItemService BuyAsync SellAsync catalog"},
        {"id": "semantic-rank", "requirements": ["req-003"], "model_query_only": True,
         "search_query": "Roblox Leaderstats leaderboard ReplicatedStorage"},
    ]
    return {
        "original_prompt": PROMPT, "requirements": requirements,
        "facets": facets, "decomposition_method": "not_required",
        "decomposition_pending": [], "unimplemented_facets": [],
        "unmatched_requirements": [],
        "request_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
    }


def test_search_expansion_never_produces_duplicate_gameplay_modules():
    ledger = _search_only_ledger()
    assert [f["id"] for f in implementation_facets(ledger)] == [
        "coins", "shop", "combat", "leaderboard",
    ]


def test_old_persisted_semantic_query_entries_remain_evidence_only():
    ledger = _search_only_ledger()
    ledger["decomposition_method"] = "source_anchored_model"
    ledger["atomic_intents"] = []
    assert [f["id"] for f in implementation_facets(ledger)] == [
        "coins", "shop", "combat", "leaderboard",
    ]


def test_default_planner_uses_real_shop_coin_combat_templates_not_search_suggestions(monkeypatch):
    monkeypatch.delenv("RMM_ENABLE_DYNAMIC_DESIGN", raising=False)
    class Research:
        def research(self, prompt):
            assert prompt == PROMPT
            return {"ledger": copy.deepcopy(_search_only_ledger()),
                    "queries": [], "evidence": [], "asset_candidates": [],
                    "reuse_candidates": [], "provider_failures": [],
                    "status": "grounded"}
    proposal = RobloxGameDesignPlanner(pre_design_research=Research()).plan(PROMPT).proposal
    assert proposal.game_design["dynamic_design"] is None
    names = {m.name for m in proposal.modules}
    assert {"ShopService", "ShopController", "CoinCollector",
            "CombatSystem", "CombatController"}.issubset(names)
    assert not any(name.startswith("MarketplaceItemServiceBuy") for name in names)
    # The corrected route must also materialize the arena, coin pickup
    # objects, merchant counter and the correct shop RPC in the Rojo tree.
    from roblox_mod_ai.project_generator import RobloxProjectGenerator
    tree = RobloxProjectGenerator(".").generate_rojo_project_json(proposal)["tree"]
    world = tree["Workspace"]
    assert {"Coins", "ShopStalls", "CombatArena"} <= set(world)
    assert "ShopPurchase" in tree["ReplicatedStorage"]["Remotes"]


def test_explicitly_unvalidated_combat_must_fail_before_luau_generation():
    behavior = (
        "The server receives an attack request and applies damage to a target "
        "without validating the request, then records a winner in the duel."
    )
    raw = {"systems": [{
        "name": "Arena Combat",
        "server_behavior": behavior,
        "client_behavior": "Show damage, arena health and the completed duel result.",
        "interaction": "request_response", "input_mode": "custom",
        "observable_result": "A target loses health and the result appears on screen.",
        "world_entities": ["Arena"],
    }]}
    with pytest.raises(HostArchitectureError, match="bypasses action validation"):
        expand_semantic_facet(
            raw, facet_id="combat", requirement_ids=["req-003"],
            source_requirements=[{"id": "req-003",
                                  "statement": "리더보드가 포함된 검투 아레나 게임을 만들어줘."}],
            reserved_modules=set(), reserved_remotes=set(), reserved_objects=set(),
        )


def test_reject_invalid_profile_and_marketplace_apis_from_failed_shop_log():
    from roblox_mod_ai.luau_api_sanity import invalid_luau_apis

    broken = """
    local stock = services.PlayerDataManager.GetState(nil, "ShopStock")
    MarketplaceItemService.BuyAsync(player, "sword")
    """
    failures = invalid_luau_apis(broken)
    assert any("authenticated Player" in diagnostic for diagnostic in failures)
    assert any("in-game currency" in diagnostic for diagnostic in failures)
    valid = """
    local profile = services.PlayerDataManager.GetState(player, "ShopStock")
    if profile then profile.owned = true end
    """
    assert invalid_luau_apis(valid) == []
