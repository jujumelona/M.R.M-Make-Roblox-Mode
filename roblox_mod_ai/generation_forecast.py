"""Auditable success sensitivity for local-model Roblox game generation.

This is NOT a probability estimator fitted to MiMo 9B. Without recorded
independent end-to-end model runs, probability of success is unidentified.
The scenario grid is explicitly hypothetical and displays how 7 planned
features + N code modules compound per-stage failure.

All counts come from the proposal/source ledger. No mock CI pass is counted
as a real model sample.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .request_contract import implementation_facets


@dataclass(frozen=True)
class StageAssumptions:
    name: str
    per_facet_design: float
    per_module_code: float
    assembly_and_static: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) and 0 <= value <= 1
                   for value in (self.per_facet_design,
                                 self.per_module_code,
                                 self.assembly_and_static)):
            raise ValueError("Hypothetical pass probabilities must be finite in [0, 1]")


SCENARIOS = (
    StageAssumptions("challenging_hypothesis", 0.60, 0.60, 0.80),
    StageAssumptions("middle_hypothesis", 0.80, 0.80, 0.90),
    StageAssumptions("favorable_hypothesis", 0.95, 0.95, 0.95),
)


def scenario_success(facet_count: int, code_module_count: int,
                     assumptions: StageAssumptions,
                     *, independent_retry_attempts: int = 1) -> float:
    """Illustrative result under stage AND retry independence assumptions.

    Repeated failures on the same small model often correlate, so 3 retries
    MUST NOT be sold as an achieved success probability. No Roblox Studio
    verification probability is supplied; this is only through static build.
    """
    if facet_count < 0 or code_module_count < 0:
        raise ValueError("Stage count cannot be negative")
    if not 1 <= independent_retry_attempts <= 5:
        raise ValueError("Independent retry scenario must use 1 to 5 attempts")
    def effective(p: float) -> float:
        return 1.0 - (1.0 - p) ** independent_retry_attempts
    return (
        effective(assumptions.per_facet_design) ** facet_count
        * effective(assumptions.per_module_code) ** code_module_count
        * assumptions.assembly_and_static
    )


def forecast_generation(
    *,
    requested_prompt: str,
    ledger: dict[str, Any],
    modules: list[dict[str, Any]],
    remotes: dict[str, Any] | None = None,
    observed_model_runs: list[dict[str, Any]] | None = None,
    expected_input_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Return a source-derived size report and *unfitted* scenario sensitivity.

    observed_model_runs is an optional list of real full-game run receipts.
    Only a completed run tagged real_local_llama_cpp_not_mock and a definite
    status is counted; individual CI tests / mock model calls never count.
    """
    facets = implementation_facets(ledger)
    facet_count = len(facets)
    code_modules = [m for m in modules if str(m.get("module_id", "")).startswith("dyn_")]
    code_count = len(code_modules)
    client = sum(str(m.get("file_path", "")).endswith(".client.luau")
                 for m in code_modules)
    server = sum(str(m.get("file_path", "")).startswith("src/server/")
                 for m in code_modules)
    remotes = remotes or {}
    if not isinstance(remotes, dict):
        raise ValueError("Remote contract must be a name -> type mapping")
    confirmed = [
        row for row in (observed_model_runs or [])
        if isinstance(row, dict)
        and row.get("model_mode") == "real_local_llama_cpp_not_mock"
        and row.get("status") in {
            "verified", "build_or_runtime_failed", "plan_failed",
            "source_only_not_studio_verified",
        }
        and row.get("complete_game_verified") in {True, False}
        and expected_input_fingerprint is not None
        and row.get("input_fingerprint") == expected_input_fingerprint
    ]
    # Full-game success requires a real Studio result. The CI cannot
    # establish the completion probability without these matched-run data.
    completed = sum(row["status"] == "verified"
                    and row["complete_game_verified"] is True for row in confirmed)
    warnings: list[str] = []
    if facet_count == 0:
        warnings.append("no_source_anchored_facets")
    if code_count == 0:
        warnings.append("no_model_authored_code_modules")
    if remotes and (client == 0 or server == 0):
        warnings.append("remote_without_client_or_server_role")
    if len(remotes) > max(code_count, 1):
        warnings.append("many_remotes_relative_to_modules")
    if code_count >= 14:
        warnings.append("many_sequential_model_outputs_compound_risk")
    if any(m.get("file_path", "").endswith(".server.luau")
           for m in code_modules):
        warnings.append("server_scripts_must_be_normalized_to_requireable_modules")
    if not confirmed:
        warnings.append("no_calibrated_real_model_e2e_success_rate")

    return {
        "schema": "rmm/generation-forecast-v1",
        "request_excerpt": requested_prompt[:400],
        "model": "UNSPECIFIED; no inference performed by this forecast",
        "source_counts": {
            "feature_count": facet_count,
            "generated_module_count": code_count,
            "generated_server_count": server,
            "generated_client_count": client,
            "remote_count": len(remotes),
            "minimum_sequential_model_completions": facet_count + code_count,
            "maximum_if_each_planner_and_coder_task_retries_three_times":
                3 * (facet_count + code_count),
            "planner_output_token_cap_per_facet": 5000,
            "coder_output_token_cap_per_module": 6000,
        },
        "measured_full_game_model_runs": {
            "count": len(confirmed),
            "verified_completed": completed,
            "matching_input_fingerprint": expected_input_fingerprint,
            "empirical_completion_rate": (
                completed / len(confirmed) if confirmed else None),
            "limitations": ("Not an accuracy estimate without matching "
                            "identical prompt, model, quantization, runtime and toolchain. "
                            "A single run or CI fixture is not statistically reliable."),
        },
        "scenarios": [
            {
                "name": row.name,
                "assumed_pass_per_facet": row.per_facet_design,
                "assumed_pass_per_module": row.per_module_code,
                "assumed_assembly_static_pass": row.assembly_and_static,
                "single_attempt_through_static_build": scenario_success(
                    facet_count, code_count, row),
                "optimistic_if_all_three_attempts_were_independent": scenario_success(
                    facet_count, code_count, row, independent_retry_attempts=3),
            }
            for row in SCENARIOS
        ],
        "warnings": warnings,
        "interpretation": (
            "Illustrative independent-stage sensitivity ONLY. These values are "
            "not a calibrated MiMo success forecast and exclude unmeasured "
            "Roblox Studio/multiplayer/persistence verification. Systematic "
            "errors correlate across retries; retries should not be treated "
            "as independent unless supported by experiment."),
    }
