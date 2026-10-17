"""Production orchestrator coordinating code generation, analysis, playtest, and build with WorkGraph."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .authored_plan import RobloxAuthoredPlan
from .code_generator import LuauCodeGenerator
from .luau_analyzer import LuauAnalysisReport, LuauStaticAnalyzer
from .model_router import ModelRouter
from .playtest_runner import PlaytestReport, RobloxPlaytestRunner
from .project_generator import RobloxProjectGenerator
from .roblox_toolchain import RobloxToolchainManager
from .spec import RobloxProposal
from .work_graph import RobloxWorkGraph, TaskStage, WorkReceipt


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
        """Executes full production pipeline with step-by-step receipts and self-correction."""
        start_time = time.perf_counter()

        proposal = candidate.proposal if isinstance(candidate, RobloxAuthoredPlan) else candidate
        output_dir = self.workspace_root / run_name / proposal.game_title
        output_dir.mkdir(parents=True, exist_ok=True)

        receipt = WorkReceipt(task_id=f"rmm_{proposal.game_title}_{int(time.time())}", overall_success=True)
        print(f"🚀 [R.M.M Production] Starting build for: {proposal.game_title}", flush=True)

        # 1. Dependency Resolution & Topological Ordering
        def step_resolve_deps():
            sorted_modules = self.work_graph.topological_sort_modules(proposal.modules)
            proposal.modules = sorted_modules
            return {"module_order": [m.name for m in sorted_modules]}

        self.work_graph.execute_stage(TaskStage.RESOLVE_DEPENDENCIES, step_resolve_deps, receipt)

        # 2. Code Generation with Self-Correction Loop
        def step_generate_code():
            print("📝 Step 2: Generating Luau source modules with self-correction loop...", flush=True)
            completed_modules = self.code_generator.generate_all_modules(proposal)
            proposal.modules = completed_modules
            return {"generated_count": len(completed_modules)}

        self.work_graph.execute_stage(TaskStage.GENERATE_CODE, step_generate_code, receipt)

        # 3. Project Tree Materialization & Toolchain Formatting
        def step_materialize():
            print(f"📁 Step 3: Materializing Rojo project tree at {output_dir}...", flush=True)
            created_paths = self.project_generator.materialize_project_tree(proposal, output_dir)

            (output_dir / "rokit.toml").write_text(self.toolchain.generate_rokit_manifest(), encoding="utf-8")
            (output_dir / "aftman.toml").write_text(self.toolchain.generate_aftman_manifest(), encoding="utf-8")

            self.toolchain.run_stylua(output_dir)
            self.toolchain.run_wally_install(output_dir)
            return {"created_files": len(created_paths)}

        self.work_graph.execute_stage(TaskStage.PACKAGE, step_materialize, receipt)

        # 4. Static Luau Analysis & Selene Linting
        analysis_report: LuauAnalysisReport | None = None

        def step_lint():
            nonlocal analysis_report
            print("🔍 Step 4: Running Luau static analysis and Selene linting...", flush=True)
            self.toolchain.run_selene(output_dir)
            file_map = {m.file_path: m.code for m in proposal.modules}
            analysis_report = self.analyzer.analyze_files(file_map)
            if not analysis_report.passed:
                print(f"⚠️ Luau analysis reported {analysis_report.error_count} syntax errors!", flush=True)
            else:
                print(f"✅ Luau static analysis passed ({analysis_report.files_analyzed} files checked).", flush=True)
            return {"errors": analysis_report.error_count, "warnings": analysis_report.warning_count, "passed": analysis_report.passed}

        self.work_graph.execute_stage(TaskStage.LINT_AND_SELF_CORRECT, step_lint, receipt)

        # 5. Playtest Simulation (Headless Roblox Studio TestEZ)
        playtest_report: PlaytestReport | None = None

        def step_playtest():
            nonlocal playtest_report
            print("🎮 Step 5: Running automated Playtest and TestEZ specifications...", flush=True)
            playtest_report = self.playtest_runner.run_headless_playtest(proposal)
            print(
                f"✅ Playtest completed: {playtest_report.passed_count}/{playtest_report.total_tests} tests passed.",
                flush=True,
            )
            return {"total": playtest_report.total_tests, "passed": playtest_report.passed_count, "failed": playtest_report.failed_count}

        self.work_graph.execute_stage(TaskStage.PLAYTEST, step_playtest, receipt)

        rbxlx_file_path = ""
        zip_file_path = ""
        build_mode = "source_only"

        if not source_only:
            # 6. Build Native .rbxlx XML Place File (Explicitly distinguish Rojo CLI from XML fallback)
            print(f"📦 Step 6: Compiling Roblox XML Place file ({proposal.game_title}.rbxlx)...", flush=True)
            rbxlx_dest = output_dir.parent / f"{proposal.game_title}.rbxlx"

            rojo_res = self.toolchain.run_rojo_build(output_dir / "default.project.json", rbxlx_dest)
            if rojo_res.get("success"):
                build_mode = "rojo_cli"
                print("✨ Compiled place file via Rojo CLI.", flush=True)
            else:
                build_mode = "native_xml_engine"
                if self.toolchain.get_status().rojo_available:
                    print(f"⚠️ Rojo CLI build returned non-zero ({rojo_res.get('error')}); engaging native XML compiler.", flush=True)
                self.project_generator.build_rbxlx_place_file(proposal, rbxlx_dest)
                print(f"✨ Native Roblox Place generated via internal XML engine: {rbxlx_dest}", flush=True)

            rbxlx_file_path = str(rbxlx_dest)

            # 7. Pack Distribution ZIP
            print("🗜️ Step 7: Packaging complete project distribution ZIP...", flush=True)
            zip_dest = output_dir.parent / f"{proposal.game_title}_roblox_project.zip"
            self.project_generator.pack_project_zip(output_dir, zip_dest)
            zip_file_path = str(zip_dest)
            print(f"✨ Project ZIP created: {zip_dest}", flush=True)

        total_duration = (time.perf_counter() - start_time) * 1000

        assert analysis_report is not None
        assert playtest_report is not None

        overall_success = analysis_report.passed and playtest_report.passed
        receipt.overall_success = overall_success

        # Write work receipt to disk
        receipt_path = output_dir / "work_receipt.json"
        receipt_path.write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")

        print(
            f"🎉 [R.M.M Build Finished] Success: {overall_success} (Mode: {build_mode}, {round(total_duration, 1)}ms)",
            flush=True,
        )

        return RobloxPipelineResult(
            success=overall_success,
            game_title=proposal.game_title,
            rbxlx_path=rbxlx_file_path,
            project_zip_path=zip_file_path,
            project_dir=str(output_dir),
            analysis_report=analysis_report,
            playtest_report=playtest_report,
            duration_ms=round(total_duration, 2),
            work_receipt=receipt,
            build_mode=build_mode,
            generated_files=[m.file_path for m in proposal.modules],
            metadata={
                "modules_count": len(proposal.modules),
                "assets_count": len(proposal.assets),
                "tests_count": len(proposal.tests),
                "toolchain": self.toolchain.get_status().to_dict(),
            },
        )
