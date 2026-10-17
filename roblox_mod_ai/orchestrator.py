"""Production orchestrator coordinating code generation, analysis, playtest, and build."""

from __future__ import annotations

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
from .spec import RobloxProposal


@dataclass
class RobloxPipelineResult:
    """Final build output artifacts and verification reports."""

    success: bool
    game_title: str
    rbxlx_path: str
    project_zip_path: str
    project_dir: str
    analysis_report: LuauAnalysisReport
    playtest_report: PlaytestReport
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "game_title": self.game_title,
            "rbxlx_path": self.rbxlx_path,
            "project_zip_path": self.project_zip_path,
            "project_dir": self.project_dir,
            "analysis": self.analysis_report.to_dict(),
            "playtest": self.playtest_report.to_dict(),
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class RobloxProductionOrchestrator:
    """Coordinates the end-to-end production of a Roblox experience."""

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

    def execute(
        self,
        candidate: RobloxProposal | RobloxAuthoredPlan,
        run_name: str = "build-output",
        source_only: bool = False,
    ) -> RobloxPipelineResult:
        """Executes full production pipeline: code generation, static analysis, playtest, and packing."""
        start_time = time.perf_counter()

        proposal = candidate.proposal if isinstance(candidate, RobloxAuthoredPlan) else candidate
        output_dir = self.workspace_root / run_name / proposal.game_title
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"🚀 [R.M.M Production] Starting build for: {proposal.game_title}", flush=True)

        # 1. Generate Luau source code for all modules
        print("📝 Step 1: Generating Luau source modules...", flush=True)
        completed_modules = self.code_generator.generate_all_modules(proposal)
        proposal.modules = completed_modules

        # 2. Materialize Rojo project file tree
        print(f"📁 Step 2: Materializing Rojo project tree at {output_dir}...", flush=True)
        created_paths = self.project_generator.materialize_project_tree(proposal, output_dir)

        # 3. Static Luau Analysis & Linting
        print("🔍 Step 3: Running Luau static analysis and syntax checks...", flush=True)
        file_map = {m.file_path: m.code for m in proposal.modules}
        analysis_report = self.analyzer.analyze_files(file_map)

        if not analysis_report.passed:
            print(f"⚠️ Luau analysis reported {analysis_report.error_count} syntax errors!", flush=True)
        else:
            print(f"✅ Luau static analysis passed ({analysis_report.files_analyzed} files checked).", flush=True)

        # 4. Playtest Simulation (Headless Roblox Studio TestEZ)
        print("🎮 Step 4: Running automated Playtest and TestEZ specifications...", flush=True)
        playtest_report = self.playtest_runner.run_headless_playtest(proposal)
        print(
            f"✅ Playtest completed: {playtest_report.passed_count}/{playtest_report.total_tests} tests passed.",
            flush=True,
        )

        rbxlx_file_path = ""
        zip_file_path = ""

        if not source_only:
            # 5. Build Native .rbxlx XML Place File
            print(f"📦 Step 5: Compiling Roblox XML Place file ({proposal.game_title}.rbxlx)...", flush=True)
            rbxlx_dest = output_dir.parent / f"{proposal.game_title}.rbxlx"
            self.project_generator.build_rbxlx_place_file(proposal, rbxlx_dest)
            rbxlx_file_path = str(rbxlx_dest)
            print(f"✨ Native Roblox Place generated: {rbxlx_dest}", flush=True)

            # 6. Pack Distribution ZIP
            print("🗜️ Step 6: Packaging complete project distribution ZIP...", flush=True)
            zip_dest = output_dir.parent / f"{proposal.game_title}_roblox_project.zip"
            self.project_generator.pack_project_zip(output_dir, zip_dest)
            zip_file_path = str(zip_dest)
            print(f"✨ Project ZIP created: {zip_dest}", flush=True)

        total_duration = (time.perf_counter() - start_time) * 1000

        overall_success = analysis_report.passed and playtest_report.passed
        print(
            f"🎉 [R.M.M Build Finished] Success: {overall_success} ({round(total_duration, 1)}ms)",
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
            metadata={
                "modules_count": len(proposal.modules),
                "assets_count": len(proposal.assets),
                "tests_count": len(proposal.tests),
            },
        )
