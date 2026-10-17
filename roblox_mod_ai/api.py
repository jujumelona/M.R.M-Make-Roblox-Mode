"""Public conversational API for R.M.M (Roblox Mod & Experience AI)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .model_router import ModelRouter
from .orchestrator import RobloxPipelineResult, RobloxProductionOrchestrator
from .planner import RobloxGameDesignPlanner
from .spec import RobloxProposal


@dataclass(frozen=True)
class CompleteChatReply:
    """User-facing plan reply containing rendered message and executable plan state."""

    message: str
    approval_hash: str = field(repr=False)
    authored_plan: RobloxAuthoredPlan = field(repr=False)

    @property
    def ready_to_build(self) -> bool:
        research = self.authored_plan.proposal.game_design.get("pre_design_research", {})
        ledger = research.get("ledger", {})
        return (not ledger.get("unimplemented_facets")
                and not ledger.get("unmatched_requirements")
                and (any(self.authored_plan.proposal.game_design.get("features", {}).values())
                     or bool(self.authored_plan.proposal.game_design.get("dynamic_design"))))


class CompleteRobloxAISession:
    """Conversational session for Roblox experience planning, revision, and production."""

    def __init__(
        self,
        output_root: str | Path = "rmm-output",
        model_profile: str = "t4_local",
        fast_mode: bool = False,
    ) -> None:
        self.output_root = Path(output_root).resolve()
        self.model_profile = model_profile
        self.fast_mode = fast_mode

        self.router = ModelRouter(profile=model_profile)
        self.planner = RobloxGameDesignPlanner(router=self.router)
        self.orchestrator = RobloxProductionOrchestrator(
            workspace_root=self.output_root,
            router=self.router,
        )

        self.authored_plan: RobloxAuthoredPlan | None = None
        self.brief: str = ""

    def plan(self, prompt: str, *, project_mode: str = "new_experience") -> CompleteChatReply:
        """Create a new game design plan from a natural-language description."""
        self.reset()
        self.brief = prompt
        plan = self.planner.plan(prompt, project_mode=project_mode)
        self.authored_plan = plan
        self.save_plan()

        return CompleteChatReply(
            message=plan.text,
            approval_hash=plan.calculate_hash(),
            authored_plan=plan,
        )

    def revise(self, feedback: str) -> CompleteChatReply:
        """Revise the existing plan based on feedback, keeping unaffected subsystems."""
        if self.authored_plan is None:
            raise ValueError("No active plan exists to revise. Call session.plan(...) first.")

        plan = self.planner.revise(self.authored_plan, feedback)
        self.authored_plan = plan
        self.save_plan()

        return CompleteChatReply(
            message=plan.text,
            approval_hash=plan.calculate_hash(),
            authored_plan=plan,
        )

    def build(
        self,
        candidate: CompleteChatReply | RobloxAuthoredPlan | RobloxProposal | None = None,
        run_name: str = "production-run",
        source_only: bool = False,
    ) -> RobloxPipelineResult:
        """Executes Luau generation, analysis, playtest, and builds .rbxlx + project ZIP."""
        if isinstance(candidate, CompleteChatReply):
            target = candidate.authored_plan
        elif isinstance(candidate, (RobloxAuthoredPlan, RobloxProposal)):
            target = candidate
        elif candidate is None:
            if self.authored_plan is None:
                raise ValueError("No plan available to build. Provide a plan or call session.plan(...) first.")
            target = self.authored_plan
        else:
            raise TypeError("Candidate must be CompleteChatReply, RobloxAuthoredPlan, or None.")

        return self.orchestrator.execute(
            candidate=target,
            run_name=run_name,
            source_only=source_only,
        )

    def save_plan(self, target_path: str | Path | None = None) -> Path:
        """Persist the authored plan and checkpoints to a JSON file."""
        if self.authored_plan is None:
            raise ValueError("No plan to save.")
        dest = Path(target_path) if target_path else self.output_root / "proposal.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(self.authored_plan.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return dest

    def load_plan(self, source_path: str | Path | None = None) -> CompleteChatReply:
        """Load a saved plan JSON from disk and restore session state."""
        src = Path(source_path) if source_path else self.output_root / "proposal.json"
        if not src.is_file():
            raise FileNotFoundError(f"Plan file not found: {src}")

        data = json.loads(src.read_text(encoding="utf-8"))
        plan = RobloxAuthoredPlan.from_dict(data)
        self.authored_plan = plan
        self.brief = plan.requested_prompt

        return CompleteChatReply(
            message=plan.text,
            approval_hash=plan.calculate_hash(),
            authored_plan=plan,
        )

    def reset(self) -> None:
        """Reset session prompt and plan."""
        self.brief = ""
        self.authored_plan = None


# Public alias for seamless compatibility with M.M.M callers
CompleteModAISession = CompleteRobloxAISession
CompleteSession = CompleteRobloxAISession
