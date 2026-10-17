"""Work graph and stage-by-stage task execution engine for R.M.M (derived from M.M.M)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class TaskStage(str, Enum):
    ANALYZE = "analyze"
    PLAN = "plan"
    ASSETS = "assets"
    RESOLVE_DEPENDENCIES = "resolve_dependencies"
    GENERATE_CODE = "generate_code"
    LINT_AND_SELF_CORRECT = "lint_and_self_correct"
    PLAYTEST = "playtest"
    PACKAGE = "package"


@dataclass
class StageReceipt:
    stage: TaskStage
    success: bool
    duration_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class WorkReceipt:
    task_id: str
    overall_success: bool
    stages: list[StageReceipt] = field(default_factory=list)
    salvaged_modules: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "overall_success": self.overall_success,
            "stages": [
                {
                    "stage": s.stage.value,
                    "success": s.success,
                    "duration_ms": round(s.duration_ms, 2),
                    "details": s.details,
                    "errors": s.errors,
                }
                for s in self.stages
            ],
            "salvaged_modules": self.salvaged_modules,
            "created_at": self.created_at,
        }


class RobloxWorkGraph:
    """Executes the multi-stage pipeline with topological ordering, receipts, and error recovery."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def execute_stage(
        self,
        stage: TaskStage,
        action: Callable[[], dict[str, Any]],
        receipt: WorkReceipt,
    ) -> dict[str, Any]:
        """Executes a single pipeline stage, capturing duration, errors, and receipts."""
        start = time.perf_counter()
        try:
            result = action()
            duration = (time.perf_counter() - start) * 1000.0
            receipt.stages.append(
                StageReceipt(
                    stage=stage,
                    success=True,
                    duration_ms=duration,
                    details=result,
                )
            )
            return result
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000.0
            receipt.stages.append(
                StageReceipt(
                    stage=stage,
                    success=False,
                    duration_ms=duration,
                    errors=[str(exc)],
                )
            )
            receipt.overall_success = False
            raise

    @staticmethod
    def topological_sort_modules(modules: list[Any]) -> list[Any]:
        """Sorts modules by depends_on dependencies so shared/services compile before consumers."""
        by_id = {getattr(m, "module_id", getattr(m, "name", str(i))): m for i, m in enumerate(modules)}
        visited: set[str] = set()
        visiting: set[str] = set()
        ordered: list[Any] = []

        def dfs(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(f"Module dependency cycle: {node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            mod = by_id.get(node_id)
            if mod:
                deps = getattr(mod, "depends_on", []) or []
                for dep in deps:
                    if dep not in by_id:
                        raise ValueError(f"Missing module dependency: {mod.module_id} -> {dep}")
                    dfs(dep)
            visiting.remove(node_id)
            visited.add(node_id)
            if mod:
                ordered.append(mod)

        for mod_id in by_id:
            if mod_id not in visited:
                dfs(mod_id)

        return ordered
