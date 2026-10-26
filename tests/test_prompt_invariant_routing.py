"""Generic regression tests: raw wording cannot select different Luau code paths.

These tests use two arbitrary prompts rather than any particular game genre.
Only the typed/validated architecture is permitted to determine routing.
"""
from types import SimpleNamespace

import pytest

import roblox_mod_ai.generation_scope as scope_module


def _proposal(prompt: str, *, dynamic: bool = True):
    return SimpleNamespace(
        requested_prompt=prompt,
        game_design={"dynamic_design": {"schema": "example/typed-contract"} if dynamic else {}},
    )


def _report(strategy: str):
    return {
        "modules": [{"module_id": "dyn_action_x", "strategy": strategy},
                    {"module_id": "mod_network_bridge", "strategy": "builtin_source"}],
    }


def test_rephrasing_does_not_change_structured_route(monkeypatch):
    monkeypatch.setattr(
        scope_module, "generation_scope",
        lambda proposal: _report("host_atomic_effect"),
    )
    scope_module.assert_prompt_invariant_routing(
        _proposal("Grow a garden then harvest."),
        original_scope=_report("host_atomic_effect"),
    )
    scope_module.assert_prompt_invariant_routing(
        _proposal("플레이어가 농작물을 수확하는 게임"),
        original_scope=_report("host_atomic_effect"),
    )


def test_raw_prompt_conditional_route_is_rejected(monkeypatch):
    def prompt_sensitive(proposal):
        route = ("host_verified_template"
                 if "garden" in proposal.requested_prompt else "bounded_server_action")
        return _report(route)

    monkeypatch.setattr(scope_module, "generation_scope", prompt_sensitive)
    with pytest.raises(ValueError, match="PROMPT_DEPENDENT_GENERATOR_ROUTE"):
        scope_module.assert_prompt_invariant_routing(
            _proposal("garden simulation"),
            original_scope=_report("host_verified_template"),
        )


def test_non_dynamic_builtin_plan_does_not_require_shadow_check(monkeypatch):
    def forbidden(_proposal):
        raise AssertionError("not called")

    monkeypatch.setattr(scope_module, "generation_scope", forbidden)
    scope_module.assert_prompt_invariant_routing(_proposal("Simple stock obby", dynamic=False))


def test_dynamic_module_roster_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(scope_module, "generation_scope",
                        lambda proposal: {"modules": []})
    with pytest.raises(ValueError, match="PROMPT_DEPENDENT_GENERATOR_ROUTE"):
        scope_module.assert_prompt_invariant_routing(
            _proposal("anything"),
            original_scope=_report("host_atomic_effect"),
        )
