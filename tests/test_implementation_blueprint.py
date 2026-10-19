"""Regression coverage for MRM's requirement-to-implementation planning boundary.

These checks intentionally do not claim Roblox Studio execution.
"""
from __future__ import annotations

from types import SimpleNamespace

from roblox_mod_ai.implementation_blueprint import (
    audit_implementation_blueprint,
    build_implementation_blueprint,
)


def _proposal(features: dict[str, bool], *, omit: set[str] | None = None):
    omit = omit or set()
    all_modules = [
        "NetworkRemotes", "PlayerDataManager", "ShopService", "ShopController",
        "CoinCollector", "CombatSystem", "CombatController",
        "ArenaRoundService", "RoundController", "HUDController",
    ]
    modules = [
        SimpleNamespace(name=name, module_id="mod_" + name,
                        file_path="src/server/" + name + ".server.luau")
        for name in all_modules if name not in omit
    ]
    ledger = {
        "requirements": [
            {"id": "req-001", "statement": "collect coins"},
            {"id": "req-002", "statement": "buy items"},
            {"id": "req-003", "statement": "combat with leaderboard"},
        ],
        "facets": [
            {"requirements": ["req-001"], "implementation_key": "is_coin_collect"},
            {"requirements": ["req-002"], "implementation_key": "is_shop"},
            {"requirements": ["req-003"], "implementation_key": "is_combat"},
            {"requirements": ["req-003"], "implementation_key": "is_leaderboard"},
        ],
        "decomposition_pending": [], "unimplemented_facets": [],
        "unmatched_requirements": [],
    }
    return SimpleNamespace(
        requested_prompt="collect coins, buy items, combat with leaderboard",
        modules=modules,
        game_design={"features": features,
                     "pre_design_research": {"ledger": ledger}, "dynamic_design": None},
    )


def test_composite_game_has_cross_system_acceptance_and_studio_scenarios():
    proposal = _proposal({
        "is_coin_collect": True, "is_shop": True,
        "is_combat": True, "is_leaderboard": True,
    })
    blueprint = build_implementation_blueprint(proposal)
    assert blueprint["ready_for_codegen"] is True
    assert {i["id"] for i in blueprint["integration_contracts"]} >= {
        "coin_to_purchase", "coin_to_leaderboard", "purchase_to_combat",
        "combat_to_leaderboard", "arena_lifecycle",
    }
    assert len(blueprint["studio_scenarios"]) >= 10
    assert all(s["status"] == "not_run" for s in blueprint["studio_scenarios"])
    proposal.game_design["implementation_blueprint"] = blueprint
    assert audit_implementation_blueprint(proposal)["passed"] is True


def test_missing_module_fails_closed():
    proposal = _proposal({
        "is_coin_collect": True, "is_shop": True,
        "is_combat": True, "is_leaderboard": True,
    }, omit={"CombatSystem"})
    blueprint = build_implementation_blueprint(proposal)
    assert blueprint["ready_for_codegen"] is False
    assert any("CombatSystem" in problem for problem in blueprint["blocking_issues"])
    proposal.game_design["implementation_blueprint"] = blueprint
    assert audit_implementation_blueprint(proposal)["passed"] is False


def test_stale_blueprint_fails_after_module_revision():
    proposal = _proposal({
        "is_coin_collect": True, "is_shop": True,
        "is_combat": True, "is_leaderboard": True,
    })
    proposal.game_design["implementation_blueprint"] = build_implementation_blueprint(proposal)
    proposal.modules = [m for m in proposal.modules if m.name != "ShopService"]
    report = audit_implementation_blueprint(proposal)
    assert not report["passed"]
    assert "mechanics mismatches current requirement/module graph" in report["errors"]


def test_unowned_requirement_cannot_be_silently_marked_complete():
    proposal = _proposal({"is_coin_collect": True, "is_shop": True})
    blueprint = build_implementation_blueprint(proposal)
    assert any("unowned requirement req-003" in x for x in blueprint["blocking_issues"])
    assert blueprint["ready_for_codegen"] is False


def test_runtime_success_cannot_be_claimed_by_serialized_plan():
    proposal = _proposal({
        "is_coin_collect": True, "is_shop": True,
        "is_combat": True, "is_leaderboard": True,
    })
    blueprint = build_implementation_blueprint(proposal)
    blueprint["studio_verified"] = True
    proposal.game_design["implementation_blueprint"] = blueprint
    assert "Static plan cannot mark Studio gameplay as verified" in (
        audit_implementation_blueprint(proposal)["errors"]
    )
