"""Real Roblox Open Cloud execution verifier. No simulated success is possible."""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from .open_cloud import RobloxOpenCloudClient
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
    return "--!strict\n" + "\n".join(checks) + "\nreturn true\n"


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
        max_polls: int = 90,
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
            create = session.post(url, json={"script": make_smoke_script(proposal)}, headers=headers)
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
                    return {
                        "passed": passed, "executed": True,
                        "state": state, "results": results,
                        "task_path": path, "test_place_version": version,
                        "scope": "server_smoke_and_datastore_only",
                        "reason": "ok" if passed else str(
                            task.get("error", "Task did not return exactly [true]")
                        ),
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
