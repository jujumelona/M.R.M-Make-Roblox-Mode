"""Manually triggered real Roblox Open Cloud smoke test for an isolated TEST place.

The caller must supply an already Rojo-compiled place file and a matching authored plan.
This command intentionally fails if Roblox credentials or test-place opt-in are missing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roblox_mod_ai.authored_plan import RobloxAuthoredPlan
from roblox_mod_ai.runtime_verification import OpenCloudRuntimeVerifier


def run(plan_path: Path, compiled_place: Path) -> dict:
    plan = RobloxAuthoredPlan.from_dict(json.loads(plan_path.read_text(encoding="utf-8")))
    return OpenCloudRuntimeVerifier().run(plan.proposal, compiled_place)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--place", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("cloud_smoke_report.json"))
    args = parser.parse_args()
    result = run(args.plan, args.place)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("results",)}, indent=2))
    return 0 if result.get("passed") and result.get("executed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
