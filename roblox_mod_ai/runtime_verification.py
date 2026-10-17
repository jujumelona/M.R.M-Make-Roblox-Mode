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
    """Build -> explicit isolated test-place upload -> actual engine execution.

    A server-side smoke test is not an actual multiplayer client interaction test.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def run(self, proposal: RobloxProposal, place_file: Path) -> dict:
        key = os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY")
        universe = os.environ.get("ROBLOX_TEST_UNIVERSE_ID")
        place = os.environ.get("ROBLOX_TEST_PLACE_ID")
        if not all((key, universe, place)) or os.environ.get("RMM_ALLOW_TEST_PLACE_PUBLISH") != "1":
            return {"passed": False, "executed": False,
                    "reason": "Real engine test requires an isolated test place, API key, and RMM_ALLOW_TEST_PLACE_PUBLISH=1"}
        pub = RobloxOpenCloudClient(api_key=key).publish_place(universe, place, place_file, version_type="Published")
        if not pub.get("success") or not pub.get("version_number"):
            return {"passed": False, "executed": False, "reason": "Test place publish failed", "publish": pub}
        version = pub["version_number"]
        base = f"https://apis.roblox.com/cloud/v2/universes/{universe}/places/{place}/versions/{version}"
        url = base + "/luau-execution-session-tasks"
        headers = {"x-api-key": key, "Content-Type": "application/json"}
        session = self.client or httpx.Client(timeout=30)
        try:
            res = session.post(url, json={"script": make_smoke_script(proposal)}, headers=headers)
            res.raise_for_status()
            task = res.json()
            path = task.get("path", "")
            if not path.startswith(f"universes/{universe}/places/{place}/"):
                return {"passed": False, "executed": False, "reason": "Invalid task path"}
            deadline = time.monotonic() + 120
            while task.get("state") in ("QUEUED", "PROCESSING", "STATE_UNSPECIFIED") and time.monotonic() < deadline:
                time.sleep(2)
                response = session.get("https://apis.roblox.com/cloud/v2/" + path, headers=headers)
                response.raise_for_status()
                task = response.json()
            results = task.get("output", {}).get("results", [])
            passed = task.get("state") == "COMPLETE" and results == [True]
            return {"passed": passed, "executed": task.get("state") not in ("QUEUED", "PROCESSING"),
                    "state": task.get("state"), "results": results, "task_path": path,
                    "test_place_version": version, "scope": "server_smoke_and_datastore_only"}
        except (httpx.HTTPError, ValueError) as exc:
            return {"passed": False, "executed": False, "reason": str(exc)}
        finally:
            if self.client is None:
                session.close()
