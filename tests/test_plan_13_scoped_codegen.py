"""Regression for production failure_logs (13): small-coder JSON/body and state ABI.

The parser rejects leaked tool-call tags, never trusts a client-supplied
Player as the action actor, and repairs an exact verified GetState ABI call
rather than weakening the dependency validator.
"""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.host_service_codegen import normalize_verified_server_body
from roblox_mod_ai.model_router import ModelRouter
from roblox_mod_ai.semantic_preservation import (
    source_intent_conflicts, source_outcome_conflicts,
)


DATA_SERVICE = """
local PlayerDataManager = {}
function PlayerDataManager.GetState(player, namespace)
    return {}
end
return PlayerDataManager
"""
PEER = SimpleNamespace(
    name="PlayerDataManager",
    file_path="src/server/PlayerDataManager.luau",
    code=DATA_SERVICE,
)
PROPOSAL = SimpleNamespace(modules=[PEER])
SOURCE = "우주로 나가면 다른행성의 특수 광물"


def test_production_coder_prefers_grammar_constrained_action_json():
    assert ModelRouter().supports_scoped_json_body is True


@pytest.mark.parametrize("fragment", [
    "</parameter><function=exec>print('ok')</function></tool_call>",
    "<tool_call><function=exec>",
    "<parameter>not Lua</parameter>",
])
def test_scoped_action_rejects_control_plane_output(fragment):
    with pytest.raises(ValueError, match="MODEL_PROTOCOL_CONTAMINATION"):
        normalize_verified_server_body(
            "player:SetAttribute('Mode', 'Space')\n" + fragment,
            PROPOSAL,
        )


def test_host_player_identity_cannot_be_shadowed_by_client_selection():
    # An exact known typo is removed so the host's trusted player parameter
    # remains in scope. Any arbitrary alias still fails closed.
    code = normalize_verified_server_body(
        "local player = args[1]\nplayer:SetAttribute('Mode','Space')",
        PROPOSAL,
    )
    assert "local player = args[1]" not in code
    assert "player:SetAttribute('Mode','Space')" in code
    with pytest.raises(ValueError, match="HOST_IDENTITY_SHADOWED"):
        normalize_verified_server_body(
            "local player = args.selection\nplayer:SetAttribute('Mode','Space')",
            PROPOSAL,
        )


def test_exact_dot_export_repairs_only_verified_dependency_call():
    source = (
        "local state = services.PlayerDataManager:GetState(player, 'State')\n"
        "if not state then return false end\n"
        "state.Mode = 'Space'"
    )
    fixed = normalize_verified_server_body(source, PROPOSAL)
    assert "services.PlayerDataManager.GetState(player, 'State')" in fixed
    assert ":GetState(" not in fixed
    assert "state.Mode = 'Space'" in fixed
    assert normalize_verified_server_body(source, SimpleNamespace(modules=[])) == source


def test_unbound_player_data_manager_rejected_instead_of_guessing_registry():
    with pytest.raises(ValueError, match="DEPENDENCY_API_UNBOUND"):
        normalize_verified_server_body(
            "local state = PlayerDataManager.GetState(player, 'State')",
            PROPOSAL,
        )


def test_plan_33_spacecraft_arrival_does_not_implement_planet_minerals():
    source_server = (
        "Server validates the craft and relocates the owned spacecraft "
        "to a destination planet with all passengers aboard."
    )
    outcome = "The spaceship visibly arrives at the other planet."
    assert any("PLANETARY_MINERAL_MECHANIC_DROPPED" in x
               for x in source_intent_conflicts(SOURCE, source_server))
    assert source_outcome_conflicts(SOURCE, outcome)
    assert source_intent_conflicts(
        SOURCE,
        "Server validates a special mineral deposit and mines special "
        "ore from an alien planet into player inventory.",
    ) == []
    assert source_outcome_conflicts(
        SOURCE,
        "The newly collected special ore is in the player's inventory.",
    ) == []


def test_plan_33_missing_crew_and_ship_upgrades_not_ready():
    source = "무기 선원 우주선 성능을 거래 구매 등으로"
    weapon_only = (
        "Server validates available currency, purchases a weapon performance "
        "upgrade, and then increases the weapon length."
    )
    issues = source_intent_conflicts(source, weapon_only)
    assert any("SUBSYSTEM_DROPPED: crew" in item for item in issues)
    assert any("SUBSYSTEM_DROPPED: ship" in item for item in issues)
    implemented = (
        "Server purchases the player's weapon upgrade and increases weapon "
        "damage. Server recruits a crew member with earned currency and "
        "assigns the crew to the ship. Server upgrades the spacecraft "
        "engine performance and deducts the verified purchase cost."
    )
    assert source_intent_conflicts(source, implemented) == []


def test_production_context_chunk_cannot_become_standalone_space_mode_button():
    from roblox_mod_ai.request_contract import validate_model_behaviors
    from roblox_mod_ai.source_decomposition import source_chunks

    clause = (
        "우주모드 인데 자원파밍 돈모으기 거래 등으로 "
        "우주선을 부위마다 만들어서 만들수있고"
    )
    fake_standalone = [
        {
            "source_span": "우주모드 인데",
            "intent": "Enable a separate SpaceMode through an F5 menu.",
            "english_query": "Roblox F5 SpaceMode toggle",
        },
        {
            "source_span": "자원파밍 돈모으기 거래 등으로",
            "intent": "Harvest resources and earn cash by trading",
            "english_query": "Roblox resource mining and trading",
        },
        {
            "source_span": "우주선을 부위마다 만들어서 만들수있고",
            "intent": "Build a spacecraft by attaching parts",
            "english_query": "Roblox modular craft builder",
        },
    ]
    assert validate_model_behaviors(clause, fake_standalone) is False
    chunks = source_chunks(clause)
    assert len(chunks) >= 1
    assert all(piece != "우주모드 인데" for piece in chunks)
    assert " ".join(chunks) == clause
