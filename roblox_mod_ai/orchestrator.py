"""Production orchestrator coordinating code generation, analysis, playtest, and build with WorkGraph."""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .code_generator import LuauCodeGenerator
from .dynamic_repair import repair_tool_diagnostics, repair_static_failures
from .agent_trajectory import AgentTrajectory
from .quality_gates import acceptance_obligations, make_artifact_manifest
from .request_traceability import build_request_traceability
from .runtime_verification import OpenCloudRuntimeVerifier
from .rbxlx_inspector import inspect_compiled_place
import hashlib
import zipfile
from .luau_analyzer import LuauAnalysisReport, LuauStaticAnalyzer
from .model_router import ModelRouter
from .playtest_runner import PlaytestReport, RobloxPlaytestRunner, TestCaseResult
from .project_generator import RobloxProjectGenerator
from .roblox_toolchain import RobloxToolchainManager
from .spec import RobloxProposal
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
        addon_mode = proposal.game_design.get("project_mode") == "existing_experience_addon"
        output_dir = self.workspace_root / run_name / proposal.game_title
        output_dir.mkdir(parents=True, exist_ok=True)
        trajectory = AgentTrajectory(output_dir)
        receipt = WorkReceipt(task_id=f"rmm_{proposal.game_title}_{int(time.time())}", overall_success=False)
        errors: list[str] = []
        tool_results: dict[str, dict] = {}
        acceptance: dict = {"passed": False, "checks": []}
        runtime: dict = {"passed": False, "executed": False, "reason": "not run"}
        analysis_report = LuauAnalysisReport(passed=False)
        playtest_report = PlaytestReport(
            passed=False, total_tests=1, passed_count=0, failed_count=1, duration_ms=0,
            results=[TestCaseResult(name="Real Roblox engine and multiplayer tests", passed=False, duration_ms=0,
                                    message="No verified Roblox engine execution")],
        )
        rbxlx_path = ""
        zip_path = ""
        build_mode = "source_only" if source_only else "rojo_required"

        def stage(stage_id: TaskStage, callback) -> bool:
            began = time.perf_counter()
            try:
                details = callback()
                passed = bool(details.get("success", details.get("passed", True)))
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
            proposal.modules = self.work_graph.topological_sort_modules(proposal.modules)
            return {"module_order": [m.name for m in proposal.modules]}

        def generate():
            completed = 0
            for module in proposal.modules:
                try:
                    if not module.code:
                        module.code = self.code_generator.generate_with_self_correction(
                            module, proposal)
                    path = output_dir / module.file_path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(module.code, encoding="utf-8")
                    (output_dir / "proposal_partial.json").write_text(
                        json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False),
                        encoding="utf-8")
                    completed += 1
                    trajectory.record("generation", "save " + module.file_path,
                                      {"source_bytes": len(module.code)}, passed=True)
                except Exception as exc:
                    message = type(exc).__name__ + ": " + str(exc)
                    trajectory.record("generation", "generate " + module.file_path,
                                      {"error": message, "traceback": traceback.format_exc()},
                                      passed=False)
                    return {"success": False, "generated_count": completed,
                            "failed_module": module.name, "error": message}
            return {"generated_count": completed, "success": True}

        def materialize():
            created = self.project_generator.materialize_project_tree(proposal, output_dir)
            (output_dir / "rokit.toml").write_text(self.toolchain.generate_rokit_manifest(), encoding="utf-8")
            (output_dir / "aftman.toml").write_text(self.toolchain.generate_aftman_manifest(), encoding="utf-8")
            if not source_only:
                for name, action in [
                    ("stylua", lambda: self.toolchain.run_stylua(output_dir)),
                    ("wally", lambda: self.toolchain.run_wally_install(output_dir)),
                ]:
                    result = action()
                    tool_results[name] = result
                    if not result.get("success") or not result.get("executed"):
                        raise RuntimeError(f"{name} failed or skipped: {result}")
            return {"created_files": len(created), "success": True}

        def check_static():
            source_map = {m.file_path: (output_dir / m.file_path).read_text(encoding="utf-8")
                          for m in proposal.modules}
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
            return {"passed": True, "static_checks": len(acceptance["checks"])}

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
        if ready and not source_only and not addon_mode:
            runtime = OpenCloudRuntimeVerifier().run(proposal, Path(rbxlx_path))
            # Open Cloud smoke proves server structure and DataStore only; it does not
            # prove client-server user interactions or join/leave restore.
            real_multiplayer = self._validate_studio_receipt(Path(rbxlx_path))
            runtime["multiplayer"] = real_multiplayer
            runtime["server_smoke_passed"] = bool(runtime.get("passed"))
            runtime["passed"] = bool(runtime["server_smoke_passed"] and real_multiplayer["passed"])
            ready = stage(TaskStage.PLAYTEST, lambda: {
                "passed": runtime["passed"], "scope": "server engine + Studio multiplayer",
                "error": runtime.get("reason", real_multiplayer.get("reason", "runtime verification incomplete"))})
            playtest_report = PlaytestReport(
                passed=ready, total_tests=2,
                passed_count=int(bool(runtime.get("server_smoke_passed"))) + int(real_multiplayer["passed"]),
                failed_count=2 - (int(bool(runtime.get("server_smoke_passed"))) + int(real_multiplayer["passed"])),
                duration_ms=0,
                results=[
                    TestCaseResult(name="Open Cloud server+DataStore", passed=bool(runtime.get("server_smoke_passed")),
                                   duration_ms=0, message=str(runtime.get("reason", runtime.get("state")))),
                    TestCaseResult(name="Studio multiplayer + persistence restore", passed=real_multiplayer["passed"],
                                   duration_ms=0, message=str(real_multiplayer.get("reason", "evidence accepted"))),
                ],
            )
        receipt.overall_success = bool(ready and not source_only and not addon_mode)
        (output_dir / "work_receipt.json").write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")
        failure_logs_zip = ""
        if not receipt.overall_success:
            failure_logs_zip = str(trajectory.failure_bundle(
                "; ".join(errors) or "Engine verification evidence missing",
                receipt=receipt.to_dict(), tool_results=tool_results))
            print("[RMM agent] failure logs: " + failure_logs_zip, flush=True)
        else:
            trajectory.record("result", "verified release",
                              {"place": rbxlx_path}, passed=True)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return RobloxPipelineResult(
            success=receipt.overall_success,
            game_title=proposal.game_title,
            rbxlx_path=rbxlx_path, project_zip_path=zip_path,
            project_dir=str(output_dir),
            analysis_report=analysis_report, playtest_report=playtest_report,
            duration_ms=round(elapsed_ms, 2), work_receipt=receipt,
            build_mode=build_mode, generated_files=[m.file_path for m in proposal.modules],
            metadata={"acceptance": acceptance, "runtime": runtime, "tool_results": tool_results,
                      "errors": errors, "source_only": source_only,
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
