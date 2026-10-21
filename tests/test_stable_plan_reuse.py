"""An identical approved user request must not randomly redesign the game.

New architecture requires explicit force_replan; obsolete or incomplete
architectures must not sneak into production under the reuse policy.
"""
from roblox_mod_ai.api import CompleteChatReply, CompleteRobloxAISession
from roblox_mod_ai.authored_plan import RobloxAuthoredPlan
from roblox_mod_ai.spec import RobloxProposal


class CountingPlanner:
    def __init__(self):
        self.calls = []

    def plan(self, prompt, *, project_mode="new_experience"):
        self.calls.append((prompt, project_mode))
        proposal = RobloxProposal(
            requested_prompt=prompt,
            game_title="StableGame",
            description="Audited mock proposal",
            game_design={"project_mode": project_mode},
            modules=[],
        )
        return RobloxAuthoredPlan(
            requested_prompt=prompt,
            text="design number " + str(len(self.calls)),
            proposal=proposal,
        )


def test_same_prompt_reuses_approved_architecture_and_force_replan(tmp_path, monkeypatch):
    # Mock ONLY plan acceptance: the production code still verifies the full
    # request ledger, integration blueprint, and detailed plan separately.
    monkeypatch.setattr(CompleteChatReply, "ready_to_build", property(lambda _: True))
    session = CompleteRobloxAISession(
        output_root=tmp_path, model_profile="fast_test", fast_mode=True)
    counter = CountingPlanner()
    session.planner = counter

    initial = session.plan("Mine resources and build a spaceship")
    assert len(counter.calls) == 1
    session2 = CompleteRobloxAISession(
        output_root=tmp_path, model_profile="fast_test", fast_mode=True)
    session2.planner = counter
    resumed = session2.plan("Mine resources and build a spaceship")
    assert resumed.approval_hash == initial.approval_hash
    assert resumed.message == initial.message
    assert len(counter.calls) == 1

    newly_requested = session2.plan(
        "Mine resources and build a spaceship", force_replan=True)
    assert newly_requested.message == "design number 2"
    assert len(counter.calls) == 2
    changed = session2.plan("Mine resources and construct a space station")
    assert changed.message == "design number 3"
    assert len(counter.calls) == 3


def test_unapproved_saved_plan_never_auto_resumes(tmp_path, monkeypatch):
    state = {"ready": False}
    monkeypatch.setattr(
        CompleteChatReply, "ready_to_build",
        property(lambda _: state["ready"]),
    )
    session = CompleteRobloxAISession(
        output_root=tmp_path, model_profile="fast_test", fast_mode=True)
    planner = CountingPlanner()
    session.planner = planner
    session.plan("Custom unimplemented experience")
    state["ready"] = False
    session.plan("Custom unimplemented experience")
    assert len(planner.calls) == 2
