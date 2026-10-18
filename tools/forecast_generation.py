"""Inspect planned MiMo workload and print *hypothetical*, not measured, success rates.

Example:
  python tools/forecast_generation.py \
    --proposal .rmm-space-assembly/proposal.json \
    --output .rmm-space-assembly/generation_forecast.json

Accepts the exact saved proposal.json from MRM. No model is invoked here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roblox_mod_ai.generation_forecast import forecast_generation


def forecast_proposal(path: Path, *,
                      receipts: list[dict] | None = None,
                      fingerprint: str | None = None) -> dict:
    proposal = json.loads(path.read_text(encoding="utf-8"))
    design = proposal.get("game_design", {})
    research = design.get("pre_design_research") or {}
    dynamic = design.get("dynamic_design") or {}
    ledger = research.get("ledger") or {}
    if not ledger.get("requirements"):
        raise ValueError("Source-anchored ledger missing; refusing invented feature count")
    return forecast_generation(
        requested_prompt=proposal["requested_prompt"],
        ledger=ledger, modules=proposal.get("modules", []),
        remotes=dynamic.get("remotes") or {},
        observed_model_runs=receipts,
        expected_input_fingerprint=fingerprint,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-run-receipt", type=Path, action="append",
                        default=[], help="A real_model_e2e_receipt.json from MiMo execution")
    parser.add_argument("--input-fingerprint",
                        help="Require exactly the same prompt/model/decoding settings "
                             "for every measured run; read it from a model receipt")
    args = parser.parse_args()
    if args.model_run_receipt and not args.input_fingerprint:
        parser.error("--input-fingerprint is required to compare actual model runs")
    observations = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.model_run_receipt
    ]
    result = forecast_proposal(
        args.proposal,
        receipts=observations, fingerprint=args.input_fingerprint,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(
            result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "source_counts": result["source_counts"],
        "empirical_real_model_completion_rate": result[
            "measured_full_game_model_runs"]["empirical_completion_rate"],
        "hypothetical_single_attempt_rates": {
            row["name"]: round(row["single_attempt_through_static_build"], 6)
            for row in result["scenarios"]
        },
        "warnings": result["warnings"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
