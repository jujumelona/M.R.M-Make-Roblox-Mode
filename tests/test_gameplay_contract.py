"""Lifecycle requirements must be bound to generated source and engine scenarios.

A plan is not accepted merely because it says 'victory' or lists a module.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.gameplay_contract import (
    SCHEMA, arena_round_requested, build_gameplay_contract,
    validate_gameplay_contract,
)
from roblox_mod_ai.gameplay_round import (
    render_arena_round_controller, render_arena_round_service,
)


def _plan(prompt="코인 수집과 검투 아레나", features=None, mode="new_experience",
          dynamic=None):
    f = {"is_coin_collect": True, "is_shop": False, "is_combat": True,
         "is_obby": False, "is_tycoon": False, "is_simulator": False}
    if features is not None:
        f.update(features)
    modules = [
        SimpleNamespace(module_id="mod_player_data", name="PlayerDataManager",
                        file_path="src/server/PlayerDataManager.server.luau"),
        SimpleNamespace(module_id="mod_coin_collector", name="CoinCollector",
                        file_path="src/server/CoinCollector.server.luau"),
        SimpleNamespace(module_id="mod_combat_core", name="CombatSystem",
                        file_path="src/server/CombatSystem.server.luau"),
    ]
    if arena_round_requested(prompt, f, dynamic=bool(dynamic),
                             addon=mode == "existing_experience_addon"):
        modules += [
            SimpleNamespace(module_id="mod_arena_round", name="ArenaRoundService",
                            file_path="src/server/ArenaRoundService.server.luau"),
            SimpleNamespace(module_id="mod_arena_round_controller", name="RoundController",
                            file_path="src/client/RoundController.client.luau"),
        ]
    result = SimpleNamespace(requested_prompt=prompt, modules=modules,
            game_design={"features": f, "dynamic_design": dynamic,
                         "project_mode": mode})
    result.game_design["gameplay_contract"] = build_gameplay_contract(result)
    return result


def _checks(plan, tmp_path):
    return {v["id"]: v["passed"] for v in
            validate_gameplay_contract(plan, tmp_path)}


def test_round_and_replay_contract_only_for_explicit_arena():
    arena = _plan()
    contract = arena.game_design["gameplay_contract"]
    assert contract["schema"] == SCHEMA
    assert contract["mode"] == "round"
    assert contract["completion_kind"] == "victory_defeat_draw"
    assert "insufficient_opponents" in contract["exceptions"]
    assert "RoundController" in {u["owner"] for u in contract["units"]}
    ordinary_combat = _plan("적을 때리는 게임")
    assert ordinary_combat.game_design["gameplay_contract"]["mode"] == "open_ended"
    addon = _plan("검투 아레나 모드", mode="existing_experience_addon")
    assert addon.game_design["gameplay_contract"]["mode"] == "addon"
    assert "ArenaRoundService" not in {m.name for m in addon.modules}


def test_missing_round_source_is_hard_error(tmp_path):
    plan = _plan()
    checks = _checks(plan, tmp_path)
    assert checks["lifecycle.present"]
    assert checks["lifecycle.reachable"]
    assert checks["lifecycle.round_modules"]
    assert not checks["lifecycle.source.round"]
    assert not checks["lifecycle.source.round_feedback"]


def test_tampered_plan_cannot_claim_success(tmp_path):
    plan = _plan()
    plan.game_design["gameplay_contract"]["graph"] = [
        {"from": "entry", "to": "outcome", "trigger": "skip gameplay"}
    ]
    checks = _checks(plan, tmp_path)
    assert checks["lifecycle.binding"] is False
    assert checks["lifecycle.reachable"] is False
    plan.game_design.pop("gameplay_contract")
    assert _checks(plan, tmp_path)["lifecycle.present"] is False


def test_custom_genre_uses_authored_facet_ownership_without_fabricated_boss():
    plan = _plan("펫 부화", features={"is_coin_collect": False, "is_combat": False},
                 dynamic={"acceptance_facets": {"pet.hatch": "Egg proximity verified and pet granted"},
                          "module_facets": {"dyn_pet": ["pet.hatch"]}})
    plan.modules += [SimpleNamespace(module_id="dyn_pet", name="PetHatching",
                                     file_path="src/server/PetHatching.luau")]
    plan.game_design["gameplay_contract"] = build_gameplay_contract(plan)
    assert plan.game_design["gameplay_contract"]["mode"] == "custom_activity"
    assert plan.game_design["gameplay_contract"]["completion_kind"] == "observable_activity_outcome"
    assert any(u["owner"] == "PetHatching"
               for u in plan.game_design["gameplay_contract"]["units"])


def test_finite_narrative_ending_cannot_be_satisfied_by_a_coin_counter(tmp_path):
    plan = _plan("보스를 잡은 다음 스토리 엔딩이 나오는 전투",
                 features={"is_coin_collect": False})
    assert plan.game_design["gameplay_contract"]["finite_ending_requested"]
    assert not _checks(plan, tmp_path)["lifecycle.finite"]


def test_round_sources_handle_solo_wait_death_departure_timeout_and_result():
    server = render_arena_round_service()
    client = render_arena_round_controller()
    for marker in ("MIN_PLAYERS = 2", "Humanoid", "Died:Connect",
                   "player.Parent == Players", "ROUND_DURATION",
                   'announce("Draw"', 'announce("Winner"',
                   "VICTORY_REWARD", "LoadCharacterAsync", "RoundStatus"):
        assert marker in server
    for marker in ("OnClientEvent", "ScreenGui", "TextLabel", "RoundStatus"):
        assert marker in client


def test_stage_finish_is_distinct_from_repetitive_progression():
    plan = _plan("50단계 용암 점프맵", features={"is_coin_collect": False,
                 "is_combat": False, "is_obby": True})
    plan.modules += [
        SimpleNamespace(module_id="mod_obby_service", name="ObbyService",
                        file_path="src/server/ObbyService.server.luau"),
        SimpleNamespace(module_id="mod_obby_controller", name="ObbyController",
                        file_path="src/client/ObbyController.client.luau"),
    ]
    plan.game_design["gameplay_contract"] = build_gameplay_contract(plan)
    assert plan.game_design["gameplay_contract"]["completion_kind"] == "final_checkpoint"


def test_dynamic_lifecycle_rejects_strict_only_or_commented_mutation(tmp_path):
    """The previous dynamic unit accepted any source containing --!strict."""
    plan = _plan("펫 부화", features={"is_coin_collect": False, "is_combat": False},
                 dynamic={"acceptance_facets": {"pet.hatch": "Pet egg hatches"},
                          "module_facets": {"dyn_pet": ["pet.hatch"]}})
    plan.modules += [SimpleNamespace(module_id="dyn_pet", name="PetHatching",
                                     file_path="src/server/PetHatching.luau")]
    plan.game_design["gameplay_contract"] = build_gameplay_contract(plan)
    file = tmp_path / "src/server/PetHatching.luau"
    file.parent.mkdir(parents=True)
    for text in (
        "--!strict\nreturn {}\n",
        '--!strict\n-- pet:SetAttribute("Hatched", true)\nreturn {}\n',
        '--!strict\nprint("pet:SetAttribute(\\\"Hatched\\\", true)")\nreturn {}\n',
    ):
        file.write_text(text, encoding="utf-8")
        assert _checks(plan, tmp_path)["lifecycle.source.custom.pet.hatch"] is False
    file.write_text(
        '--!strict\nlocal Service = {}\n'
        'function Service.handleAction(player, services)\n'
        '  player:SetAttribute("PetHatched", true)\n'
        'end\nreturn Service\n',
        encoding="utf-8")
    assert _checks(plan, tmp_path)["lifecycle.source.custom.pet.hatch"] is True
    assert not plan.game_design["gameplay_contract"]["engine_playtested"]


def test_custom_host_composition_checks_real_helper_effect_not_delegation_only(tmp_path):
    plan = _plan("Mine and exchange resources",
                 features={"is_coin_collect": False, "is_combat": False},
                 dynamic={
                     "acceptance_facets": {"resource.exchange": "Resources change"},
                     "module_facets": {"dyn_resource": ["resource.exchange"]},
                     "host_actions": {"ResourceAction": {
                         "service": "ResourceServer", "kind": "RemoteFunction",
                     }},
                 })
    plan.modules += [SimpleNamespace(
        module_id="dyn_resource", name="ResourceServer",
        file_path="src/server/ResourceServer.luau",
    )]
    plan.game_design["gameplay_contract"] = build_gameplay_contract(plan)
    saved = tmp_path / "src/server/ResourceServer.luau"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(
        '--!strict\nlocal Service = {}\n'
        'local function performResourceAction(player)\n'
        '  player:SetAttribute("ResourcesEarned", 1)\n'
        'end\n'
        'function Service.handleAction(player, services, ...)\n'
        '  return performResourceAction(player)\n'
        'end\nreturn Service\n', encoding="utf-8")
    assert _checks(plan, tmp_path)["lifecycle.source.custom.resource.exchange"] is True
    saved.write_text(
        '--!strict\nlocal Service = {}\n'
        'function Service.handleAction(player, services, ...)\n'
        '  return true\nend\nreturn Service\n', encoding="utf-8")
    assert _checks(plan, tmp_path)["lifecycle.source.custom.resource.exchange"] is False
