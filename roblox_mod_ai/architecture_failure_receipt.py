"""Preserve the actual micro-planner failure instead of masking it as missing owners.

All claims are diagnostics, not evidence that generated gameplay passed.
The report is packaged by AgentTrajectory with every failed production run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_architecture_compilation_report(
    proposal: Any,
    project_dir: str | Path,
) -> dict[str, Any]:
    design = getattr(proposal, "game_design", {}) or {}
    research = design.get("pre_design_research") or {}
    ledger = research.get("ledger") or {}
    failures = research.get("provider_failures") or []
    history = research.get("architecture_attempts") or []
    # History is accumulated by the planner's scoped retries. Cap the output,
    # never claim the retained subset is the entire trace if it was oversized.
    entries = history if isinstance(history, list) else []
    if len(entries) > 240:
        selected = entries[-240:]
    else:
        selected = entries
    root_errors = [
        str(f.get("reason", ""))
        for f in failures
        if isinstance(f, dict) and f.get("facet") == "dynamic_game_design"
    ]
    report = {
        "schema": "rmm/architecture-compile-diagnostics-v1",
        "status": ("compiled" if design.get("dynamic_design")
                   else "uncompiled"),
        "phase": design.get("planning_phase"),
        "root_error": root_errors[-1] if root_errors else None,
        "provider_failures": failures,
        "attempts_recorded": len(entries),
        "attempts_included": len(selected),
        "attempts_omitted": len(entries) - len(selected),
        "architecture_attempts": selected,
        "classification_unverified": ledger.get("classification_unverified", []),
        "unimplemented_facets": ledger.get("unimplemented_facets", []),
        "unmatched_requirements": ledger.get("unmatched_requirements", []),
        "requested_requirement_ids": [
            row.get("id") for row in ledger.get("requirements", [])
            if isinstance(row, dict)
        ],
    }
    dest = Path(project_dir) / "architecture_compilation_report.json"
    dest.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return {
        "executed": True,
        "status": report["status"],
        "root_error": report["root_error"],
        "attempts_recorded": report["attempts_recorded"],
        "attempts_included": report["attempts_included"],
        "report_file": dest.name,
    }
