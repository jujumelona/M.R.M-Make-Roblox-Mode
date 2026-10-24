"""Universal stage-boundary regressions: PLAN records intent, BUILD proves code.

These tests intentionally use unrelated generic game ideas. No one example's
English/Korean verbs, shop names or source span IDs are used by production
code. The plan must not fail because an authoring or semantic verifier is
unavailable, but production still invokes that verifier before codegen.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from roblox_mod_ai.api import CompleteChatReply
from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.orchestrator import RobloxProductionOrchestrator


class UnavailableModel:
    supports_host_standard_transport = True
    supports_atomic_action_decomposition = True

    def complete_json(self, *args, **kwargs):
        raise AssertionError("Model generation must NOT run while drafting the plan")


class ResearchOnly:
    def research(self, prompt):
        return {
            "schema": "rmm/pre-design-rag-v1",
            "status": "grounded",
            "ledger": {
                "original_prompt": prompt,
                "request_sha256": hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest(),
                "requirements": [{
                    "id": "req-001",
                    "source": "user_prompt",
                    "statement": prompt,
                }],
                "facets": [{
                    "id": "intent-general",
                    "requirements": ["req-001"],
                    "source_span": prompt,
                    "implementation_key": None,
                    "implemented_by_builtin": False,
                }],
                "atomic_intents": [],
                "unmatched_requirements": [],
                "unimplemented_facets": ["intent-general"],
                "decomposition_pending": [],
                "classification_unverified": [],
                "decomposition_method": "basic",
            },
            "queries": [],
            "asset_candidates": [],
            "evidence": [],
            "provider_failures": [],
        }


@pytest.mark.parametrize("prompt", [
    "Create a procedural escape room",
    "Make a cooperative aquarium",
    "Build a tower defense experiment",
    "Create an interactive museum",
])
def test_plan_captures_all_intent_even_if_impl_model_unavailable(
    prompt, tmp_path, monkeypatch,
):
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "1")
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "0")
    monkeypatch.setattr(
        "roblox_mod_ai.planner.dynamic_design_enabled", lambda: True,
    )
    def forbidden_architect(*a, **kw):
        raise AssertionError("Do not run implementation authoring during plan")
    monkeypatch.setattr(
        "roblox_mod_ai.dynamic_architect.RobloxDynamicArchitect.design",
        forbidden_architect,
    )
    planner = RobloxGameDesignPlanner(
        router=UnavailableModel(), pre_design_research=ResearchOnly(),
        output_root=tmp_path,
    )
    authored = planner.plan(prompt)
    assert authored.proposal.requested_prompt == prompt
    assert authored.proposal.game_design["planning_phase"] == "intent_draft"
    assert authored.proposal.game_design["dynamic_design"] is None
    assert not authored.proposal.game_design[
        "implementation_blueprint"
    ]["ready_for_codegen"]
    assert not authored.proposal.game_design[
        "pre_design_research"
    ].get("architecture_attempts")
    reply = CompleteChatReply(
        message=authored.text, approval_hash=authored.calculate_hash(),
        authored_plan=authored,
    )
    assert reply.ready_to_build, (
        "A source-complete plan must be admitted into PRODUCTION, "
        "even without compiled implementation or a running GGUF model"
    )
    assert "INTENT DRAFT SAVED" in reply.message


def test_build_phase_compiles_draft_before_any_codegen(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "0")
    prompt = "Create a procedural escape room"
    plan = RobloxGameDesignPlanner(
        router=UnavailableModel(), pre_design_research=ResearchOnly(),
        output_root=tmp_path,
    ).plan(prompt)
    orchestrator = RobloxProductionOrchestrator.__new__(
        RobloxProductionOrchestrator
    )
    orchestrator.workspace_root = tmp_path
    orchestrator.router = UnavailableModel()
    invoked = []

    def compile_spy(self, requested, *, project_mode, compile_architecture=False):
        invoked.append((requested, project_mode, compile_architecture))
        return SimpleNamespace(proposal=plan.proposal)

    monkeypatch.setattr(
        "roblox_mod_ai.planner.RobloxGameDesignPlanner.plan",
        compile_spy,
    )

    class StopAtBuild(Exception):
        pass

    def stop_at_prebuild(proposal):
        raise StopAtBuild()

    monkeypatch.setattr(
        "roblox_mod_ai.orchestrator.normalize_economy_ledger",
        stop_at_prebuild,
    )
    with pytest.raises(StopAtBuild):
        orchestrator.execute(plan)
    assert invoked == [(prompt, "new_experience", True)]


def test_real_implementation_still_fails_closed_until_codegen_ready(tmp_path):
    plan = RobloxGameDesignPlanner(
        router=UnavailableModel(), pre_design_research=ResearchOnly(),
        output_root=tmp_path,
    ).plan("Create an interactive museum")
    assert not plan.proposal.game_design[
        "implementation_blueprint"
    ]["ready_for_codegen"]
    from roblox_mod_ai.implementation_blueprint import (
        audit_implementation_blueprint,
    )
    assert audit_implementation_blueprint(plan.proposal)["passed"] is False



def test_unclassified_and_unmatched_source_still_creates_a_plan(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "0")

    class IncompleteResearch(ResearchOnly):
        def research(self, prompt):
            data = super().research(prompt)
            # The model did not decompose a nuanced request. That cannot
            # prevent saving the ORIGINAL intent and starting production.
            data["ledger"]["unmatched_requirements"] = ["classification-pending"]
            data["ledger"]["decomposition_pending"] = ["chunk-pending"]
            data["ledger"]["classification_unverified"] = ["chunk-pending"]
            return data

    p = "Create a reactive weather ecosystem"
    authored = RobloxGameDesignPlanner(
        router=UnavailableModel(), pre_design_research=IncompleteResearch(),
        output_root=tmp_path,
    ).plan(p)
    reply = CompleteChatReply(
        message=authored.text, approval_hash=authored.calculate_hash(),
        authored_plan=authored,
    )
    assert reply.ready_to_build
    assert authored.proposal.requested_prompt == p
    assert authored.proposal.game_design["planning_phase"] == "intent_draft"
    assert not authored.proposal.game_design[
        "implementation_blueprint"
    ]["ready_for_codegen"]


def test_invalid_original_source_hash_is_not_a_valid_saved_draft(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RMM_ENABLE_AI_DETAILED_PLAN", "0")
    p = "Create a botanical greenhouse"
    authored = RobloxGameDesignPlanner(
        router=UnavailableModel(), pre_design_research=ResearchOnly(),
        output_root=tmp_path,
    ).plan(p)
    authored.proposal.game_design["pre_design_research"][
        "ledger"
    ]["request_sha256"] = "tampered"
    reply = CompleteChatReply(
        message=authored.text, approval_hash=authored.calculate_hash(),
        authored_plan=authored,
    )
    assert not reply.ready_to_build
