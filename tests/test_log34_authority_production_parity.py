"""Regression: 34th log's planner preview passed, production rejected in 88ms.

A model service requiring a preexisting owned planet/catalog must be audited
across all model-owned route strategies, and the preview must execute the
same source-level normalizations without mutating the original proposal.
"""
from copy import deepcopy

from roblox_mod_ai.authority_architecture_repair import (
    inspect_authority_design,
)
from roblox_mod_ai.model_action_authority import unproven_model_actions
from test_log32_model_authority import _log32_design


def _complete_test_design():
    plan, _scope = _log32_design()
    design = deepcopy(plan.game_design["dynamic_design"])
    design["modules"] = deepcopy(plan.modules)
    design["remotes"] = {route: "RemoteFunction"
                         for route in design["host_actions"]}
    design["module_remotes"] = {
        module.module_id: [
            route for route, row in design["host_actions"].items()
            if row["service"] == module.name
        ] for module in plan.modules
    }
    design["module_world_objects"] = {
        key: list(value)
        for key, value in design.get("module_world_objects", {}).items()
    }
    design["world_objects"] = [
        {"name": "AlienEntitiesSpawnedOnT77D3DB11", "class": "Part",
         "position": [0, 2, 0], "size": [4, 4, 4]},
        {"name": "SpecialMineralDeposit77D3DB31", "class": "Part",
         "position": [12, 2, 0], "size": [4, 4, 4]},
    ]
    return design


def test_34_missing_authority_cannot_evade_audit_via_early_strategy():
    plan, scope = _log32_design()
    for row in scope["modules"]:
        if row["name"].startswith("ShipPerformance"):
            row["strategy"] = "bounded_server_action"
        elif row["name"].startswith("Colonize"):
            row["strategy"] = "whole_file_model_legacy"
    gaps = unproven_model_actions(plan, scope)
    assert {gap["module"] for gap in gaps} == {
        "ColonizePlanet77D3DB2Server",
        "ShipPerformanceUpgrade213E1D3Server",
    }


def test_34_host_owned_compiled_action_remains_exempt():
    plan, scope = _log32_design()
    for row in scope["modules"]:
        row["strategy"] = "host_verified_typed_effect"
    assert unproven_model_actions(plan, scope) == []


def test_34_source_preview_normalizes_without_mutating_authored_design():
    design = _complete_test_design()
    original = deepcopy(design)
    issues = inspect_authority_design(
        design, [], requested_prompt=(
            "Build a ship from mined resources, buy upgrades and colonize a planet"
        ))
    assert {row["module"] for row in issues} == {
        "ShipPerformanceUpgrade213E1D3Server",
        "ColonizePlanet77D3DB2Server",
    }, issues
    assert design == original, (
        "Never mutate canonical source contracts while running preflight"
    )


def test_34_complete_correction_requires_effect_provenance_not_just_state_words():
    design = _complete_test_design()
    remote = "ShipPerformanceUpgrade213E1D3Action"
    spec = design["host_typed_actions"][remote]
    spec["transport_only"] = False
    spec["contract"]["state_changes"] = [{
        "scope": "player", "key": "RMMShipState.Speed",
        "operation": "increment",
    }]
    # A declaration alone is not enough: the compiler must own the effect
    # or the world target must be independently declared.
    plan, scope = _log32_design()
    plan.game_design["dynamic_design"] = design
    assert any(row["remote"] == remote
               for row in unproven_model_actions(plan, scope))
