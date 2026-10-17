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
        """Generate truthful TestEZ structural checks, never fake math-based gameplay tests.

        These tests inspect actual instance/service presence WHEN executed in Roblox.
        They are not a substitute for Studio multiplayer side-effect verification.
        """
        features = proposal.game_design.get("features", {})
        cases: list[tuple[str, str, str, list[tuple[str, str]]]] = [
            (
                "Network",
                "NetworkRemotes",
                "tests/Network.spec.luau",
                [
                    ("ReplicatedStorage", "Remotes"),
                    ("ReplicatedStorage", "Shared"),
                ],
            ),
        ]
        if features.get("is_coin_collect"):
            cases.append((
                "CoinCollection",
                "CoinCollector",
                "tests/CoinCollection.spec.luau",
                [
                    ("Workspace", "Coins"),
                    ("ServerScriptService", "CoinCollector"),
                ],
            ))
        if features.get("is_shop"):
            cases.append((
                "Shop",
                "ShopService",
                "tests/Shop.spec.luau",
                [
                    ("Workspace", "ShopStalls"),
                    ("ServerScriptService", "ShopService"),
                ],
            ))
        if features.get("is_combat"):
            cases.append((
                "Combat",
                "CombatSystem",
                "tests/Combat.spec.luau",
                [
                    ("Workspace", "CombatArena"),
                    ("ReplicatedStorage", "Remotes"),
                    ("ServerScriptService", "CombatSystem"),
                ],
            ))
        if features.get("is_obby"):
            cases.append(("Obby", "ObbyService", "tests/Obby.spec.luau",
                          [("Workspace", "Checkpoints"), ("ServerScriptService", "ObbyService")]))
        if features.get("is_tycoon"):
            cases.append(("Tycoon", "TycoonService", "tests/Tycoon.spec.luau",
                          [("Workspace", "TycoonPlots"), ("ServerScriptService", "TycoonService")]))
        if features.get("is_simulator"):
            cases.append(("Simulator", "SimulatorService", "tests/Simulator.spec.luau",
                          [("Workspace", "SellZones"), ("ServerScriptService", "SimulatorService")]))

        specs: list[RobloxTestSpec] = []
        for name, target, path, requirements in cases:
            lines = [
                "--!strict",
                "-- Structural presence only. NEVER interpreted as gameplay or DataStore proof.",
                "return function()",
                f'    describe("{name} instance presence", function()',
            ]
            for service, child in requirements:
                lines.extend([
                    f'        it("has {service}.{child}", function()',
                    f'            local service = game:GetService("{service}")',
                    f'            expect(service:FindFirstChild("{child}") ~= nil).to.equal(true)',
                    "        end)",
                ])
            lines.extend(["    end)", "end", ""])
            specs.append(RobloxTestSpec(
                test_id="test_" + name.lower(),
                name=name + " instance presence (NOT gameplay)",
                target_module=target,
                file_path=path,
                test_code="\\n".join(lines),
            ))
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
