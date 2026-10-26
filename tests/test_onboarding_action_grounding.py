"""No internal intent identifiers or development instructions in player HUD."""
from types import SimpleNamespace

from roblox_mod_ai.gameplay_onboarding import render_game_objectives


def test_player_sees_actual_first_mining_action_not_internal_intent():
    plan = SimpleNamespace(
        requested_prompt="자원파밍과 거래로 우주선을 조립하고 우주로 가기",
        game_design={"gameplay_contract": {
            "mode": "open_ended",
            "units": [{"id": "onboarding", "action": "read briefing"},
                      {"id": "intent", "action":
                       "execute requested intent-38a0790701"}],
        }},
        modules=[SimpleNamespace(name="ResourceGather4533281Server",
                                 file_path="src/server/ResourceGather4533281Server.luau")],
    )
    src = render_game_objectives(plan)
    assert "자원 노드 근처로 이동해 채굴 버튼을 눌러 자원을 모으세요." in src
    assert "execute requested intent" not in src


def test_player_hud_does_not_invent_mining_when_no_mining_owner():
    plan = SimpleNamespace(
        requested_prompt="미지의 우주 게임",
        game_design={"gameplay_contract": {
            "mode": "open_ended",
            "units": [{"id": "intro", "action": "NOT RUN"}],
        }},
        modules=[],
    )
    src = render_game_objectives(plan)
    assert "맵을 탐색하세요." in src
    assert "NOT RUN" not in src
