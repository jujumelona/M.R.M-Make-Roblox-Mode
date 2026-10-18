"""Persistent action -> observation journal for MRM's coding agent.

Inspired by SWE-agent trajectories and Aider's edit/lint/test feedback loop.
No model output is considered success until the same concrete check passes.
"""
from __future__ import annotations

import json
from pathlib import Path
import zipfile
from typing import Any


class AgentTrajectory:
    def __init__(self, output_dir: str | Path) -> None:
        self.root = Path(output_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "agent_trajectory.json"
        self.events: list[dict[str, Any]] = []
        self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps({
            "schema": "rmm/agent-trajectory-v1",
            "steps": self.events,
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def record(self, phase: str, action: str, observation: Any,
               *, passed: bool, attempt: int = 1) -> None:
        event = {
            "step": len(self.events) + 1,
            "phase": phase,
            "action": action,
            "attempt": attempt,
            "passed": bool(passed),
            "observation": observation,
        }
        self.events.append(event)
        self._save()
        status = "OK" if passed else "FAILED"
        print(f"[RMM agent] {phase} / {action} / attempt {attempt}: {status}",
              flush=True)
        if not passed:
            print(f"[RMM agent] diagnostic: {str(observation)[:1200]}", flush=True)

    def failure_bundle(self, error: str, *, receipt: Any = None,
                       tool_results: Any = None) -> Path:
        """Save failed run's exact checks, generated code and execution logs."""
        report = {
            "schema": "rmm/agent-failure-v1",
            "success": False,
            "error": error,
            "trajectory_file": self.path.name,
            "steps": len(self.events),
            "receipt": receipt,
            "tool_results": tool_results,
        }
        report_path = self.root / "agent_failure_report.json"
        report_path.write_text(json.dumps(
            report, ensure_ascii=False, indent=2, default=str
        ), encoding="utf-8")
        out = self.root.parent / (self.root.name + "_failure_logs.zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                # Never recursively include prior ZIP artifacts or model weights.
                if path.suffix.lower() in {".zip", ".gguf", ".rbxlx", ".exe"}:
                    continue
                if path.stat().st_size > 10_000_000:
                    continue
                archive.write(path, path.relative_to(self.root).as_posix())
        return out
