"""Production orchestrator coordinating code generation, analysis, playtest, and build with WorkGraph."""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .code_generator import LuauCodeGenerator
from .dynamic_repair import repair_tool_diagnostics, repair_static_failures
from .agent_loop import RobloxCodeRepairAgent, LuauGenerationError
from .agent_trajectory import AgentTrajectory
from .quality_gates import acceptance_obligations, make_artifact_manifest
from .request_traceability import build_request_traceability
from .local_studio import install_local_studio_checks
from .verification_selector import make_verification_report
from .source_review import review_generated_sources
from .source_repair_cycle import run_source_repair_cycle
from .gameplay_contract import make_studio_playtest_scenarios
from .rbxlx_inspector import inspect_compiled_place
import hashlib
import zipfile
from .luau_analyzer import LuauAnalysisReport, LuauStaticAnalyzer
from .model_router import ModelRouter
from .playtest_runner import PlaytestReport, RobloxPlaytestRunner, TestCaseResult
from .project_generator import RobloxProjectGenerator
from .roblox_toolchain import RobloxToolchainManager
from .spec import RobloxProposal, ModuleKind
from .host_architecture import requires_player_ingress
from .work_graph import RobloxWorkGraph, TaskStage, WorkReceipt, StageReceipt


@dataclass
class RobloxPipelineResult:
    """Final build output artifacts, verification reports, and stage receipts."""

    success: bool
    game_title: str
    rbxlx_path: str
    project_zip_path: str
    project_dir: str
    analysis_report: LuauAnalysisReport
    playtest_report: PlaytestReport
    duration_ms: float
    work_receipt: WorkReceipt
    build_mode: str
    generated_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            # Source/package completion is not proof of a successful Roblox playtest.
            "build_ready": bool(self.metadata.get("build_ready", False)),
            "release_status": self.metadata.get("release_status", "unverified"),
            "game_title": self.game_title,
            "rbxlx_path": self.rbxlx_path,
            "project_zip_path": self.project_zip_path,
            "project_dir": self.project_dir,
            "build_mode": self.build_mode,
            "analysis": self.analysis_report.to_dict(),
            "playtest": self.playtest_report.to_dict(),
            "duration_ms": self.duration_ms,
            "work_receipt": self.work_receipt.to_dict(),
            "metadata": self.metadata,
        }


from .economy_core import normalize_economy_ledger
from .server_modules import normalize_dynamic_server_modules
from .host_mining_contract import ensure_mining_world_contract
from .host_gameplay import render_host_gameplay
from .module_generation_gate import (
    ModuleGenerationContractError, require_generated_module_contract,
    generated_module_errors,
)
from .scaffold_policy import is_host_scaffolded_source
from .generation_scope import generation_scope
from .implementation_blueprint import audit_implementation_blueprint

def explicit_stage_verdict(details: Any) -> bool:
    """No missing/contradictory stage return can be treated as success."""
    if not isinstance(details, dict):
        raise ValueError("STAGE_RESULT_MUST_BE_OBJECT")
    verdicts = [details[key] for key in ("success", "passed")
                if key in details]
    if (not verdicts or any(type(value) is not bool for value in verdicts)
            or len(set(verdicts)) != 1):
        raise ValueError(
            "STAGE_RESULT_EXPLICIT_BOOL_REQUIRED: success/passed "
            "must exist, be boolean, and agree")
    return verdicts[0]


