"""Real Roblox Open Cloud execution verifier. No simulated success is possible."""
from __future__ import annotations

import os
import time
import hashlib
from pathlib import Path

import httpx

from .open_cloud import RobloxOpenCloudClient
from .cloud_engine_suite import make_engine_suite_script, engine_contract_checks
from .spec import RobloxProposal


def make_smoke_script(proposal: RobloxProposal) -> str:
    """Checks real instances and persistent storage on an isolated TEST place."""
    flags = proposal.game_design.get("features", {})
    checks = [
        'assert(game:GetService("ServerScriptService"):FindFirstChild("PlayerDataManager"), "missing player data")',
        'assert(game:GetService("ReplicatedStorage"):WaitForChild("Remotes"), "missing remotes")',
    ]
    if flags.get("is_coin_collect"):
        checks.append('assert(workspace:FindFirstChild("Coins") and #workspace.Coins:GetChildren() > 0, "missing coins")')
        checks.append('assert(game:GetService("ServerScriptService"):FindFirstChild("CoinCollector"), "missing pickup handler")')
    if flags.get("is_shop"):
        checks.append('assert(workspace:FindFirstChild("ShopStalls"), "missing shop")')
        checks.append('assert(game:GetService("ReplicatedStorage").Remotes:FindFirstChild("ShopPurchase"), "missing ShopPurchase")')
        checks.append('assert(game:GetService("StarterPlayer").StarterPlayerScripts:FindFirstChild("ShopController"), "missing shop client")')
    if flags.get("is_combat"):
        checks.append('assert(workspace:FindFirstChild("CombatArena"), "missing arena")')
    checks.append("""
local HttpService = game:GetService("HttpService")
local store = game:GetService("DataStoreService"):GetDataStore("RMM_VerificationOnly")
local key = "test_" .. HttpService:GenerateGUID(false)
local ok, err = pcall(function()
    store:SetAsync(key, {value=17})
    local result = store:GetAsync(key)
    assert(result and result.value == 17, "DataStore roundtrip mismatch")
    store:RemoveAsync(key)
end)
assert(ok, "DataStore test failed: " .. tostring(err))
""")
    # The model must never author the test oracle. Derive assertions from the
    # generated contract and run them in the actual uploaded Roblox DataModel.
    # Keep a separate test-only DataStore roundtrip as a distinct assertion.
    scripted = make_engine_suite_script(proposal)
    return (scripted.removesuffix("return true\n")
            + "do\n" + "\n".join(checks)
            + "\nend\nreturn true\n")

