"""Convert a copied Roblox Studio Output log into a bound, reviewable receipt.

The log must contain RMM_STUDIO_E2E_RESULT emitted by the RMM plugin after
actual StudioTestService runs. Conversion does not independently authenticate
that log or execute Roblox; it never upgrades any failed check to success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MARKER = "RMM_STUDIO_E2E_RESULT"


def receipt_from_log(log: str, release_place: Path, test_place: Path) -> dict:
    matches = re.findall(r"RMM_STUDIO_E2E_RESULT\s+(\{[^\r\n]+\})", log)
    if not matches:
        raise ValueError("No StudioTestService result marker found in supplied log")
    payload = json.loads(matches[-1])
    required = ("client_server", "coin_pickup", "shop_purchase", "datastore_restore")
    if payload.get("runner") != "StudioTestService" or any(
        payload.get("checks", {}).get(name) is not True for name in required
    ):
        raise ValueError("Studio test result does not contain all passing checks")
    release = Path(release_place)
    test = Path(test_place)
    if not release.is_file() or not test.is_file():
        raise FileNotFoundError("Both compiled release and instrumented Studio test places are required")
    return {
        "runner": "StudioTestService",
        "checks": {name: True for name in required},
        "place_sha256": hashlib.sha256(release.read_bytes()).hexdigest(),
        "studio_test_place_sha256": hashlib.sha256(test.read_bytes()).hexdigest(),
        "evidence_type": "local_studio_output",
        "warning": "Locally self-attested output; only genuine StudioTestService runs count",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio-log", type=Path, required=True)
    parser.add_argument("--release-place", type=Path, required=True)
    parser.add_argument("--studio-place", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("studio_receipt.json"))
    args = parser.parse_args()
    data = receipt_from_log(
        args.studio_log.read_text(encoding="utf-8"),
        args.release_place, args.studio_place,
    )
    args.output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Studio receipt written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
