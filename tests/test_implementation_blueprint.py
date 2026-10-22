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
    assert all(row["acceptance"].strip() for row in blueprint["requirements"])
    assert any(row["id"] == "req-003" and "ArenaRoundService" in row["owners"]
               for row in blueprint["requirements"])
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


def test_dynamic_blueprint_survives_host_normalization_and_topological_sort():
    from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec, RobloxService, ModuleKind
    from roblox_mod_ai.server_modules import normalize_dynamic_server_modules
    shared = RobloxModuleSpec(
        module_id="mod_network_bridge", name="NetworkRemotes",
        kind=ModuleKind.SHARED_MODULE, file_path="src/shared/NetworkRemotes.luau",
        roblox_service=RobloxService.REPLICATED_STORAGE)
    profile = RobloxModuleSpec(
        module_id="mod_player_data", name="PlayerDataManager",
        kind=ModuleKind.DATA_STORE, file_path="src/server/PlayerDataManager.server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE)
    game = RobloxModuleSpec(
        module_id="dyn_pets", name="CustomPetHatching",
        kind=ModuleKind.SERVER_SCRIPT, file_path="src/server/CustomPetHatching.server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE)
    dynamic = {
        "module_facets": {"dyn_pets": ["pets"]},
        "acceptance_facets": {"pets": "Server hatches pet from egg"},
        "module_requirements": {"dyn_pets": ["req-001"]},
        "acceptance": {"req-001": "Server hatches pet from egg"},
    }
    proposal = RobloxProposal(
        requested_prompt="펫 부화", game_title="PetTest", description="fixture",
        modules=[shared, profile, game],
        game_design={
            "features": {}, "dynamic_design": dynamic, "storage_backend": "builtin",
            "pre_design_research": {"ledger": {"requirements": [
                {"id": "req-001", "statement": "펫 부화"}],
                "facets": [{"id": "pets", "requirements": ["req-001"]}],
                "unimplemented_facets": [], "unmatched_requirements": [],
                "decomposition_pending": []}},
        },
    )
    assert normalize_dynamic_server_modules(proposal)
    names = {m.name for m in proposal.modules}
    assert "RMMServerBootstrap" in names
    assert next(m for m in proposal.modules if m.name == "PlayerDataManager").file_path.endswith(".luau")
    proposal.game_design["implementation_blueprint"] = build_implementation_blueprint(proposal)
    assert audit_implementation_blueprint(proposal)["passed"] is True
    # Module ordering changes during resolve(), without changing owners.
    proposal.modules.reverse()
    assert audit_implementation_blueprint(proposal)["passed"] is True
    # Idempotence is required: production cannot silently add another bootstrap.
    assert not normalize_dynamic_server_modules(proposal)
    assert audit_implementation_blueprint(proposal)["passed"] is True
    proposal.modules = [m for m in proposal.modules if m.name != "CustomPetHatching"]
    assert not audit_implementation_blueprint(proposal)["passed"]


def test_model_unclassified_user_requirements_block_codegen_even_with_fake_owners():
    """A source-only placeholder is not semantically verified gameplay."""
    proposal = _proposal({
        "is_coin_collect": True, "is_shop": True,
        "is_combat": True, "is_leaderboard": True,
    })
    ledger = proposal.game_design["pre_design_research"]["ledger"]
    ledger["classification_unverified"] = ["chunk-008"]
    blueprint = build_implementation_blueprint(proposal)
    assert not blueprint["ready_for_codegen"]
    assert any("unclassified_gameplay_requirements" in issue
               for issue in blueprint["blocking_issues"])
    # A persisted old planner receipt claiming everything implemented is stale.
    proposal.game_design["implementation_blueprint"] = dict(
        blueprint, blocking_issues=[], ready_for_codegen=True)
    assert not audit_implementation_blueprint(proposal)["passed"]
    # The same source requirement can pass only after the missing classification
    # is explicitly resolved rather than being assigned a fictional owner.
    ledger["classification_unverified"] = []
    verified = build_implementation_blueprint(proposal)
    assert verified["ready_for_codegen"] is True


def test_source_npc_combat_and_colony_require_real_owner_behavior():
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService, RobloxProposal
    enemy = RobloxModuleSpec(
        module_id="dyn_enemy", name="CombatEncounterServer",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/CombatEncounterServer.luau",
        description="The server validates hits against other players and "
                    "reduces the target player's health for PvP.",
    )
    colony = RobloxModuleSpec(
        module_id="dyn_colony", name="SettlementServer",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/SettlementServer.luau",
        description="The server updates the map display and toggles a colony menu.",
    )
    ledger = {
        "requirements": [
            {"id": "req-001", "statement": "Fight alien enemies"},
            {"id": "req-002", "statement": "Colonize a planet"},
        ],
        "facets": [], "unimplemented_facets": [], "unmatched_requirements": [],
        "decomposition_pending": [], "atomic_intents": [
            {"facet_id": "enemy", "source_span": "Fight alien enemies",
             "intent": "Players damage alien NPC enemies",
             "english_query": "Roblox hostile enemy humanoid damage"},
            {"facet_id": "colony", "source_span": "Colonize a planet",
             "intent": "Found a persistent colony settlement",
             "english_query": "Roblox DataStore colony settlement"},
        ],
    }
    dynamic = {
        "module_facets": {"dyn_enemy": ["enemy"], "dyn_colony": ["colony"]},
        "module_requirements": {"dyn_enemy": ["req-001"], "dyn_colony": ["req-002"]},
        "acceptance_facets": {
            "enemy": "Target player health is reduced.",
            "colony": "Open the colony screen.",
        },
        "acceptance": {"req-001": "Target player health is reduced.",
                       "req-002": "Open the colony screen."},
    }
    plan = RobloxProposal(
        requested_prompt="Fight alien enemies and colonize a planet",
        game_title="Exploration", description="Two independent requested mechanics",
        modules=[enemy, colony], game_design={
            "features": {}, "dynamic_design": dynamic,
            "pre_design_research": {"ledger": ledger},
        })
    blueprint = build_implementation_blueprint(plan)
    assert not blueprint["ready_for_codegen"]
    assert any("NPC_COMBAT_DROPPED" in e for e in blueprint["blocking_issues"])
    assert any("SETTLEMENT_DROPPED" in e for e in blueprint["blocking_issues"])
    enemy.description = "The server validates attacks on hostile alien NPC enemies"
    colony.description = ("The server validates colonization of a planet, "
                          "persists the player's settlement and marks it occupied.")
    dynamic["acceptance_facets"]["enemy"] = "Confirmed hits damage alien enemies"
    dynamic["acceptance_facets"]["colony"] = "Colonized planet has persistent settlement"
    dynamic["acceptance"]["req-001"] = "Confirmed hit damages hostile alien NPC enemies"
    dynamic["acceptance"]["req-002"] = "Persistent settlement exists on colonized planet"
    fixed = build_implementation_blueprint(plan)
    assert fixed["ready_for_codegen"] is True



def test_client_promised_launch_cannot_substitute_for_missing_server_spaceflight():
    """Regression from proposal 48 req-007: ship upgrade approved as launch."""
    from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService, RobloxProposal
    owner = RobloxModuleSpec(
        module_id="dyn_ship_feature", name="ShipFeatureServer",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/ShipFeatureServer.luau",
        description=(
            "The server validates the player's coins, deducts a purchase cost "
            "and applies a new ship speed upgrade to owned ship performance."
        ),
    )
    source = "그렇게해서 우주로 나갈수있고"
    ledger = {
        "requirements": [{"id": "req-007", "statement": source}],
        "atomic_intents": [{
            "facet_id": "intent-depart", "requirement_id": "req-007",
            "source_span": source,
            "intent": "Launch the spacecraft into space",
            "english_query": "Roblox server space launch travel",
        }],
        "facets": [{"id": "intent-depart", "requirements": ["req-007"]}],
        "unimplemented_facets": [], "unmatched_requirements": [],
        "decomposition_pending": [], "classification_unverified": [],
    }
    dynamic = {
        "module_facets": {"dyn_ship_feature": ["intent-depart"]},
        "module_requirements": {"dyn_ship_feature": ["req-007"]},
        "acceptance_facets": {
            "intent-depart": "The player sees their spaceship launch into space"
        },
        "acceptance": {
            "req-007": "The player sees their spaceship launch into space"
        },
    }
    plan = RobloxProposal(
        requested_prompt=source, game_title="GeneralGame", description="Launch",
        modules=[owner], game_design={
            "features": {}, "dynamic_design": dynamic,
            "pre_design_research": {"ledger": ledger},
        },
    )
    bad = build_implementation_blueprint(plan)
    assert not bad["ready_for_codegen"]
    assert any("SPACE_TRAVEL_DROPPED" in x
               for x in bad["blocking_issues"])
    owner.description = (
        "The server verifies owned ship parts and fuel, launches the "
        "spacecraft into space, updates its authoritative flight state "
        "and moves the player into orbit."
    )
    good = build_implementation_blueprint(plan)
    assert good["ready_for_codegen"]
