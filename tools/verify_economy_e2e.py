"""CI: execute the exact generated EconomyLedger and kill unsafe mutations.

No local model or Roblox Studio required: Lune executes production Luau against
mock Roblox services. This checks actual ledger behavior, not full persistence.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from roblox_mod_ai.economy_core import render_economy_ledger
from roblox_mod_ai.spec import RobloxModuleSpec


def main() -> None:
    root = Path(".rmm-economy-e2e").resolve()
    root.mkdir(parents=True, exist_ok=True)
    module = RobloxModuleSpec(
        module_id="dyn_economy", name="EconomyLedger",
        kind="shared_module",
        file_path="src/server/EconomyLedger.luau",
        roblox_service="ServerScriptService",
        description="Server-authoritative currency ledger tracks player balances and credits",
    )
    source = render_economy_ledger(module)
    original = root / "EconomyLedger.luau"
    original.write_text(source, encoding="utf-8")
    mutations = (
        ("allow_overspending",
         "if not coins or coins.Value < amount then",
         "if not coins then"),
        ("disable_amount_validation",
         "if not validAmount(amount) then",
         "if false then"),
        ("ignore_integer_overflow",
         "if not coins or amount > 2147483647 - coins.Value then",
         "if not coins then"),
        ("reward_disconnected_players",
         "if player.Parent ~= Players then",
         "if false then"),
        ("wrong_purchase_direction",
         "coins.Value -= amount",
         "coins.Value += amount"),
        ("wrong_reward_direction",
         "coins.Value += amount",
         "coins.Value -= amount"),
    )

    def execute(file: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["lune", "run", "tests/economy_ledger_e2e"],
            env={**os.environ, "RMM_ECONOMY_SOURCE": str(file)},
            capture_output=True, text=True, timeout=40, check=False,
        )

    baseline = execute(original)
    assert baseline.returncode == 0, (
        "Real generated EconomyLedger did not pass Lune E2E:\n" +
        baseline.stdout + "\n" + baseline.stderr
    )
    print(baseline.stdout.strip())
    evidence = []
    for name, old, new in mutations:
        assert source.count(old) >= 1, (name, "mutation anchor missing")
        changed = source.replace(old, new, 1)
        mutant = root / (name + ".luau")
        mutant.write_text(changed, encoding="utf-8")
        run = execute(mutant)
        assert run.returncode != 0, (
            "Mutation was NOT detected by executable gameplay tests: " +
            name + "\n" + run.stdout + "\n" + run.stderr
        )
        evidence.append({"mutation": name, "killed": True,
                         "returncode": run.returncode})
        print("Killed unsafe ledger mutation:", name)
    receipt = {
        "schema": "rmm/economy-execution-mutation-v1",
        "model": "first-party generated Luau",
        "execution": "Lune with controlled Roblox API mocks; not Studio",
        "baseline_passed": True,
        "mutations_killed": len(evidence),
        "mutations_survived": 0,
        "mutations": evidence,
    }
    (root / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ECONOMY E2E + MUTATIONS PASS:", len(evidence))


if __name__ == "__main__":
    main()
