"""Prevent CI mocks from masquerading as real model success-rate evidence.

Source-count scenario forecasts are math under *explicit* assumptions, not
observed MiMo 9B full-game success estimates.
"""
from __future__ import annotations

import json
import math

import pytest

from roblox_mod_ai.generation_forecast import (
    StageAssumptions, forecast_generation, scenario_success, wilson_95_interval,
)
from tools.forecast_generation import forecast_proposal
from test_space_seven_facets_e2e import _user_space_ledger, _PROMPT, _SPACE


def test_space_game_14_modules_seven_facets_composes_21_model_decisions():
    ledger = _user_space_ledger()
    modules = [
        {"module_id": "dyn_" + stem + "_" + role,
         "name": stem + role,
         "file_path": ("src/server/" + stem + ".luau" if role == "server"
                       else "src/client/" + stem + ".client.luau")}
        for _, _, _, stem in _SPACE for role in ("server", "client")
    ]
    result = forecast_generation(
        requested_prompt=_PROMPT, ledger=ledger, modules=modules,
        remotes={stem + "Action": "RemoteEvent"
                 for _, _, _, stem in _SPACE},
    )
    counts = result["source_counts"]
    assert counts["feature_count"] == 7
    assert counts["generated_module_count"] == 14
    assert counts["generated_server_count"] == 7
    assert counts["generated_client_count"] == 7
    assert counts["remote_count"] == 7
    assert counts["minimum_sequential_model_completions"] == 21
    assert counts["maximum_if_each_planner_and_coder_task_retries_three_times"] == 63
    assert counts["planner_output_token_cap_per_facet"] == 5000
    assert counts["coder_output_token_cap_per_module"] == 6000
    assert result["measured_full_game_model_runs"]["empirical_completion_rate"] is None
    assert "no_calibrated_real_model_e2e_success_rate" in result["warnings"]
    for row in result["scenarios"]:
        expected = (
            row["assumed_pass_per_facet"] ** 7 *
            row["assumed_pass_per_module"] ** 14 *
            row["assumed_assembly_static_pass"]
        )
        assert row["single_attempt_through_static_build"] == pytest.approx(expected)
        assert (row["optimistic_if_all_three_attempts_were_independent"]
                >= row["single_attempt_through_static_build"])


def test_module_count_deteriorates_the_hypothetical_probability():
    conditions = StageAssumptions("illustrative_only", 0.90, 0.80, 0.90)
    for module_count in (14, 22):
        assert 0 < scenario_success(7, module_count, conditions) < 1
    assert scenario_success(7, 22, conditions) < scenario_success(7, 14, conditions)


def test_fictitious_ci_fixture_is_not_empirical_model_measurement():
    ledger = _user_space_ledger()
    fake = {"model_mode": "CI_deterministic_mock", "status": "verified",
            "complete_game_verified": True, "input_fingerprint": "mock"}
    result = forecast_generation(
        requested_prompt=_PROMPT, ledger=ledger, modules=[],
        observed_model_runs=[fake],
    )
    assert result["measured_full_game_model_runs"]["count"] == 0
    assert result["measured_full_game_model_runs"]["empirical_completion_rate"] is None


def test_untraceable_run_cannot_inflate_measured_rate():
    ledger = _user_space_ledger()
    report = {"model_mode": "real_local_llama_cpp_not_mock", "status": "verified",
              "complete_game_verified": True}
    result = forecast_generation(
        requested_prompt=_PROMPT, ledger=ledger, modules=[],
        observed_model_runs=[report],
    )
    assert result["measured_full_game_model_runs"]["count"] == 0


def test_observed_rate_uses_identical_input_fingerprint_only():
    ledger = _user_space_ledger()
    def receipt(fingerprint, status, completed):
        return {
            "model_mode": "real_local_llama_cpp_not_mock",
            "input_fingerprint": fingerprint,
            "status": status,
            "complete_game_verified": completed,
        }
    samples = [
        receipt("same-configuration", "verified", True),
        receipt("same-configuration", "build_or_runtime_failed", False),
        receipt("different-model-quantization", "verified", True),
        receipt("same-configuration", "error", False),  # model never finished request
        receipt("same-configuration", "source_only_not_studio_verified", False),
        {"model_mode": "CI_deterministic_mock",
         "input_fingerprint": "same-configuration",
         "status": "verified", "complete_game_verified": True},
    ]
    result = forecast_generation(
        requested_prompt=_PROMPT, ledger=ledger, modules=[],
        observed_model_runs=samples, expected_input_fingerprint="same-configuration",
    )
    observed = result["measured_full_game_model_runs"]
    assert observed["count"] == 2
    assert observed["verified_completed"] == 1
    assert observed["empirical_completion_rate"] == 0.5
    assert observed["approximate_95pct_wilson_interval"][0] < 0.5
    assert observed["approximate_95pct_wilson_interval"][1] > 0.5
    mismatched = forecast_generation(
        requested_prompt=_PROMPT, ledger=ledger, modules=[],
        observed_model_runs=samples, expected_input_fingerprint="unused",
    )
    assert mismatched["measured_full_game_model_runs"]["count"] == 0
    assert mismatched["measured_full_game_model_runs"]["empirical_completion_rate"] is None


def test_intervals_cannot_disguise_zero_or_tiny_model_run_samples():
    assert wilson_95_interval(0, 0) is None
    assert wilson_95_interval(0, 10)[1] > 0.25
    assert wilson_95_interval(0, 20)[1] > 0.16
    assert wilson_95_interval(10, 10)[0] < 0.75
    with pytest.raises(ValueError):
        wilson_95_interval(4, 3)


def test_invalid_probabilities_rejected_and_retries_do_not_claim_calibration():
    for p in (-0.1, 1.1, math.nan, math.inf):
        with pytest.raises(ValueError):
            StageAssumptions("bad", p, .8, .8)
    result = forecast_generation(
        requested_prompt=_PROMPT, ledger=_user_space_ledger(), modules=[],
    )
    assert "not a calibrated MiMo success forecast" in result["interpretation"]


def test_cli_refuses_unattributed_requirements_and_reads_saved_proposal(tmp_path):
    file = tmp_path / "proposal.json"
    file.write_text(json.dumps({
        "requested_prompt": _PROMPT,
        "game_design": {"pre_design_research": {"ledger": _user_space_ledger()},
                        "dynamic_design": {"remotes": {"MiningAction": "RemoteEvent"}}},
        "modules": [{"module_id": "dyn_mining", "name": "Mining",
                     "file_path": "src/server/Mining.luau"}],
    }, ensure_ascii=False), encoding="utf-8")
    assert forecast_proposal(file)["source_counts"]["feature_count"] == 7
    file.write_text(json.dumps({
        "requested_prompt": _PROMPT,
        "game_design": {"pre_design_research": {}, "dynamic_design": {}},
        "modules": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Source-anchored ledger missing"):
        forecast_proposal(file)
