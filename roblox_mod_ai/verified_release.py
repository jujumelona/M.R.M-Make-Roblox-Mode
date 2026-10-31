"""Strict Colab delivery gate: every deliverable is from an actually tested place.

Offline builds remain useful intermediate artifacts; only an authenticated
Open Cloud server-engine PASS permits a *server-verified* final ZIP. Real client
multiplayer and Studio remain explicitly pending. Revision may only address
observed failure and may not change the source request or requirement ledger.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from .quality_gates import make_artifact_manifest
from .project_generator import RobloxProjectGenerator
from .runtime_verification import OpenCloudRuntimeVerifier


def _ledger(reply: Any) -> tuple[str, tuple[tuple[str, str], ...]]:
    p = reply.authored_plan.proposal
    ls = ((p.game_design or {}).get("pre_design_research") or {}).get("ledger") or {}
    requirements = tuple((row["id"], row["statement"])
                         for row in ls.get("requirements", [])
                         if isinstance(row, dict) and
                         isinstance(row.get("id"), str) and
                         isinstance(row.get("statement"), str))
    return p.requested_prompt, requirements


def run_verified_release(
    session: Any, plan_reply: Any, *, run_name: str,
    max_rebuilds: int = 2, verifier: Any = None,
) -> dict[str, Any]:
    """Generate, test server runtime, repair/rebuild, verify and THEN release.

    No artifact is labelled final if test access is unavailable, a task failed,
    the exact place hash changed, or the source requirement ledger drifted.
    """
    if type(max_rebuilds) is not int or not 0 <= max_rebuilds <= 3:
        raise ValueError("max_rebuilds must be 0..3")
    oracle = verifier if verifier is not None else OpenCloudRuntimeVerifier()
    origin = _ledger(plan_reply)
    if not origin[1]:
        # A missing original ledger means no way to prove a revision preserved
        # the source request. The usual offline builder is still available.
        return {"verified": False, "release_status": "missing_request_ledger",
                "final_zip": "", "attempts": [], "failure_report": ""}
    attempts: list[dict[str, Any]] = []
    active = plan_reply
    previous_hashes: set[str] = set()
    failure_report = ""
    for attempt in range(max_rebuilds + 1):
        if not active.ready_to_build or _ledger(active) != origin:
            return {"verified": False, "release_status": "plan_drift_or_not_ready",
                    "final_zip": "", "attempts": attempts,
                    "failure_report": failure_report}
        result = session.build(active, run_name=f"{run_name}-gate-{attempt}")
        out = Path(result.project_dir)
        out.mkdir(parents=True, exist_ok=True)
        if not result.success or not result.rbxlx_path:
            entry = {"attempt": attempt, "status": "offline_build_failed",
                     "source_failures": result.metadata.get("errors", []),
                     "failure_logs_zip": result.metadata.get("failure_logs_zip", "")}
            attempts.append(entry)
            failure_report = _save_failure(out, attempts)
            # The standard compiler already owns its bounded source repair
            # loop. Replanning cannot safely cure an unbuilt or partial Place.
            break
        place_file = Path(result.rbxlx_path)
        place_digest = hashlib.sha256(place_file.read_bytes()).hexdigest()
        if place_digest in previous_hashes:
            attempts.append({"attempt": attempt, "status": "unchanged_failed_place",
                             "place_sha256": place_digest})
            failure_report = _save_failure(out, attempts)
            break
        previous_hashes.add(place_digest)
        try:
            report = oracle.run(active.authored_plan.proposal, place_file)
        except Exception as error:
            report = {"passed": False, "executed": False,
                      "status": "engine_runner_failed",
                      "reason": type(error).__name__}
        # A checked engine PASS requires the exact same compiled file digest,
        # server execution, and an opaque task path tied to the uploaded
        # version. Never accept a false positive or a simulated test pass.
        verified = (report.get("passed") is True
                    and report.get("executed") is True
                    and report.get("state") == "COMPLETE"
                    and report.get("results") == [True]
                    and report.get("place_sha256") == place_digest
                    and isinstance(report.get("task_path"), str)
                    and "/luau-execution-sessions/" in report["task_path"])
        # Missing configuration or an unexecuted Cloud request is not a
        # failed gameplay run. Preserve this distinction in every receipt.
        if verified:
            outcome = "engine_passed"
        elif report.get("status") == "verification_setup_required":
            outcome = "verification_setup_required"
        elif report.get("executed") is not True:
            outcome = "engine_not_executed"
        else:
            outcome = "engine_failed"
        entry = {"attempt": attempt, "status": outcome,
                 "place_sha256": place_digest, "engine": report}
        attempts.append(entry)
        (out / "cloud_engine_report.json").write_text(
            json.dumps({"schema": "rmm/engine-release-gate-v1",
                        "verified": verified, "attempts": attempts,
                        "studio_multiplayer_verified": False},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        if verified:
            (out / "artifact_manifest.json").write_text(json.dumps(
                make_artifact_manifest(out, place_file),
                indent=2, ensure_ascii=False), encoding="utf-8")
            final = Path(result.project_zip_path).with_name(
                Path(result.project_zip_path).stem + "_SERVER_ENGINE_VERIFIED.zip")
            RobloxProjectGenerator(out.parent).pack_project_zip(out, final)
            with zipfile.ZipFile(final) as z:
                if (hashlib.sha256(z.read("compiled_place.rbxlx")).hexdigest()
                        != place_digest or "cloud_engine_report.json" not in z.namelist()):
                    raise RuntimeError("Engine-tested Place and final ZIP mismatch")
            return {"verified": True,
                    "release_status": "server_engine_verified_studio_pending",
                    "final_zip": str(final), "place": str(place_file),
                    "attempts": attempts, "failure_report": ""}
        failure_report = _save_failure(out, attempts)
        # A credential or environment problem is NOT a defect in generated
        # gameplay. Never ask the model to rewrite a perfectly good game
        # because API permissions or the test universe are missing.
        if report.get("executed") is not True or attempt == max_rebuilds:
            break
        reason = str(report.get("reason", ""))[:1200]
        logs = str(report.get("engine_logs", ""))[:2000]
        # The exact requested features remain mandatory after every revision.
        try:
            active = session.revise(
                "Revise implementation ONLY for the actual Roblox server engine "
                "failure below. Preserve the ORIGINAL request ledger, all "
                "effects and all unaffected systems. Never bypass an assertion, "
                "change the verifier, remove a feature, or claim Studio success. "
                f"Engine error: {reason}\nEngine diagnostics: {logs}")
        except Exception as error:
            attempts.append({"attempt": attempt,
                             "status": "engine_repair_unavailable",
                             "error_type": type(error).__name__})
            failure_report = _save_failure(out, attempts)
            break
    status = ("verification_setup_required"
              if any(entry.get("status") == "verification_setup_required"
                     for entry in attempts)
              else "engine_verification_incomplete")
    return {"verified": False, "release_status": status,
            "final_zip": "", "attempts": attempts, "failure_report": failure_report}


def _save_failure(folder: Path, attempts: list[dict[str, Any]]) -> str:
    report = folder / "cloud_verification_failure.json"
    report.write_text(json.dumps({"verified": False, "attempts": attempts},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    path = folder.parent / (folder.name + "_cloud_verification_failure.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(report, report.name)
    return str(path)