class RobloxProductionOrchestrator:
    """Coordinates end-to-end production of a Roblox experience via topological work graph."""

    def __init__(
        self,
        workspace_root: str | Path = "rmm-output",
        router: ModelRouter | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.router = router or ModelRouter()
        self.code_generator = LuauCodeGenerator(self.router)
        self.project_generator = RobloxProjectGenerator(self.workspace_root)
        self.analyzer = LuauStaticAnalyzer()
        self.playtest_runner = RobloxPlaytestRunner()
        self.toolchain = RobloxToolchainManager()
        self.work_graph = RobloxWorkGraph(self.workspace_root)

    def execute(
        self,
        candidate: RobloxProposal | RobloxAuthoredPlan,
        run_name: str = "build-output",
        source_only: bool = False,
    ) -> RobloxPipelineResult:
        """Build with fail-closed tool results and honest engine verification.

        No built-in XML fallback; Rojo project is the only place source of truth.
        """
        start = time.perf_counter()
        proposal = candidate.proposal if isinstance(candidate, RobloxAuthoredPlan) else candidate
        # Phase boundary: planning captures original user requirements and
        # NEVER requires the 9B model to prove server code semantics. When
        # actual production is requested, compile executable architecture
        # using the implementation validators before any Luau generation.
        # A failed implementation contract remains a production error, not a
        # retroactive failure to CREATE the user's source-owned plan.
        if proposal.game_design.get("planning_phase") == "intent_draft":
            from .planner import RobloxGameDesignPlanner
            compiled = RobloxGameDesignPlanner(
                router=self.router, output_root=self.workspace_root,
            ).plan(
                proposal.requested_prompt,
                project_mode=proposal.game_design.get(
                    "project_mode", "new_experience"),
                compile_architecture=True,
            )
            proposal = compiled.proposal
        normalize_economy_ledger(proposal)
        normalize_dynamic_server_modules(proposal)
        # Mining with no declared physical target is not a safe player action.
        # Host supplies the missing requested resource world prerequisite
        # BEFORE any Luau is generated, so the model is not asked to invent
        # targets, yields or a parallel economy API.
        world_materializations = ensure_mining_world_contract(proposal)
        addon_mode = proposal.game_design.get("project_mode") == "existing_experience_addon"
        from .artifact_path_safety import safe_segment, validate_project_layout
        run_component = safe_segment(run_name, field="run_name")
        title_component = safe_segment(proposal.game_title, field="game_title")
        output_dir = self.workspace_root / run_component / title_component
        # Check the full resolved tree before creating it; a symlink or
        # imported relative path must never redirect writes outside the
        # designated workspace. This includes cached source and test paths.
        anchor = self.workspace_root.resolve()
        if not output_dir.resolve().is_relative_to(anchor):
            raise ValueError("RMM_GAME_OUTPUT_ESCAPES_WORKSPACE")
        validate_project_layout(output_dir, proposal.modules, proposal.tests)
        output_dir.mkdir(parents=True, exist_ok=True)
        trajectory = AgentTrajectory(output_dir)
        for item in world_materializations:
            trajectory.record("preflight", "materialize_mining_world_contract", item, passed=True)
        receipt = WorkReceipt(task_id=f"rmm_{proposal.game_title}_{int(time.time())}", overall_success=False)
        errors: list[str] = []
        tool_results: dict[str, dict] = {}
        acceptance: dict = {"passed": False, "checks": []}
        runtime: dict = {"passed": False, "executed": False, "status": "not_run",
                         "reason": "Roblox Studio has not tested this build"}
        analysis_report = LuauAnalysisReport(passed=False)
        playtest_report = PlaytestReport(
            passed=False, total_tests=0, passed_count=0, failed_count=0, duration_ms=0,
            results=[],  # No fabricated failure: an engine test was not requested or run.
        )
        rbxlx_path = ""
        zip_path = ""
        build_mode = "source_only" if source_only else "rojo_required"

        def stage(stage_id: TaskStage, callback) -> bool:
            began = time.perf_counter()
            try:
                details = callback()
                # Every pipeline stage must return a REAL explicit verdict.
                # The old default True marked a missing/malformed callback
                # result as successful and advanced straight to packaging.
                passed = explicit_stage_verdict(details)
                receipt.stages.append(StageReceipt(stage=stage_id, success=passed,
                    duration_ms=(time.perf_counter() - began) * 1000, details=details,
                    errors=[] if passed else [str(details.get("error", "stage not verified"))]))
                if not passed:
                    errors.append(f"{stage_id.value}: {details.get('error', 'not verified')}")
                trajectory.record(stage_id.value, 'validate stage', details, passed=passed)
                return passed
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                receipt.stages.append(StageReceipt(stage=stage_id, success=False,
                    duration_ms=(time.perf_counter() - began) * 1000, errors=[msg]))
                errors.append(f"{stage_id.value}: {msg}")
                trajectory.record(stage_id.value, "exception", {
                    "error": msg, "traceback": traceback.format_exc()
                }, passed=False)
                return False

        def resolve():
            nonlocal acceptance
            # Uploaded authored plans can carry a stale, optimistic blueprint.
            # Recompute its requirement audit BEFORE model work or checkpoints.
            # A source span retained without a semantic classification is not
            # proof that the right mechanic (NPC vs player, settlement vs UI)
            # exists. Do not burn 9B retries on an invalid architecture.
            if "implementation_blueprint" in proposal.game_design:
                audited = audit_implementation_blueprint(proposal)
                tool_results["implementation_blueprint_audit"] = audited
                if not audited["passed"]:
                    # Preserve the planning diagnostics on the final receipt.
                    # Earlier eager rejection correctly avoided wasting model
                    # time but returned no acceptance check IDs, making other
                    # tools believe the plan had never been audited.
                    from .request_contract import ledger_complete
                    ledger = (proposal.game_design.get("pre_design_research") or {}).get("ledger") or {}
                    covered = ledger_complete(proposal.requested_prompt, ledger)
                    semantically_classified = not ledger.get("classification_unverified")
                    acceptance = {"passed": False, "checks": [
                        {"id": "planning.request_coverage",
                         "passed": bool(covered and semantically_classified),
                         "detail": "Original requirements and classified actions: " +
                                   str(bool(covered and semantically_classified))},
                        {"id": "planning.integration_blueprint",
                         "passed": False,
                         "detail": "; ".join(audited["errors"][:16])},
                    ]}
                    return {
                        "success": False,
                        "error": "INCOMPLETE_GAMEPLAY_ARCHITECTURE: " +
                                 "; ".join(audited["errors"][:16]),
                        "requires_replanning": True,
                        "architecture_errors": audited["errors"],
                    }
            proposal.modules = self.work_graph.topological_sort_modules(proposal.modules)
            design = proposal.game_design.get("dynamic_design") or {}
            host_actions = design.get("host_actions") or {}
            world_actions = design.get("host_world_actions") or {}
            # Imported authored plans can predate the current plan validator.
            # Refuse to code player mechanics with no Remote/ProximityPrompt
            # or declared service caller; a valid script would be unreachable.
            orphaned = [
                m.name for m in proposal.modules
                if m.module_id.startswith("dyn_")
                and m.kind == ModuleKind.SERVER_MODULE
                and requires_player_ingress(m.name, m.description)
                and not any(isinstance(v, dict) and v.get("service") == m.name
                            for v in host_actions.values())
                and not any(isinstance(v, dict) and v.get("service") == m.name
                            for v in world_actions.values())
                and not any(
                    m.module_id in other.depends_on
                    for other in proposal.modules
                    if other.module_id not in (
                        m.module_id, "mod_dynamic_server_bootstrap")
                )
            ]
            if orphaned:
                return {
                    "success": False,
                    "error": "UNROUTED_PLAYER_GAMEPLAY: authored plan has " +
                             str(len(orphaned)) +
                             " player-driven server services without any host "
                             "input route or declared caller. Replan the "
                             "gameplay architecture instead of regenerating "
                             "unreachable Luau: " + ", ".join(orphaned[:12]),
                    "unrouted_modules": orphaned,
                    "requires_replanning": True,
                }
            # A plan that builds a vehicle in one service but launches an
            # unrelated placeholder world Part cannot become valid through
            # ANY Luau-body retry. Catch the cross-stage identity breach
            # before paying for bounded-model coding. This is an IMPLEMENTATION
            # contract error, not a failure to preserve the original plan.
            from .vehicle_identity_binding import (
                bind_verified_vehicle_providers, bind_vehicle_actors,
            )
            from .vehicle_identity_contract import vehicle_identity_errors
            # Prefer the verified runtime Model provider over a guessed static
            # Craft Part; fall back to unique scene-root binding only when a
            # first-party provider cannot be proven.
            actor_bindings = bind_verified_vehicle_providers(proposal)
            actor_bindings.extend(bind_vehicle_actors(proposal))
            if actor_bindings:
                tool_results["vehicle_identity_bindings"] = actor_bindings
                for record in actor_bindings:
                    trajectory.record("preflight", "bind_existing_vehicle_root",
                                      record, passed=True)
            actor_errors = vehicle_identity_errors(proposal)
            if actor_errors:
                tool_results["vehicle_identity_errors"] = actor_errors
                return {
                    "success": False,
                    "error": "UNBOUND_VEHICLE_IDENTITY: " + "; ".join(actor_errors),
                    "requires_contract_revision": True,
                    "requires_replanning": True,
                    "implementation_blocker": "cross_system_physical_actor",
                }

            # Materialize the actual orbit landing Part only AFTER the host
            # has resolved the builder->launched-vehicle identity. Without
            # this preflight, the local coder invents an undeclared Orbit
            # world object even when a complete host departure exists.
            from .vehicle_identity_binding import materialize_source_linked_space_arrivals
            arrivals = materialize_source_linked_space_arrivals(proposal)
            if arrivals:
                tool_results["host_arrival_materializations"] = arrivals
                for record in arrivals:
                    trajectory.record("preflight", "materialize_source_linked_space_arrival",
                                      record, passed=True)
            # First-party declarative compilers own BOTH their server ABI
            # and client payload. A generic typed-only stub must not override
            # a fully matched implementation; rebase such stubs as a pair
            # before spending any tokens on model-generated Luau.
            from .host_protocol_handoff import rebase_complete_host_protocols
            source_scope = generation_scope(proposal, for_protocol_handoff=True)
            handoffs = rebase_complete_host_protocols(proposal, source_scope)
            if handoffs:
                tool_results["host_protocol_handovers"] = handoffs
            scope = generation_scope(proposal)
            tool_results["generation_scope"] = scope
            trajectory.record("preflight", "generation scope", {
                "counts": scope["counts"],
                "whole_file_model_risk_modules": scope["whole_file_model_risk_modules"],
                "model_action_risk_modules": scope["model_action_risk_modules"],
            }, passed=True)
            return {"success": True,
                    "module_order": [m.name for m in proposal.modules],
                    "generation_scope": scope["counts"],
                    "whole_file_model_risk_modules":
                        scope["whole_file_model_risk_modules"],
                    "model_action_risk_modules":
                        scope["model_action_risk_modules"]}

        checkpoint_file = output_dir / "generation_checkpoint.json"
        # Input-only checkpoints previously survived changes to coder prompts,
        # server bootstrap contracts and recovery policy. This resumed stale
        # broken code after every fix. Tie all resumed modules to the actual
        # source of the generation pipeline; changed implementation invalidates
        # checkpoints without deleting the user's prior run evidence.
        # Every package Python module may define a host adapter, validator,
        # state ABI, routing policy, or a model-coding prompt. A hand-maintained
        # file list missed newly added adapters and allowed old checkpoints to
        # survive source changes. Fingerprint the actual installed codebase,
        # deterministically and without relying on an optional git checkout.
        from .generation_provenance import generation_source_digests
        component_fingerprints = generation_source_digests(
            Path(__file__).resolve().parent
        )
        # Report the exact Colab clone revision and generation source digests
        # in failure ZIPs so a stale interpreter is identifiable on the next run.
        tool_results["source_provenance"] = {
            "executed": True,
            "git_commit": os.environ.get("RMM_SOURCE_COMMIT", ""),
            "orchestrator_disk_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "code_generator_disk_sha256": component_fingerprints["code_generator.py"],
            "module_cache_reset_requested": bool(os.environ.get("RMM_SOURCE_COMMIT")),
        }

        def checkpoint_signature(module):
            # Resume ONLY the same authored gameplay and module interfaces.
            # Exclude mutable generated code; include the entire module layout
            # and grounded evidence hashes so a new design invalidates old code.
            design = proposal.game_design.get("dynamic_design") or {}
            research = proposal.game_design.get("pre_design_research") or {}
            contract = {
                "code_generation_components": component_fingerprints,
                "coder_backend": {
                    "router_type": type(self.router).__name__,
                    "profile": str(getattr(self.router, "profile", "")),
                },
                "request": proposal.requested_prompt,
                "module": {k: v for k, v in module.to_dict().items() if k != "code"},
                "all_modules": [{
                    "module_id": m.module_id, "name": m.name,
                    "file_path": m.file_path, "description": m.description,
                } for m in proposal.modules],
                "remotes": design.get("remotes", {}),
                "world_objects": design.get("world_objects", []),
                "module_facets": design.get("module_facets", {}),
                "module_remotes": design.get("module_remotes", {}),
                "module_world_objects": design.get("module_world_objects", {}),
                "host_world_motion": design.get("host_world_motion", {}),
                "host_vehicle_identity_bindings": design.get("host_vehicle_identity_bindings", []),
                "host_actions": design.get("host_actions", {}),
                "host_action_choices": design.get("host_action_choices", {}),
                "host_client_actions": design.get("host_client_actions", {}),
                "host_world_actions": design.get("host_world_actions", {}),
                "module_requirements": design.get("module_requirements", {}),
                "module_behaviors": design.get("module_behaviors", {}),
                "detailed_plan": proposal.game_design.get("detailed_implementation_plan", {}),
                "evidence": [{
                    "facet": e.get("facet"), "url": e.get("url"),
                    "sha": e.get("content_sha256"),
                } for e in research.get("evidence", [])],
            }
            # Keep previous hashes for already successful AI-generated
            # modules and PlayerDataManager. Only the built-in Remote bridge
            # implementation changed and must be regenerated.
            if module.module_id == "mod_network_bridge":
                contract["builtin_generator_revision"] = "custom-network-contract-v2"
            return hashlib.sha256(json.dumps(
                contract, ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")).hexdigest()

        def generate():
            completed = 0
            # An exhausted bounded coder is a failure of THAT module, not
            # proof that every other independent module is impossible. Gather
            # a bounded sample of independent failures while preserving all
            # valid source checkpoints. Never publish a partial game as PASS.
            try:
                failure_budget = int(os.environ.get(
                    "RMM_MAX_CODEGEN_FAILURE_DIAGNOSTICS", "3"))
            except ValueError:
                failure_budget = 3
            failure_budget = max(1, min(failure_budget, 12))
            failures: list[dict[str, Any]] = []
            blocked: list[dict[str, str]] = []
            failed_ids: set[str] = set()
            from .generation_provenance import (
                host_source_must_regenerate, trusted_checkpoint_source,
            )
            strategy_by_id = {
                row["module_id"]: row["strategy"]
                for row in generation_scope(proposal)["modules"]
            }
            # Persist checkpoints per completed module; never assume an
            # unrelated old file belongs to this game or trust a corrupt file.
            try:
                manifest = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                if manifest.get("schema") != "rmm/codegen-checkpoint-v1":
                    manifest = {}
            except (OSError, ValueError, TypeError):
                manifest = {}
            entries = manifest.get("modules", {})
            if not isinstance(entries, dict):
                entries = {}

            def save_checkpoint(module):
                content = module.code
                if not content or generated_module_errors(
                        module, proposal, content, self.analyzer):
                    return
                entries[module.file_path] = {
                    "input_sha256": checkpoint_signature(module),
                    "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
                staging = checkpoint_file.with_suffix(".json.tmp")
                staging.write_text(json.dumps({
                    "schema": "rmm/codegen-checkpoint-v1", "modules": entries,
                }, indent=2, ensure_ascii=False), encoding="utf-8")
                staging.replace(checkpoint_file)

            for module in proposal.modules:
                dependencies_failed = [dep for dep in module.depends_on
                                       if dep in failed_ids]
                if dependencies_failed:
                    blocked.append({"module": module.name,
                                    "reason": "failed_dependencies: " +
                                    ", ".join(dependencies_failed)})
                    failed_ids.add(module.module_id)
                    continue
                if failures and len(failures) >= failure_budget:
                    blocked.append({"module": module.name,
                                    "reason": "bounded_independent_failure_budget"})
                    continue
                is_host_generated = False
                try:
                    # Host-owned source is regenerated from the authoritative
                    # contract, even when an imported proposal already has
                    # stale or model-written code. No saved module may override
                    # the host Remote ingress or no-argument client UI.
                    dynamic_contract = proposal.game_design.get("dynamic_design") or {}
                    # Scope dispatch and source overwrite share a SINGLE
                    # classification. Previously 10+ declarative host adapters
                    # were classified as host source yet retained stale Luau
                    # from imported proposals/checkpoints.
                    is_host_generated = host_source_must_regenerate(
                        module, strategy_by_id.get(module.module_id, "")
                    )
                    if is_host_generated:
                        module.code = self.code_generator.generate_module_code(
                            module, proposal)
                    path = output_dir / module.file_path
                    fingerprint = checkpoint_signature(module)
                    stored = entries.get(module.file_path, {})
                    previous = trusted_checkpoint_source(
                        path, stored, fingerprint,
                        module.code if module.module_id.startswith("dyn_")
                        and not is_host_generated and module.code else None,
                    )
                    if (module.module_id.startswith("dyn_")
                            and not is_host_generated and module.code
                            and previous is None):
                        # Imported proposal_partial.json can contain previously
                        # generated *model* code. Never trust those bytes without
                        # a checkpoint matching every source file and ABI.
                        module.code = ""
                        trajectory.record(
                            "generation", "discard untrusted inline code " + module.file_path,
                            {"reason": "No matching signed source checkpoint"},
                            passed=True,
                        )
                    if not module.code and previous is not None:
                        if not generated_module_errors(
                                module, proposal, previous, self.analyzer):
                            module.code = previous
                            trajectory.record("generation", "resume " + module.file_path,
                                              {"source_bytes": len(previous),
                                               "source_sha256": stored["source_sha256"]},
                                              passed=True)
                    if not module.code:
                        module.code = self.code_generator.generate_with_self_correction(
                            module, proposal)
                    # Validate every generated or resumed source NOW, before
                    # advancing to the next 9B coding task or saving checkpoint.
                    # This catches real peer API and realm faults much earlier
                    # than the final whole-project acceptance gate.
                    require_generated_module_contract(
                        module, proposal, module.code, self.analyzer)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(module.code, encoding="utf-8")
                    save_checkpoint(module)
                    (output_dir / "proposal_partial.json").write_text(
                        json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False),
                        encoding="utf-8")
                    completed += 1
                    trajectory.record("generation", "save " + module.file_path,
                                      {"source_bytes": len(module.code)}, passed=True)
                except Exception as exc:
                    message = type(exc).__name__ + ": " + str(exc)
                    trace = traceback.format_exc()
                    failed_code = exc.candidate if isinstance(exc, LuauGenerationError) else module.code
                    actual_errors = (exc.diagnostics if isinstance(
                        exc, (LuauGenerationError, ModuleGenerationContractError))
                        else [message])
                    if failed_code:
                        debug_path = output_dir / "failed_candidates" / module.file_path
                        debug_path.parent.mkdir(parents=True, exist_ok=True)
                        debug_path.write_bytes(failed_code.encode("utf-8"))
                    # Keep every failed model candidate and parser observation,
                    # not just the last truncated version.
                    attempt_path = output_dir / "failed_candidates" / (
                        module.file_path + ".attempts.json")
                    attempt_path.parent.mkdir(parents=True, exist_ok=True)
                    attempt_record = {
                        "module": module.name,
                        "source_file": module.file_path,
                        "initial_generation_attempts": (
                            exc.history if isinstance(exc, LuauGenerationError) else []),
                        "initial_error": message,
                    }
                    attempt_path.write_text(
                        json.dumps(attempt_record, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    trajectory.record("generation", "generate " + module.file_path,
                                      {"error": message, "traceback": trace,
                                       "analyzer_diagnostics": actual_errors,
                                       "failed_candidate_saved": bool(failed_code)},
                                      passed=False)
                    # The original path immediately returned False. Feed the
                    # actual exception and partial source to the coding agent
                    # before abandoning this specific gameplay module.
                    bounded_failure = (
                        (isinstance(exc, LuauGenerationError)
                         and any(str(item).startswith("SCOPED_")
                                 for item in exc.diagnostics))
                        or (isinstance(exc, ModuleGenerationContractError)
                            and is_host_scaffolded_source(failed_code or ""))
                    )
                    if is_host_generated or bounded_failure or not module.module_id.startswith("dyn_"):
                        # One scoped module is exhausted; never re-run its
                        # failed body as a 6000-token whole ModuleScript.
                        # Diagnose a few independent modules before leaving
                        # the pipeline in a truthful FAILED state.
                        failures.append({
                            "module": module.name, "error": message,
                            "host_owned": is_host_generated,
                            "scoped_unit_exhausted": bounded_failure,
                            "requires_contract_revision": bounded_failure,
                        })
                        failed_ids.add(module.module_id)
                        module.code = ""
                        continue
                    try:
                        replacement = RobloxCodeRepairAgent(router=self.router).repair(
                            module, proposal,
                            existing_code=failed_code or "",
                            diagnostics=("Generation failed for " + module.file_path +
                                         "\n" + "\n".join(actual_errors) +
                                         "\n" + trace[-5000:]),
                            attempts=3,
                        )
                        # A repair that merely parses but still references
                        # invented services must not count as a recovered module.
                        require_generated_module_contract(
                            module, proposal, replacement, self.analyzer)
                        module.code = replacement
                        path = output_dir / module.file_path
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(replacement, encoding="utf-8")
                        save_checkpoint(module)
                        (output_dir / "proposal_partial.json").write_text(
                            json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False),
                            encoding="utf-8")
                        completed += 1
                        trajectory.record("generation", "recover " + module.file_path,
                                          {"source_bytes": len(replacement),
                                           "original_error": message},
                                          passed=True)
                        continue
                    except Exception as repair_error:
                        if isinstance(repair_error, LuauGenerationError):
                            latest_path = output_dir / "failed_candidates" / module.file_path
                            latest_path.parent.mkdir(parents=True, exist_ok=True)
                            latest_path.write_bytes(repair_error.candidate.encode("utf-8"))
                            attempt_record["last_failed_source_stage"] = "recovery"
                            attempt_record["last_diagnostics"] = repair_error.diagnostics
                        attempt_record["recovery_attempts"] = (
                            repair_error.history
                            if isinstance(repair_error, LuauGenerationError) else [])
                        attempt_record["recovery_error"] = (
                            type(repair_error).__name__ + ": " + str(repair_error))
                        attempt_path.write_text(
                            json.dumps(attempt_record, ensure_ascii=False, indent=2),
                            encoding="utf-8")
                        trajectory.record("generation", "recover " + module.file_path,
                                          {"initial_error": message,
                                           "repair_error": str(repair_error),
                                           "traceback": traceback.format_exc()},
                                          passed=False)
                        failures.append({
                            "module": module.name,
                            "error": "Initial generation: " + message +
                                     "; Recovery failed: " +
                                     type(repair_error).__name__ + ": " +
                                     str(repair_error),
                            "initial_error": message,
                            "repair_error": str(repair_error),
                        })
                        failed_ids.add(module.module_id)
                        module.code = ""
                        continue
            if failures:
                return {
                    "success": False,
                    "generated_count": completed,
                    "failed_module": failures[0]["module"],
                    "error": ("INDEPENDENT_CODEGEN_FAILURES: " +
                              "; ".join(str(row["module"]) + ": " +
                                        str(row["error"])[:350]
                                        for row in failures)),
                    "failed_modules": failures,
                    "blocked_modules": blocked,
                    "failure_budget": failure_budget,
                    "host_owned": failures[0].get("host_owned", False),
                    "scoped_unit_exhausted": failures[0].get(
                        "scoped_unit_exhausted", False),
                    "requires_contract_revision": any(
                        row.get("requires_contract_revision") for row in failures),
                }
            return {"generated_count": completed, "success": True}

        def materialize():
            created = self.project_generator.materialize_project_tree(proposal, output_dir)
            if proposal.game_design.get("detailed_implementation_plan"):
                (output_dir / "detailed_implementation_plan.json").write_text(
                    json.dumps(proposal.game_design["detailed_implementation_plan"],
                               indent=2, ensure_ascii=False), encoding="utf-8")
            # Recognize reusable offline contracts from the actual generated
            # project. This is never decided by the user's genre/prompt.
            self.toolchain.stage_lune_economy_test(output_dir)
            tool_results["offline_test_count"] = len(
                self.toolchain.discover_offline_tests(output_dir))
            if proposal.game_design.get("gameplay_contract"):
                (output_dir / "gameplay_contract.json").write_text(
                    json.dumps(proposal.game_design["gameplay_contract"],
                               indent=2, ensure_ascii=False), encoding="utf-8")
                (output_dir / "gameplay_playtest_scenarios.json").write_text(
                    json.dumps(make_studio_playtest_scenarios(
                        proposal.game_design["gameplay_contract"]),
                        indent=2, ensure_ascii=False), encoding="utf-8")
            (output_dir / "rokit.toml").write_text(self.toolchain.generate_rokit_manifest(), encoding="utf-8")
            (output_dir / "aftman.toml").write_text(self.toolchain.generate_aftman_manifest(), encoding="utf-8")
            if not source_only:
                # The default built-in game has no Wally runtime imports:
                # optional Promise/Signal/Jest dev packages must not turn
                # a valid offline Rojo build into a network install failure.
                # Fusion or ProfileStore explicitly opts into Wally.
                needs_wally = (
                    proposal.game_design.get("ui_backend") == "fusion"
                    or proposal.game_design.get("storage_backend") == "profilestore"
                )
                if not needs_wally:
                    tool_results["wally"] = {
                        "success": False, "executed": False,
                        "status": "not_applicable",
                        "reason": "Built-in UI/storage requires no external Wally packages",
                    }
                actions = [("stylua", lambda: self.toolchain.run_stylua(output_dir))]
                if needs_wally:
                    actions.append(("wally", lambda: self.toolchain.run_wally_install(output_dir)))
                for name, action in actions:
                    result = action()
                    tool_results[name] = result
                    if not result.get("success") or not result.get("executed"):
                        if (name == "stylua" and result.get("executed")
                                and proposal.game_design.get("dynamic_design")):
                            # Formatter has actionable Luau source diagnostics:
                            # pass them to the coding agent and rerun formatting.
                            try:
                                recovery = repair_tool_diagnostics(
                                    proposal, output_dir, name, result,
                                    retry_tool=action,
                                    format_sources=None,
                                    router=self.router,
                                )
                            except Exception as exc:
                                recovery = {"passed": False, "reason": str(exc)}
                            tool_results[name + "_repair"] = recovery
                            trajectory.record("tool", "repair " + name, recovery,
                                              passed=bool(recovery.get("passed")))
                            if recovery.get("passed"):
                                continue
                        # Missing executables, credentials and Wally network
                        # failures are environment errors, not Luau errors.
                        # Never ask a model to invent source to disguise them.
                        return {"success": False, "created_files": len(created),
                                "error": f"{name} failed after recovery: {result}",
                                "tool": name, "diagnostic": result}
            return {"created_files": len(created), "success": True}

        def check_static():
            source_map = {m.file_path: (output_dir / m.file_path).read_text(encoding="utf-8")
                          for m in proposal.modules}
            # StyLua and repair tools mutate disk. The REAL built sources are
            # the authority, not stale in-memory pre-format text. Otherwise
            # wiring and cross-file acceptance can approve a different program
            # from the one Rojo packages.
            for m in proposal.modules:
                m.code = source_map[m.file_path]
            checked_analysis = self.analyzer.analyze_files(source_map)
            checked_acceptance = acceptance_obligations(proposal, output_dir)
            (output_dir / "request_traceability.json").write_text(
                json.dumps(build_request_traceability(
                    proposal, acceptance=checked_acceptance, source_root=output_dir),
                    indent=2, ensure_ascii=False), encoding="utf-8")
            return checked_analysis, checked_acceptance

        def lint():
            nonlocal analysis_report, acceptance
            analysis_report, acceptance = check_static()
            if not analysis_report.passed or not acceptance["passed"]:
                trajectory.record("static", "initial source and acceptance checks", {
                    "analysis": analysis_report.to_dict(),
                    "failed_checks": [x for x in acceptance["checks"] if not x["passed"]],
                }, passed=False)
                if proposal.game_design.get("dynamic_design"):
                    analysis_report, acceptance, recovered = repair_static_failures(
                        proposal, output_dir, analysis_report, acceptance,
                        self.router, recheck=check_static,
                        format_sources=(lambda: self.toolchain.run_stylua(output_dir))
                        if not source_only else None, trajectory=trajectory)
                    if recovered:
                        trajectory.record("static", "self-repair verified",
                                          {"remaining_failures": 0}, passed=True)
                if not analysis_report.passed or not acceptance["passed"]:
                    missing = [x["id"] for x in acceptance["checks"] if not x["passed"]]
                    return {"passed": False,
                            "error": "Static repair unsuccessful; Lua errors: " +
                                     str(analysis_report.error_count) +
                                     "; missing checks: " + ", ".join(missing),
                            "analysis": analysis_report.to_dict(),
                            "failed_checks": [x for x in acceptance["checks"] if not x["passed"]]}

            if not source_only:
                for name, action in [
                    ("selene", lambda: self.toolchain.run_selene(output_dir)),
                    ("luau_analyze", lambda: self.toolchain.run_luau_analyze(output_dir)),
                ]:
                    result = action()
                    tool_results[name] = result
                    # luau-analyze is optional because the canonical Rokit
                    # toolchain in CI installs StyLua, Selene, Wally and Rojo.
                    # It is NOT reported as executed or as verified when absent.
                    # Real Selene and Rojo compilation remain mandatory below.
                    if (name == "luau_analyze" and not result.get("executed")
                            and result.get("message") == "luau-analyze missing"):
                        tool_results["luau_typechecking"] = {
                            "executed": False, "verified": False,
                            "reason": "Standalone luau-analyze not installed; "
                                      "Selene+Rojo validation is not static typechecking"
                        }
                        continue
                    if not result.get("success") or not result.get("executed"):
                        if (result.get("executed") and
                                proposal.game_design.get("dynamic_design")):
                            try:
                                recovery = repair_tool_diagnostics(
                                    proposal, output_dir, name, result,
                                    retry_tool=action,
                                    format_sources=lambda: self.toolchain.run_stylua(output_dir),
                                    router=self.router)
                            except Exception as exc:
                                recovery = {"passed":False,
                                            "reason":type(exc).__name__ + ": " + str(exc)[:400]}
                            tool_results[name + "_repair"] = recovery
                            trajectory.record("tool", "repair " + name, recovery,
                                              passed=bool(recovery.get("passed")))
                            if recovery.get("passed"):
                                # Re-evaluate source/semantic acceptance after edits.
                                revised_source={m.file_path:(output_dir/m.file_path).read_text(
                                    encoding="utf-8") for m in proposal.modules}
                                analysis_report=self.analyzer.analyze_files(revised_source)
                                acceptance=acceptance_obligations(proposal, output_dir)
                                (output_dir / "request_traceability.json").write_text(
                                    json.dumps(build_request_traceability(proposal, acceptance=acceptance, source_root=output_dir),
                                               indent=2, ensure_ascii=False), encoding="utf-8")
                                if not analysis_report.passed or not acceptance["passed"]:
                                    return {"passed":False,
                                            "error":"Post-repair static/contract check failed"}
                                continue
                        return {"passed": False, "error": f"{name} failed or skipped: {result}"}
            if not source_only:
                # Official Luau CLI grammar checking is optional when the
                # binary is not installed; a real failure is never ignored.
                compile_check = self.toolchain.run_luau_compile(output_dir)
                tool_results["luau_compile"] = compile_check
                if compile_check.get("executed") and not compile_check.get("success"):
                    return {"passed": False, "error": "Official Luau parser failed",
                            "diagnostic": compile_check}
                # Run ALL explicitly offline-compatible tests, regardless
                # of game type, source name, or module count.
                unit = self.toolchain.run_lune_offline_suite(output_dir)
                tool_results["lune_offline"] = unit
                if unit.get("executed") and not unit.get("success"):
                    return {"passed": False, "error": "Offline Luau tests failed",
                            "diagnostic": unit}
            # A second pass compares the actually written, formatted source
            # against each original requirement. It can run in Colab using
            # the already loaded local GGUF; Roblox Studio is NOT invoked.
            ai_review = review_generated_sources(proposal, output_dir, self.router)
            tool_results["ai_source_review"] = ai_review
            (output_dir / "ai_source_review.json").write_text(
                json.dumps(ai_review, indent=2, ensure_ascii=False), encoding="utf-8")
            if ai_review["status"] == "issues_found":
                # A review is an observation, not the end of the workflow.
                # For model-authored modules: diagnose -> plan -> patch ->
                # rerun real available validators -> inspect the new source.
                def verify_review_repair() -> dict:
                    observed = {}
                    if not source_only:
                        formatter = self.toolchain.run_stylua(output_dir)
                        observed["stylua"] = formatter
                        if formatter.get("executed") and not formatter.get("success"):
                            return {"passed": False, "reason": "StyLua failed",
                                    "tools": observed}
                    latest_analysis, latest_acceptance = check_static()
                    observed["static"] = {
                        "analysis": latest_analysis.passed,
                        "acceptance": latest_acceptance["passed"],
                        "failed_checks": [v["id"] for v in
                                          latest_acceptance["checks"] if not v["passed"]],
                    }
                    if not latest_analysis.passed or not latest_acceptance["passed"]:
                        return {"passed": False, "reason": "Static or contract regression",
                                "tools": observed}
                    if not source_only:
                        for key, call in (
                            ("selene", lambda: self.toolchain.run_selene(output_dir)),
                            ("luau_analyze", lambda: self.toolchain.run_luau_analyze(output_dir)),
                            ("luau_compile", lambda: self.toolchain.run_luau_compile(output_dir)),
                            ("lune_offline", lambda: self.toolchain.run_lune_offline_suite(output_dir)),
                        ):
                            tool = call()
                            observed[key] = tool
                            if tool.get("executed") and not tool.get("success"):
                                return {"passed": False,
                                        "reason": "Real " + key + " regression",
                                        "tools": observed}
                            if key == "selene" and not tool.get("executed"):
                                return {"passed": False, "reason": "Mandatory Selene not executed",
                                        "tools": observed}
                    return {"passed": True, "tools": observed}

                repair = run_source_repair_cycle(
                    proposal, output_dir, self.router, ai_review,
                    verify=verify_review_repair,
                    review_again=lambda: review_generated_sources(
                        proposal, output_dir, self.router),
                    max_rounds=int(os.environ.get("RMM_AI_REPAIR_ROUNDS", "3")),
                )
                tool_results["ai_source_repair"] = repair
                (output_dir / "ai_source_repair.json").write_text(
                    json.dumps(repair, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                trajectory.record(
                    "static", "AI source defect repair and re-review",
                    {"status": repair["status"], "rounds": len(repair["attempts"]),
                     "reason": repair["reason"],
                     "changed_files": repair["changed_files"]},
                    passed=repair["passed"],
                )
                if not repair["passed"]:
                    return {"passed": False,
                            "error": "AI defect repair exhausted or blocked: " + repair["reason"],
                            "repair_history": repair["attempts"],
                            "findings": [row for row in ai_review["findings"]
                                         if row["severity"] == "blocking"]}
                ai_review = repair["final_review"]
                tool_results["ai_source_review"] = ai_review
                (output_dir / "ai_source_review.json").write_text(
                    json.dumps(ai_review, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                analysis_report, acceptance = check_static()
                if not analysis_report.passed or not acceptance["passed"]:
                    return {"passed": False,
                            "error": "Final static acceptance regressed after source review repair"}
                # Retain only VERIFIED repaired code in the checkpoint.
                # Otherwise next Colab run resumes the stale pre-repair source
                # and makes the same small AI repeat all failed attempts.
                try:
                    saved = json.loads(checkpoint_file.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    saved = {}
                items = saved.get("modules", {})
                if not isinstance(items, dict):
                    items = {}
                for module in proposal.modules:
                    if module.file_path not in repair["changed_files"]:
                        continue
                    final_source = (output_dir / module.file_path).read_text(encoding="utf-8")
                    items[module.file_path] = {
                        "input_sha256": checkpoint_signature(module),
                        "source_sha256": hashlib.sha256(
                            final_source.encode("utf-8")).hexdigest(),
                    }
                temporary = checkpoint_file.with_suffix(".json.tmp")
                temporary.write_text(json.dumps({
                    "schema": "rmm/codegen-checkpoint-v1", "modules": items,
                }, indent=2, ensure_ascii=False), encoding="utf-8")
                temporary.replace(checkpoint_file)
            if ai_review["status"] == "failed":
                return {"passed": False, "error": "AI source review could not finish",
                        "diagnostic": ai_review.get("reason", "")}
            return {"passed": True, "static_checks": len(acceptance["checks"]),
                    "ai_source_review": ai_review["status"]}

        def package():
            nonlocal rbxlx_path, zip_path, build_mode
            if addon_mode:
                # An add-on is NOT a standalone Roblox Place and cannot be safely
                # published without inspecting the owner's base Experience.
                outzip = output_dir.parent / f"{proposal.game_title}_owned_addon.zip"
                self.project_generator.pack_project_zip(output_dir, outzip)
                zip_path = str(outzip)
                build_mode = "owned_addon_sources"
                return {"passed": True, "mode": build_mode,
                        "note": "Additive sources prepared. No Place edited or published."}
            if source_only:
                return {"passed": True, "mode": "source_only", "note": "Never counts as release verified"}
            place = output_dir.parent / f"{proposal.game_title}.rbxlx"
            result = self.toolchain.run_rojo_build(output_dir / "default.project.json", place)
            tool_results["rojo"] = result
            if not result.get("success") or not result.get("executed") or not place.is_file() or place.stat().st_size == 0:
                if result.get("executed") and proposal.game_design.get("dynamic_design"):
                    try:
                        recovery = repair_tool_diagnostics(
                            proposal, output_dir, "rojo", result,
                            retry_tool=lambda: self.toolchain.run_rojo_build(
                                output_dir / "default.project.json", place),
                            format_sources=lambda: self.toolchain.run_stylua(output_dir),
                            router=self.router)
                    except Exception as exc:
                        recovery = {"passed": False, "reason": type(exc).__name__ + ": " + str(exc)}
                    tool_results["rojo_repair"] = recovery
                    trajectory.record("tool", "repair Rojo build", recovery,
                                      passed=bool(recovery.get("passed")))
                    if recovery.get("passed"):
                        checked_analysis, checked_acceptance = check_static()
                        if not checked_analysis.passed or not checked_acceptance["passed"]:
                            return {"passed": False, "error": "Rojo repair regressed static acceptance"}
                        result = recovery["retried_tool"]
                        tool_results["rojo"] = result
                if not result.get("success") or not place.is_file() or place.stat().st_size == 0:
                    return {"passed": False, "error": f"Rojo build failed after repair: {result}"}
            structural = inspect_compiled_place(proposal, place, source_root=output_dir)
            tool_results["compiled_structure"] = structural
            if not structural["passed"]:
                return {"passed": False, "error": "Compiled Rojo place is missing requested objects: "
                        + str([x["id"] for x in structural["checks"] if not x["passed"]])}
            build_mode = "rojo_cli"
            rbxlx_path = str(place)
            # Include the compiled Place in the downloadable ZIP (previously
            # only the source folder was archived). Include a standalone
            # Windows Studio local smoke kit; no credentials or publishing.
            studio_kit = install_local_studio_checks(proposal, output_dir, place)
            tool_results["local_studio_kit"] = {
                "passed": True, "executed": False, "files_prepared": studio_kit,
                "scope": "optional local edit-mode Instance checks",
            }
            artifact_manifest = make_artifact_manifest(output_dir, place)
            (output_dir / "artifact_manifest.json").write_text(
                json.dumps(artifact_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            outzip = output_dir.parent / f"{proposal.game_title}_roblox_project.zip"
            self.project_generator.pack_project_zip(output_dir, outzip)
            with zipfile.ZipFile(outzip) as archive:
                names = set(archive.namelist())
                for relative, digest in artifact_manifest["source_files"].items():
                    if relative not in names or hashlib.sha256(archive.read(relative)).hexdigest() != digest:
                        return {"passed": False, "error": f"ZIP source mismatch: {relative}"}
                if "artifact_manifest.json" not in names:
                    return {"passed": False, "error": "ZIP missing manifest"}
                # The artifact isn't usable offline unless the executable
                # compiled Place itself is bundled, not just its Luau sources.
                if "compiled_place.rbxlx" not in names:
                    return {"passed": False, "error": "ZIP missing compiled Roblox Place"}
                if hashlib.sha256(archive.read("compiled_place.rbxlx")).hexdigest() != hashlib.sha256(place.read_bytes()).hexdigest():
                    return {"passed": False, "error": "ZIP compiled Place hash mismatch"}
                for member in ("structural_smoke.luau", "run_smoke.ps1", "README.md"):
                    if "local_studio/" + member not in names:
                        return {"passed": False, "error": "ZIP missing local Studio kit: " + member}
            zip_path = str(outzip)
            return {"passed": True, "mode": build_mode, "files": len(artifact_manifest["source_files"])}

        ready = stage(TaskStage.RESOLVE_DEPENDENCIES, resolve)
        if ready:
            ready = stage(TaskStage.GENERATE_CODE, generate)
        if ready:
            ready = stage(TaskStage.PACKAGE, materialize)
        if ready:
            ready = stage(TaskStage.LINT_AND_SELF_CORRECT, lint)
        if ready:
            ready = stage(TaskStage.PACKAGE, package)
        # Offline production is the default contract. Packaging must succeed
        # without Roblox account secrets, test IDs, network publishing, or a
        # Studio receipt. Engine checks are a separate *optional* local action.
        build_ready = bool(ready and not source_only and not addon_mode
                           and rbxlx_path and zip_path)
        artifact_ready = bool(ready and (
            build_ready or (addon_mode and zip_path) or source_only
        ))
        receipt.overall_success = artifact_ready
        # The report is written before the final ZIP repack so a downloaded
        # game says exactly which tests RMM ACTUALLY executed and which it did not.
        verification_report = make_verification_report(
            source_only=source_only, addon_mode=addon_mode,
            tool_results=tool_results,
            analysis_passed=analysis_report.passed,
            acceptance=acceptance, artifact_ready=artifact_ready,
        )
        (output_dir / "verification_report.json").write_text(
            json.dumps(verification_report, indent=2, ensure_ascii=False),
            encoding="utf-8")
        tool_results["verification_selection"] = verification_report
        print("[RMM VERIFY] " + json.dumps(verification_report["summary"]),
              flush=True)
        release_status = (
            "built_unverified" if build_ready
            else "addon_packaged" if artifact_ready and addon_mode
            else "source_only" if artifact_ready and source_only
            else "build_incomplete"
        )
        # The final artifact still needs a real Studio test before calling it
        # gameplay-verified. The separate local test never publishes anything.
        runtime["artifact_ready"] = artifact_ready
        (output_dir / "work_receipt.json").write_text(
            json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")
        failure_logs_zip = ""
        if not artifact_ready:
            failure_logs_zip = str(trajectory.failure_bundle(
                "; ".join(errors) or "Production checks failed",
                receipt=receipt.to_dict(), tool_results=tool_results))
            print("[RMM agent] failure logs: " + failure_logs_zip, flush=True)
        else:
            trajectory.record("result", "build artifacts created; Studio playtest not run",
                              {"place": rbxlx_path, "zip": zip_path,
                               "release_status": release_status}, passed=True)
        # The first ZIP is assembled inside the packaging stage, before that
        # stage can append its final receipt and the success trajectory event.
        # Rebuild the manifest *after* these facts have been recorded, then
        # repack. This prevents a "successful" ZIP with a truncated audit log
        # or stale hashes. Do not count a failed final ZIP as artifact-ready.
        if artifact_ready and zip_path:
            try:
                if not addon_mode and not source_only:
                    latest_manifest = make_artifact_manifest(output_dir, Path(rbxlx_path))
                    (output_dir / "artifact_manifest.json").write_text(
                        json.dumps(latest_manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")
                self.project_generator.pack_project_zip(output_dir, Path(zip_path))
                with zipfile.ZipFile(zip_path) as archive:
                    members = set(archive.namelist())
                    if "work_receipt.json" not in members or "agent_trajectory.json" not in members:
                        raise RuntimeError("Packaged ZIP missing final receipt/trajectory")
                    saved_receipt = json.loads(archive.read("work_receipt.json"))
                    saved_steps = json.loads(archive.read("agent_trajectory.json"))
                    if saved_receipt.get("overall_success") is not True:
                        raise RuntimeError("Packaged receipt is not a successful build")
                    if not any(step.get("phase") == "result" for step in saved_steps.get("steps", [])):
                        raise RuntimeError("Packaged trajectory missing final outcome")
                    if not addon_mode and not source_only:
                        if "compiled_place.rbxlx" not in members:
                            raise RuntimeError("Compiled Roblox Place missing from distribution")
                        if hashlib.sha256(archive.read("compiled_place.rbxlx")).hexdigest() != (
                            hashlib.sha256(Path(rbxlx_path).read_bytes()).hexdigest()
                        ):
                            raise RuntimeError("Compiled Place changed after initial validation")
                        for rel, digest in latest_manifest["source_files"].items():
                            if rel not in members or hashlib.sha256(archive.read(rel)).hexdigest() != digest:
                                raise RuntimeError("Final ZIP mismatch: " + rel)
            except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
                artifact_ready = False
                build_ready = False
                receipt.overall_success = False
                runtime["artifact_ready"] = False
                release_status = "build_incomplete"
                errors.append("final_package: " + str(exc))
                (output_dir / "work_receipt.json").write_text(
                    json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")
                failure_logs_zip = str(trajectory.failure_bundle(
                    "; ".join(errors), receipt=receipt.to_dict(), tool_results=tool_results))
                print("[RMM agent] final package failed: " + str(exc), flush=True)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return RobloxPipelineResult(
            success=receipt.overall_success,
            game_title=proposal.game_title,
            rbxlx_path=rbxlx_path, project_zip_path=zip_path,
            project_dir=str(output_dir),
            analysis_report=analysis_report, playtest_report=playtest_report,
            duration_ms=round(elapsed_ms, 2), work_receipt=receipt,
            build_mode=build_mode, generated_files=[m.file_path for m in proposal.modules],
            metadata={"acceptance": acceptance, "runtime": runtime,
                      "verification": verification_report, "tool_results": tool_results,
                      "errors": errors, "source_only": source_only,
                      "build_ready": build_ready,
                      "release_status": release_status,
                      "source_commit": os.environ.get("RMM_SOURCE_COMMIT", ""),
                      "agent_trajectory": str(trajectory.path),
                      "failure_logs_zip": failure_logs_zip,
                      "project_mode": proposal.game_design.get("project_mode", "new_experience"),
                      "addon_prepared": bool(addon_mode and ready)},
        )

    @staticmethod
    def _validate_studio_receipt(place: Path) -> dict:
        """Only admit explicit successful multiplayer check evidence for THIS exact place."""
        import os
        path = os.environ.get("RMM_STUDIO_E2E_RECEIPT", "")
        if not path or not Path(path).is_file():
            return {"passed": False, "reason": "StudioTestService multiplayer receipt unavailable"}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            required = {"jest_suites", "client_server", "coin_pickup", "shop_purchase", "datastore_restore"}
            ok = (data.get("runner") == "StudioTestService"
                  and data.get("evidence_type") == "local_studio_output"
                  and isinstance(data.get("studio_test_place_sha256"), str)
                  and len(data.get("studio_test_place_sha256", "")) == 64
                  and data.get("place_sha256") == hashlib.sha256(place.read_bytes()).hexdigest()
                  and all(data.get("checks", {}).get(name) is True for name in required))
            return {"passed": bool(ok), "reason": "receipt validated" if ok else "invalid or incomplete receipt"}
        except (ValueError, OSError) as exc:
            return {"passed": False, "reason": str(exc)}
