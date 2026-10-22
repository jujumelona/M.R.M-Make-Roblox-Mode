"""Public conversational API for R.M.M (Roblox Mod & Experience AI)."""

from __future__ import annotations

import json
import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .model_router import ModelRouter
from .orchestrator import RobloxPipelineResult, RobloxProductionOrchestrator
from .planner import RobloxGameDesignPlanner
from .request_contract import ledger_complete
from .implementation_blueprint import audit_implementation_blueprint
from .detailed_plan import audit_detailed_plan
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
        proposal = self.authored_plan.proposal
        is_complete = (ledger_complete(proposal.requested_prompt, ledger)
                       and (any(proposal.game_design.get("features", {}).values())
                            or bool(proposal.game_design.get("dynamic_design"))))
        # Imported stale plans may have nonempty modules but blank acceptance.
        # Replan them before codegen instead of producing a second broken ZIP.
        # All production modes, including Existing Experience add-ons and
        # imported plans with older research schemas, need the SAME audited
        # implementation ownership and detailed state/effect contract.
        # Otherwise a valid-looking source ledger can bypass the blueprint
        # and resume code from an incompatible plan revision.
        # Some test/connector research providers supply a source ledger but
        # omit an optional schema marker. Do not accept an unknown *declared*
        # schema, yet allow schema-free in-memory research only when BOTH
        # current implementation and detailed-plan audits pass below.
        # Old persisted plans cannot bypass either content audit.
        if research.get("schema") not in (None, "rmm/pre-design-rag-v1"):
            return False
        if proposal.game_design.get("project_mode", "new_experience") not in (
                "new_experience", "existing_experience_addon"):
            return False
        return bool(is_complete
                    and audit_implementation_blueprint(proposal)["passed"]
                    and audit_detailed_plan(proposal)["passed"])


class CompleteRobloxAISession:
    """Conversational session for Roblox experience planning, revision, and production."""

    @staticmethod
    def _is_colab_runtime() -> bool:
        return ("google.colab" in sys.modules or Path("/content").is_dir())

    def __init__(
        self,
        output_root: str | Path = "rmm-output",
        model_profile: str = "t4_local",
        fast_mode: bool = False,
    ) -> None:
        self.output_root = Path(output_root).resolve()
        self.model_profile = model_profile
        self.fast_mode = fast_mode
        self.model_runtime = None
        # Older Colab notebooks import the latest package but do not start their
        # model in cell 4. Initialize the real backend before ModelRouter takes
        # a snapshot of the endpoint. This is idempotent for a ready endpoint.
        if (not fast_mode and model_profile != "fast_test"
                and self._is_colab_runtime()):
            from .colab_model_runtime import ensure_model_runtime
            self.model_runtime = ensure_model_runtime(
                profile=model_profile,
                cache_root=self.output_root.parent / "rmm-model",
                in_colab=True,
            )

        self.router = ModelRouter(profile=model_profile)
        self.planner = RobloxGameDesignPlanner(
            router=self.router, output_root=self.output_root)
        self.orchestrator = RobloxProductionOrchestrator(
            workspace_root=self.output_root,
            router=self.router,
        )

        self.authored_plan: RobloxAuthoredPlan | None = None
        self.brief: str = ""

    def plan(self, prompt: str, *, project_mode: str = "new_experience",
             force_replan: bool = False) -> CompleteChatReply:
        """Reuse an approved identical plan by default; never restart its graph.

        The old API discarded the approved module/route graph on each retry
        of the same prompt, producing an unrelated set of 18-24 modules
        instead of resuming the fixed program. `force_replan=True` explicitly
        requests a fresh architecture. Invalid legacy plans never auto-resume.
        """
        saved = self.output_root / "proposal.json"
        if saved.is_file() and not force_replan:
            try:
                candidate = RobloxAuthoredPlan.from_dict(
                    json.loads(saved.read_text(encoding="utf-8"))
                )
                proposal = candidate.proposal
                if (candidate.requested_prompt == prompt
                        and proposal.requested_prompt == prompt
                        and proposal.game_design.get(
                            "project_mode", "new_experience") == project_mode):
                    previous = CompleteChatReply(
                        message=candidate.text,
                        approval_hash=candidate.calculate_hash(),
                        authored_plan=candidate,
                    )
                    if previous.ready_to_build:
                        self.reset()
                        self.brief = prompt
                        self.authored_plan = candidate
                        return previous
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                # Corrupt, obsolete and incomplete plans must not be reused.
                pass
        self.reset()
        self.brief = prompt
        plan = self.planner.plan(prompt, project_mode=project_mode)
        self.authored_plan = plan
        self.save_plan()
        reply = CompleteChatReply(
            message=plan.text,
            approval_hash=plan.calculate_hash(),
            authored_plan=plan,
        )
        if not reply.ready_to_build:
            self.export_plan_failure()
        return reply

    def revise(self, feedback: str) -> CompleteChatReply:
        """Revise the existing plan based on feedback, keeping unaffected subsystems."""
        if self.authored_plan is None:
            raise ValueError("No active plan exists to revise. Call session.plan(...) first.")

        plan = self.planner.revise(self.authored_plan, feedback)
        self.authored_plan = plan
        self.save_plan()
        reply = CompleteChatReply(
            message=plan.text,
            approval_hash=plan.calculate_hash(),
            authored_plan=plan,
        )
        if not reply.ready_to_build:
            self.export_plan_failure()
        return reply

    def build(
        self,
        candidate: CompleteChatReply | RobloxAuthoredPlan | RobloxProposal | None = None,
        run_name: str = "production-run",
        source_only: bool = False,
    ) -> RobloxPipelineResult:
        """Build Luau, validate the source and package offline Studio artifacts.

        A verified engine gameplay test is a separate, optional local step.
        """
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

    def export_plan_failure(self) -> Path:
        """Persist the actual planning diagnostics instead of ending in traceback.

        Includes the source-anchored request ledger, model/provider failures and
        model design repair observations. No gameplay success is implied.
        """
        if self.authored_plan is None:
            raise ValueError("No plan failure available")
        research = self.authored_plan.proposal.game_design.get("pre_design_research", {})
        self.output_root.mkdir(parents=True, exist_ok=True)
        report = self.output_root / "plan_failure_report.json"
        report.write_text(json.dumps({
            "schema": "rmm/plan-failure-v1",
            "success": False,
            "requested_prompt": self.authored_plan.requested_prompt,
            "provider_failures": research.get("provider_failures", []),
            "architecture_attempts": research.get("architecture_attempts", []),
            "missing_requirements": research.get("ledger", {}).get(
                "unmatched_requirements", []),
            "unimplemented_facets": research.get("ledger", {}).get(
                "unimplemented_facets", []),
            "decomposition_pending": research.get("ledger", {}).get(
                "decomposition_pending", []),
            "request_ledger": research.get("ledger", {}),
            "note": "Planning incomplete; source generated? no; Roblox engine run? no",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        bundle = self.output_root / "plan_failure_logs.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in (report, self.output_root / "proposal.json"):
                if path.is_file():
                    archive.write(path, path.name)
        print("[RMM agent] planning failure report: " + str(bundle), flush=True)
        return bundle

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