class OpenCloudRuntimeVerifier:
    """Publish an isolated test place and poll a *real* Roblox engine task.

    All network calls are injectable for contract testing. Fake HTTP responses
    never represent a successful live engine execution.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        publisher: object | None = None,
        poll_interval: float = 2.0,
        max_polls: int = 165,
    ) -> None:
        self.client = client
        self.publisher = publisher
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def run(self, proposal: RobloxProposal, place_file: Path) -> dict:
        key = os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY", "")
        universe = os.environ.get("ROBLOX_TEST_UNIVERSE_ID", "")
        place = os.environ.get("ROBLOX_TEST_PLACE_ID", "")
        missing = []
        if not key:
            missing.append("ROBLOX_OPEN_CLOUD_API_KEY")
        if not universe.isdecimal() or int(universe or "0") <= 0:
            missing.append("ROBLOX_TEST_UNIVERSE_ID")
        if not place.isdecimal() or int(place or "0") <= 0:
            missing.append("ROBLOX_TEST_PLACE_ID")
        if os.environ.get("RMM_ALLOW_TEST_PLACE_PUBLISH") != "1":
            missing.append("RMM_ALLOW_TEST_PLACE_PUBLISH=1")
        if missing:
            # The compiled project has not failed a Roblox engine test. No
            # engine test could start without a separate, explicitly approved
            # disposable test place. Never fake a pass or silently publish.
            return {
                "passed": False, "executed": False,
                "status": "verification_setup_required",
                "missing_requirements": missing,
                "reason": "Dedicated test Place ID, Universe ID, API key, and explicit publish opt-in required",
            }

        compiled = Path(place_file)
        if not compiled.is_file() or compiled.suffix.lower() not in (".rbxlx", ".rbxl"):
            return {"passed": False, "executed": False, "reason": "Compiled test place is missing"}

        publisher = self.publisher or RobloxOpenCloudClient(api_key=key)
        try:
            pub = publisher.publish_place(universe, place, compiled, version_type="Published")
        except Exception as exc:
            return {"passed": False, "executed": False, "reason": f"Test place publish exception: {type(exc).__name__}"}
        if not isinstance(pub, dict):
            return {
                "passed": False, "executed": False,
                "reason": "Test-place publisher returned a non-object response",
            }
        version = pub.get("version_number")
        if pub.get("success") is not True or not isinstance(version, (int, str)) or not str(version).isdecimal():
            return {
                "passed": False, "executed": False,
                "reason": "Test place publish did not return a valid version",
                "publish_status": pub.get("status_code") if isinstance(pub, dict) else None,
            }

        url = (
            f"https://apis.roblox.com/cloud/v2/universes/{universe}/places/{place}/"
            f"versions/{version}/luau-execution-session-tasks"
        )
        headers = {"x-api-key": key, "Content-Type": "application/json"}
        session = self.client or httpx.Client(timeout=30)
        prefix = f"universes/{universe}/places/{place}/versions/{version}/"
        try:
            script = make_smoke_script(proposal)
            script_digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
            place_digest = hashlib.sha256(compiled.read_bytes()).hexdigest()
            create = session.post(url, json={"script": script}, headers=headers)
            create.raise_for_status()
            task = create.json()
            if not isinstance(task, dict):
                return {"passed": False, "executed": False, "reason": "Invalid task response"}
            path = task.get("path")
            if not isinstance(path, str) or not path.startswith(prefix) or (
                "/luau-execution-sessions/" not in path or "/tasks/" not in path
            ) or "?" in path or "#" in path or ".." in path:
                return {"passed": False, "executed": False, "reason": "Invalid task resource path"}

            # The create endpoint may not supply state/output; ALWAYS fetch the task.
            task_url = "https://apis.roblox.com/cloud/v2/" + path
            state = "UNKNOWN"
            for attempt in range(self.max_polls):
                if attempt and self.poll_interval:
                    time.sleep(self.poll_interval)
                response = session.get(task_url, headers={"x-api-key": key})
                response.raise_for_status()
                task = response.json()
                if not isinstance(task, dict):
                    return {"passed": False, "executed": False, "reason": "Invalid polled task response"}
                state = task.get("state")
                if state in ("COMPLETE", "FAILED", "CANCELLED"):
                    output = task.get("output")
                    results = output.get("results") if isinstance(output, dict) else None
                    passed = state == "COMPLETE" and results == [True]
                    # Fetch actual failed engine logs, but never claim to have
                    # observed client/studio multiplayer or ingest untrusted
                    # log output as instructions.
                    runtime_logs = []
                    if not passed and (self.client is None or os.environ.get("RMM_FETCH_CLOUD_TASK_LOGS") == "1"):
                        try:
                            logs_res = session.get(task_url + "/logs",
                                headers={"x-api-key": key})
                            if logs_res.status_code == 200:
                                obj = logs_res.json()
                                if isinstance(obj, dict):
                                    # Official API returns luauExecutionSessionTaskLogs,
                                    # not a top-level "logs" array. Include structured
                                    # messages and flat messages for real repair evidence.
                                    records = obj.get("luauExecutionSessionTaskLogs", [])
                                    if isinstance(records, list):
                                        for row in records[:50]:
                                            if not isinstance(row, dict):
                                                continue
                                            for message in (row.get("structuredMessages") or [])[:150]:
                                                if isinstance(message, dict):
                                                    runtime_logs.append(str(message.get("message", ""))[:500])
                                            for message in (row.get("messages") or [])[:150]:
                                                if isinstance(message, str):
                                                    runtime_logs.append(message[:500])
                        except (httpx.HTTPError, ValueError, TypeError):
                            pass
                    safe_logs = str(runtime_logs)[:12000].replace(key, "[REDACTED]") if key else ""
                    return {
                        "passed": passed, "executed": True,
                        "state": state, "results": results,
                        "task_path": path, "test_place_version": version,
                        "place_sha256": place_digest,
                        "script_sha256": script_digest,
                        "contract_check_count": len(engine_contract_checks(proposal)),
                        "engine_logs": safe_logs,
                        "scope": "server_smoke_and_datastore_only",
                        "extended_scope": "server_datamodel_remotes_world_and_datastore_not_multiplayer",
                        "reason": "ok" if passed else str(
                            task.get("error", "Task did not return exactly [true]")
                        )[:3000].replace(key, "[REDACTED]"),
                    }
                if state not in ("QUEUED", "PROCESSING", "STATE_UNSPECIFIED"):
                    return {"passed": False, "executed": False, "state": state,
                            "reason": "Unexpected Roblox task state", "task_path": path}
            return {
                "passed": False, "executed": False, "state": state,
                "reason": "Roblox task poll limit reached",
                "task_path": path, "test_place_version": version,
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "passed": False, "executed": False,
                "reason": f"Roblox Cloud request failed: {type(exc).__name__}",
            }
        finally:
            if self.client is None:
                session.close()
