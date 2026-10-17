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
                "-- Jest Roblox tests: structure only, not gameplay validation.",
                'local ReplicatedStorage = game:GetService("ReplicatedStorage")',
                'local JestGlobals = require(ReplicatedStorage:WaitForChild("DevPackages"):WaitForChild("JestGlobals"))',
                "local describe = JestGlobals.describe",
                "local it = JestGlobals.it",
                "local expect = JestGlobals.expect",
                f'describe("{name} instance presence", function()',
            ]
            for service, child in requirements:
                lines.extend([
                    f'    it("has {service}.{child}", function()',
                    f'        local service = game:GetService("{service}")',
                    f'        expect(service:FindFirstChild("{child}") ~= nil).toBe(true)',
                    "    end)",
                ])
            lines.extend(["end)", ""])
            specs.append(RobloxTestSpec(
                test_id="test_" + name.lower(),
                name=name + " Jest instance presence (NOT gameplay)",
                target_module=target,
                file_path=path,
                test_code=chr(10).join(lines),
            ))
        # The dynamic game still needs real Studio/Cloud behavior tests.
        # These generated Jest assertions establish only that new roles,
        # remotes and world objects exist in the actual Studio DataModel.
        dynamic = proposal.game_design.get("dynamic_design") or {}
        if dynamic:
            checks = [
                "--!strict",
                'local ReplicatedStorage = game:GetService("ReplicatedStorage")',
                'local JestGlobals = require(ReplicatedStorage:WaitForChild("DevPackages"):WaitForChild("JestGlobals"))',
                "local describe = JestGlobals.describe",
                "local it = JestGlobals.it",
                "local expect = JestGlobals.expect",
                'describe("Dynamic game object presence, not gameplay behavior", function()',
            ]
            for module in proposal.modules:
                if not module.module_id.startswith("dyn_"):
                    continue
                if module.file_path.startswith("src/server/"):
                    tree_expr='game:GetService("ServerScriptService")'
                elif module.file_path.startswith("src/client/"):
                    tree_expr='game:GetService("StarterPlayer"):WaitForChild("StarterPlayerScripts")'
                else:
                    tree_expr='ReplicatedStorage:WaitForChild("Shared")'
                checks += [
                    f'    it("includes {module.name}", function()',
                    f'        expect({tree_expr}:FindFirstChild("{module.name}") ~= nil).toBe(true)',
                    "    end)",
                ]
            for name, kind in dynamic.get("remotes", {}).items():
                checks += [
                    f'    it("declares {name} remote", function()',
                    '        local remotes = ReplicatedStorage:WaitForChild("Remotes")',
                    f'        local remote = remotes:FindFirstChild("{name}")',
                    f'        expect(remote ~= nil and remote:IsA("{kind}")).toBe(true)',
                    "    end)",
                ]
            for obj in dynamic.get("world_objects", []):
                name,kind=obj["name"],obj["class"]
                checks += [
                    f'    it("contains {name} world object", function()',
                    f'        local instance = workspace:FindFirstChild("{name}")',
                    f'        expect(instance ~= nil and instance:IsA("{kind}")).toBe(true)',
                    "    end)",
                ]
            checks.append("end)")
            specs.append(RobloxTestSpec(
                test_id="test_dynamic_structure", name="Novel mechanics Studio instance contract",
                target_module="DynamicGame", file_path="tests/DynamicStructure.spec.luau",
                test_code="\\n".join(checks),
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
