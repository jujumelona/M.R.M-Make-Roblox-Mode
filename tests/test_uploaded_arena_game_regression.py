"""Regressions discovered from the generated coin/shop/arena Place.

Source assertions deliberately do not claim multiplayer engine execution.
"""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.gameplay_onboarding import render_game_objectives
from roblox_mod_ai.gameplay_round import render_arena_round_service


def _arena_plan():
    return SimpleNamespace(
        requested_prompt="코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나 게임을 만들어줘.",
        game_design={
            "features": {"is_coin_collect": True, "is_shop": True, "is_combat": True},
            "gameplay_contract": {"mode": "round", "units": [
                {"id": "onboarding", "action": "read instructions"},
                {"id": "collect", "action": "touch a coin"},
            ]},
        },
        modules=[SimpleNamespace(module_id="mod_arena_round")],
    )


def test_players_receive_real_arena_objective_not_the_development_prompt():
    code = render_game_objectives(_arena_plan())
    assert "코인을 모으고 장비를 구매해 아레나 경기에서 승리하세요." in code
    assert "코인을 터치해 모으세요." in code
    assert "만들어줘" not in code
    assert "GameObjective" in code and "GameActionHint" in code


def test_potion_does_not_charge_full_health_players_for_no_effect():
    code = LuauCodeGenerator()._generate_shop_service(
        SimpleNamespace(name="ShopService"), _arena_plan())
    guard = 'if itemId == "health_potion" and humanoid.Health >= humanoid.MaxHealth then'
    charge = "coinsVal.Value = EconomyRules.charge(coinsVal.Value, item.price)"
    assert guard in code
    assert code.index(guard) < code.index(charge)
    assert "Health is already full" in code


def test_match_cannot_start_without_profile_and_leaving_ring_forfeits():
    code = render_arena_round_service()
    assert 'stats:FindFirstChild("Coins")' in code
    assert "local ARENA_MARGIN = 3" in code
    assert "arena:GetBoundingBox()" in code
    assert "frame:PointToObjectSpace(root.Position)" in code
    assert "arenaFrame * CFrame.new(x, arenaSize.Y * 0.5 + 2, z)" in code
    assert "Arena geometry is missing" in code
    assert "math.abs(root.Position.X)" not in code
    assert "and inArena(player) then" in code
    assert 'player:SetAttribute("InArenaRound", false)' in code
    assert 'announce("Winner"' in code
    assert 'announce("Draw"' in code
