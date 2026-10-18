"""Real GGUF->source->Rojo test runner. Never substitutes a canned model.

Usage:
  python tools/run_real_model_e2e.py --prompt-file request.txt --output rmm-e2e
  python tools/run_real_model_e2e.py --prompt-file request.txt --source-only

Connect to an already running llama.cpp model. In Colab, session creation
can start the notebook-owned model runtime. The receipt deliberately separates
plan validity, source checks, Rojo compilation and real Studio execution.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

import httpx

from roblox_mod_ai.api import CompleteRobloxAISession


def run(prompt: str, output: Path, *, source_only: bool = False,
        resume_plan: bool = False) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt: dict = {
        "schema": "rmm/real-local-model-e2e-v1",
        "model_mode": "real_local_llama_cpp_not_mock",
        "complete_game_verified": False,
        "plan_passed": False, "source_static_passed": False,
        "rojo_compiled": False, "studio_runtime_passed": False,
        "status": "starting", "failures": [],
    }
    start = time.monotonic()
    receipt_path = output / "real_model_e2e_receipt.json"

    def write() -> dict:
        receipt["elapsed_seconds"] = round(time.monotonic() - start, 2)
        receipt_path.write_text(json.dumps(
            receipt, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        return receipt

    try:
        # Real-only: deliberately never use the CI's LocalGameModel fixture.
        session = CompleteRobloxAISession(output_root=output)
        adapter = session.router.get_adapter_for_role("coder")
        endpoint = adapter.base_url
        receipt["model_endpoint"] = endpoint
        try:
            with httpx.Client(timeout=8) as client:
                response = client.get(endpoint.rstrip("/") + "/models")
                response.raise_for_status()
                models = response.json().get("data", [])
            if not isinstance(models, list) or not models:
                raise RuntimeError("Local model endpoint returned no loaded model")
        except Exception as exc:
            raise RuntimeError("Real local model is not ready at " + endpoint +
                               ": " + str(exc)) from exc
        receipt["model_loaded"] = True
        if resume_plan:
            planned = session.load_plan()
        else:
            if not prompt.strip():
                raise ValueError("A concrete game prompt is required")
            planned = session.plan(prompt)
        receipt["plan_path"] = str(output / "proposal.json")
        receipt["plan_passed"] = bool(planned.ready_to_build)
        receipt["plan_modules"] = len(planned.authored_plan.proposal.modules)
        receipt["original_request_requirements"] = len(
            planned.authored_plan.proposal.game_design.get(
                "pre_design_research", {}).get("ledger", {}).get("requirements", []))
        receipt["facets_unimplemented"] = (
            planned.authored_plan.proposal.game_design.get("pre_design_research", {})
            .get("ledger", {}).get("unimplemented_facets", []))
        write()
        if not planned.ready_to_build:
            receipt["status"] = "plan_failed"
            receipt["failures"].append("Planning did not cover source requirements")
            return write()

        result = session.build(source_only=source_only)
        # RobloxPipelineResult has no .errors field. The authoritative
        # failures live in the work receipt's per-stage error/diagnostic
        # records; an AttributeError here previously destroyed real E2E
        # reporting after an otherwise successful build attempt.
        stage_receipt = result.work_receipt.to_dict()
        receipt["production_stages"] = stage_receipt["stages"]
        receipt["production_errors"] = [
            {"stage": entry["stage"],
             "errors": entry.get("errors", []),
             "details": entry.get("details", {})}
            for entry in stage_receipt["stages"]
            if not entry.get("success")
        ]
        receipt["project_dir"] = result.project_dir
        receipt["failure_logs_zip"] = result.metadata.get("failure_logs_zip")
        receipt["checks"] = result.metadata.get("acceptance", {}).get("checks", [])
        receipt["source_static_passed"] = bool(
            result.analysis_report.passed
            and result.metadata.get("acceptance", {}).get("passed"))
        receipt["tool_results"] = result.metadata.get("tool_results", {})
        receipt["rojo_compiled"] = bool(
            receipt["tool_results"].get("rojo", {}).get("success"))
        receipt["studio_runtime_passed"] = bool(
            result.metadata.get("runtime", {}).get("passed"))
        receipt["complete_game_verified"] = bool(result.success)
        if result.success:
            receipt["status"] = "verified"
        elif receipt["source_static_passed"] and source_only:
            receipt["status"] = "source_only_not_studio_verified"
        else:
            receipt["status"] = "build_or_runtime_failed"
        return write()
    except Exception as exc:
        receipt["status"] = "error"
        receipt["failures"].append(type(exc).__name__ + ": " + str(exc))
        receipt["traceback"] = traceback.format_exc()[-5000:]
        return write()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt-file", type=Path)
    group.add_argument("--prompt")
    group.add_argument("--resume-plan", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("rmm-real-e2e"))
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--model-url", help="Full llama.cpp OpenAI-compatible /v1 URL")
    args = parser.parse_args()
    if args.model_url:
        os.environ["ROBLOX_LLAMA_SERVER_URL"] = args.model_url.rstrip("/")
    os.environ["RMM_ENABLE_DYNAMIC_DESIGN"] = "1"
    os.environ["RMM_ENABLE_MODEL_GENERATION"] = "1"
    user_prompt = (args.prompt_file.read_text(encoding="utf-8")
                   if args.prompt_file else args.prompt or "")
    report = run(user_prompt, args.output, source_only=args.source_only,
                 resume_plan=args.resume_plan)
    print(json.dumps({
        "status": report["status"],
        "plan_passed": report["plan_passed"],
        "source_static_passed": report["source_static_passed"],
        "rojo_compiled": report["rojo_compiled"],
        "studio_runtime_passed": report["studio_runtime_passed"],
        "report": str(args.output / "real_model_e2e_receipt.json"),
    }, ensure_ascii=False))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
