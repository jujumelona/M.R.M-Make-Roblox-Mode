"""Run the uploaded proposal-35 request against a REAL local GGUF backend.

No deterministic fixture or mock transport. Plan -> code generation -> true
StyLua/Selene/Rojo compilation. Studio engine remains separately unverified.
Execute on a Colab GPU after installing the RMM repo/dependencies or on a
machine with a running llama-server and a real Rojo/Luau toolchain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

SPACE_REQUEST = (
    "우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을  부위마다 "
    "만들어서 만들수있고 무기 선원 우주선 성능을 거래 구매 등으로 "
    "업그레이드 확장 할 수 있고 그렇게해서 우주로 나갈수있고 "
    "우주로 나가면 다른행성의 특수 광물  외게인과 싸움 "
    "식민지화등 여러가지가 가능한 모드"
)


def _run_tool(tool: str, *args: str, cwd: Path) -> dict:
    binary = shutil.which(tool)
    if not binary:
        raise RuntimeError("REQUIRED_REAL_TOOL_MISSING: " + tool)
    process = subprocess.run(
        [binary, *args], cwd=cwd, capture_output=True, text=True,
        timeout=180, check=False,
    )
    result = {
        "tool": tool, "returncode": process.returncode,
        "stdout_tail": process.stdout[-3000:],
        "stderr_tail": process.stderr[-4000:],
    }
    if process.returncode:
        raise RuntimeError("REAL_TOOL_FAILED " + tool + ": " +
                           process.stderr[-2500:] + process.stdout[-1500:])
    return result


def run(output_root: Path, prompt: str = SPACE_REQUEST) -> dict:
    # Do not let the stock prefab route convert this request into an
    # unrelated arena, or switch to the deterministic testing transport.
    os.environ.update({
        "RMM_ENABLE_DYNAMIC_DESIGN": "1",
        "RMM_ENABLE_MODEL_DECOMPOSITION": "1",
        "RMM_ENABLE_MODEL_GENERATION": "1",
        "RMM_ENABLE_MODEL_QUERY_EXPANSION": "0",
        "RMM_PREDESIGN_LIVE_SEARCH": "0",
        "RMM_SOURCE_FIDELITY_AUDIT": "1",
        "ROBLOX_MOD_AI_ALLOW_OFFLINE_FALLBACK": "0",
    })
    from roblox_mod_ai.api import CompleteRobloxAISession
    from roblox_mod_ai.model_adapters import LlamaCppAdapter

    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipt_path = root / "real_model_space_e2e_receipt.json"
    receipt: dict = {
        "schema": "rmm/real-model-space-e2e-v1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "requested_prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "backend": "local GGUF / llama.cpp",
        "fake_model_used": False,
        "real_model_inference": False,
        "architecture_accepted": False,
        "generated_module_count": 0,
        "static_checks_passed": False,
        "rojo_place_compiled": False,
        "studio_gameplay_verified": False,
        "studio_status": "not_run",
        "status": "failed",
        "steps": [],
    }

    def save() -> None:
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    save()
    try:
        # Colab starts MiMo 9B here; elsewhere a live llama.cpp server MUST
        # already be configured. Do not create a synthetic adapter.
        session = CompleteRobloxAISession(
            output_root=root, model_profile="t4_local")
        adapter = session.router.get_adapter_for_role("planner")
        if type(adapter) is not LlamaCppAdapter:
            raise RuntimeError("REAL_BACKEND_REQUIRED: expected LlamaCppAdapter")
        response = session.router.complete(
            "Reply with one short word: ready.", max_tokens=24, temperature=0.0)
        if not response.strip():
            raise RuntimeError("REAL_MODEL_PROBE_EMPTY")
        receipt["real_model_inference"] = True
        receipt["model_id"] = os.environ.get("RMM_MODEL_ID", "local-gguf")
        receipt["model_endpoint"] = (
            os.environ.get("ROBLOX_LLAMA_SERVER_URL")
            or os.environ.get("RMM_MODEL_BASE_URL") or "http://127.0.0.1:8080/v1"
        )
        receipt["model_probe_finish_reason"] = (
            session.router.last_generation_report.get("finish_reason"))
        receipt["steps"].append("real_llama_cpp_completion")
        save()

        reply = session.plan(prompt, force_replan=True)
        research = reply.authored_plan.proposal.game_design.get(
            "pre_design_research", {})
        ledger = research.get("ledger", {})
        receipt["architecture_attempts"] = research.get(
            "architecture_attempts", [])
        receipt["architecture_recovered_chunks"] = ledger.get(
            "architecture_recovered_chunks", [])
        receipt["unverified_chunks"] = ledger.get(
            "classification_unverified", [])
        receipt["provider_failures"] = research.get("provider_failures", [])
        receipt["architecture_accepted"] = bool(reply.ready_to_build)
        save()
        if not reply.ready_to_build:
            raise RuntimeError(
                "REAL_MODEL_PLAN_NOT_READY: see plan_failure_logs.zip and receipt")
        receipt["steps"].append("real_model_architecture_accepted")
        save()

        result = session.build(reply, run_name="real-model-space", source_only=True)
        receipt["static_checks_passed"] = bool(
            result.success and result.analysis_report.passed
            and result.metadata.get("acceptance", {}).get("passed"))
        receipt["release_status"] = result.metadata.get("release_status")
        project = Path(result.project_dir)
        dynamic_modules = [
            module for module in reply.authored_plan.proposal.modules
            if module.module_id.startswith("dyn_")
        ]
        receipt["generated_module_count"] = len(dynamic_modules)
        receipt["generated_file_evidence"] = [{
            "module": module.name, "path": module.file_path,
            "size": (project / module.file_path).stat().st_size,
            "sha256": hashlib.sha256(
                (project / module.file_path).read_bytes()).hexdigest(),
        } for module in dynamic_modules if (project / module.file_path).is_file()]
        save()
        if not receipt["static_checks_passed"]:
            raise RuntimeError("REAL_MODEL_GENERATION_FAILED_STATIC_ACCEPTANCE")
        if len(receipt["generated_file_evidence"]) != len(dynamic_modules):
            raise RuntimeError("MODEL_MODULE_SOURCE_MISSING")

        # Enforce actual external tools. Syntactic Python checks and XML
        # fixture generation do not count as compilation.
        receipt["compiler_checks"] = [
            _run_tool("stylua", "--check", "src", cwd=project),
            _run_tool("selene", "src", cwd=project),
            _run_tool("rojo", "build", "default.project.json",
                      "-o", "real-model-space.rbxlx", cwd=project),
        ]
        place = project / "real-model-space.rbxlx"
        if not place.is_file() or place.stat().st_size < 2000:
            raise RuntimeError("REAL_MODEL_PLACE_NOT_COMPILED")
        from roblox_mod_ai.rbxlx_inspector import inspect_compiled_place
        inspection = inspect_compiled_place(
            reply.authored_plan.proposal, place, source_root=project)
        receipt["compiled_place_inspection"] = inspection
        if not inspection["passed"]:
            raise RuntimeError("REAL_PLACE_INSPECTION_FAILED")
        receipt["rojo_place_compiled"] = True
        receipt["place_path"] = str(place)
        receipt["place_sha256"] = hashlib.sha256(place.read_bytes()).hexdigest()
        receipt["steps"].append("real_stylua_selene_rojo_compilation")
        receipt["status"] = "offline_build_passed_studio_not_run"
    except Exception as exc:
        receipt["error"] = type(exc).__name__ + ": " + str(exc)[:4000]
        receipt["traceback_tail"] = traceback.format_exc()[-6500:]
    finally:
        receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".rmm-live-space",
                        help="Persistent plan, source and evidence directory")
    parser.add_argument("--prompt-file", type=Path,
                        help="UTF-8 plain text of another user request")
    args = parser.parse_args()
    prompt = (args.prompt_file.read_text(encoding="utf-8").strip()
              if args.prompt_file else SPACE_REQUEST)
    receipt = run(Path(args.output), prompt)
    print(json.dumps({
        "status": receipt["status"],
        "real_model_inference": receipt["real_model_inference"],
        "architecture_accepted": receipt["architecture_accepted"],
        "static_checks_passed": receipt["static_checks_passed"],
        "rojo_place_compiled": receipt["rojo_place_compiled"],
        "studio_gameplay_verified": False,
        "error": receipt.get("error"),
    }, ensure_ascii=False, indent=2))
    return 0 if receipt["rojo_place_compiled"] else 1


if __name__ == "__main__":
    sys.exit(main())
