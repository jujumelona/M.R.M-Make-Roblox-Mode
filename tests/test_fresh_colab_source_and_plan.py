"""Prevent accidental use of wrong, stale linecache source in Colab research."""
from types import SimpleNamespace
from unittest.mock import patch

from roblox_mod_ai.pre_design_research import _fresh_generator_method_source
from roblox_mod_ai.api import CompleteChatReply


def test_local_research_uses_actual_ast_method_body():
    for method in ("_generate_shop_service", "_generate_coin_collector",
                   "_generate_combat_service", "_generate_shop_controller"):
        body = _fresh_generator_method_source(method)
        assert body is not None
        assert f"def {method}(" in body
        assert "return " in body
    assert "coinsFolder" in _fresh_generator_method_source("_generate_coin_collector")
    assert "purchaseFunction" in _fresh_generator_method_source("_generate_shop_service")
    assert _fresh_generator_method_source("_method_not_present") is None


def test_stale_loaded_plan_is_not_ready_for_build():
    proposal = SimpleNamespace(
        requested_prompt="make arena with shop", modules=[],
        game_design={
            "features": {"is_combat": True}, "dynamic_design": None,
            "project_mode": "new_experience",
            "pre_design_research": {"schema": "rmm/pre-design-rag-v1",
                                    "ledger": {"requirements": [{"id": "req-1"}]}},
        },
    )
    plan = SimpleNamespace(proposal=proposal)
    reply = CompleteChatReply(message="stale plan", approval_hash="ignored", authored_plan=plan)
    with patch("roblox_mod_ai.api.ledger_complete", return_value=True):
        assert reply.ready_to_build is False
