"""Production orchestrator coordinating code generation, analysis, playtest, and build with WorkGraph."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .code_generator import LuauCodeGenerator
from .quality_gates import acceptance_obligations, make_artifact_manifest
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
        output_dir = self.workspace_root / run_name / proposal.game_title
        output_dir.mkdir(parents=True, exist_ok=True)
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
                return passed
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                receipt.stages.append(StageReceipt(stage=stage_id, success=False,
                    duration_ms=(time.perf_counter() - began) * 1000, errors=[msg]))
                errors.append(f"{stage_id.value}: {msg}")
                return False

        def resolve():
            proposal.modules = self.work_graph.topological_sort_modules(proposal.modules)
            return {"module_order": [m.name for m in proposal.modules]}

        def generate():
            proposal.modules = self.code_generator.generate_all_modules(proposal)
            return {"generated_count": len(proposal.modules)}

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

        def lint():
            nonlocal analysis_report, acceptance
            source_map = {m.file_path: (output_dir / m.file_path).read_text(encoding="utf-8")
                          for m in proposal.modules}
            analysis_report = self.analyzer.analyze_files(source_map)
            acceptance = acceptance_obligations(proposal, output_dir)
            if not analysis_report.passed:
                return {"passed": False, "error": f"Luau static errors: {analysis_report.error_count}"}
            if not acceptance["passed"]:
                missing = [x["id"] for x in acceptance["checks"] if not x["passed"]]
                return {"passed": False, "error": "Missing acceptance evidence: " + ", ".join(missing)}
            if not source_only:
                for name, action in [
                    ("selene", lambda: self.toolchain.run_selene(output_dir)),
                    ("luau_analyze", lambda: self.toolchain.run_luau_analyze(output_dir)),
                ]:
                    result = action()
                    tool_results[name] = result
                    if not result.get("success") or not result.get("executed"):
                        return {"passed": False, "error": f"{name} failed or skipped: {result}"}
            return {"passed": True, "static_checks": len(acceptance["checks"])}

        def package():
            nonlocal rbxlx_path, zip_path, build_mode
            if source_only:
                return {"passed": True, "mode": "source_only", "note": "Never counts as release verified"}
            place = output_dir.parent / f"{proposal.game_title}.rbxlx"
            result = self.toolchain.run_rojo_build(output_dir / "default.project.json", place)
            tool_results["rojo"] = result
            if not result.get("success") or not result.get("executed") or not place.is_file() or place.stat().st_size == 0:
                return {"passed": False, "error": f"Rojo build failed (no XML fallback): {result}"}
            structural = inspect_compiled_place(proposal, place)
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
        if ready and not source_only:
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
        receipt.overall_success = bool(ready and not source_only)
        (output_dir / "work_receipt.json").write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")
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
                      "errors": errors, "source_only": source_only},
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
