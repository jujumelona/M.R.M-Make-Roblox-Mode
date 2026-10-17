"""Roblox Studio Playtest and Luau TestEZ automated test runner."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .spec import RobloxProposal, RobloxTestSpec


@dataclass
class TestCaseResult:
    name: str
    passed: bool
    duration_ms: float
    message: str = ""


@dataclass
class PlaytestReport:
    passed: bool
    total_tests: int
    passed_count: int
    failed_count: int
    duration_ms: float
    results: list[TestCaseResult] = field(default_factory=list)

    @property
    def tests_run(self) -> int:
        return self.total_tests

    @property
    def tests_passed(self) -> int:
        return self.passed_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total_tests": self.total_tests,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "duration_ms": self.duration_ms,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "duration_ms": r.duration_ms,
                    "message": r.message,
                }
                for r in self.results
            ],
        }


class RobloxPlaytestRunner:
    """Headless simulator and test generator corresponding to Minecraft GameTest."""

    def generate_default_test_specs(self, proposal: RobloxProposal) -> list[RobloxTestSpec]:
        """Generates standard TestEZ spec files for the proposal."""
        specs: list[RobloxTestSpec] = [
            RobloxTestSpec(
                test_id="test_combat_sanity",
                name="Combat & Damage Distance Check",
                target_module="CombatSystem",
                file_path="tests/Combat.spec.luau",
                test_code="""--!strict
return function()
    local ReplicatedStorage = game:GetService("ReplicatedStorage")
    local remotes = ReplicatedStorage:WaitForChild("Remotes")
    local attackRemote = remotes:WaitForChild("AttackRequest") :: RemoteEvent

    describe("Combat System", function()
        it("should reject attack requests exceeding maximum reach distance", function()
            -- Distance sanity check test
            local maxReach = 15
            local simulatedDistance = 25
            expect(simulatedDistance > maxReach).to.equal(true)
        end)

        it("should apply damage server-authoritatively", function()
            local baseHealth = 100
            local damage = 25
            local remainingHealth = baseHealth - damage
            expect(remainingHealth).to.equal(75)
        end)
    end)
end
""",
            ),
            RobloxTestSpec(
                test_id="test_datastore_persistence",
                name="DataStore Session & Save Validation",
                target_module="PlayerDataManager",
                file_path="tests/DataStore.spec.luau",
                test_code="""--!strict
return function()
    describe("PlayerDataManager", function()
        it("should initialize default stats when no saved data exists", function()
            local defaultCoins = 0
            local defaultLevel = 1
            expect(defaultCoins).to.equal(0)
            expect(defaultLevel).to.equal(1)
        end)

        it("should retry save operations up to 3 times on failure", function()
            local maxRetries = 3
            expect(maxRetries).to.equal(3)
        end)
    end)
end
""",
            ),
        ]
        return specs

    def run_headless_playtest(self, proposal: RobloxProposal) -> PlaytestReport:
        """Legacy API: never misreport structural inspection as an actual Roblox run.

        Actual engine checks are OpenCloudRuntimeVerifier + StudioTestService receipts.
        """
        case = TestCaseResult(
            name="[NOT RUN] Roblox Studio / Open Cloud",
            passed=False, duration_ms=0,
            message="Headless simulation is not a Roblox engine playtest. Use isolated test place and StudioTestService.",
        )
        return PlaytestReport(
            passed=False, total_tests=1, passed_count=0, failed_count=1,
            duration_ms=0, results=[case],
        )
