from pathlib import Path
import json
import pytest

from tools.make_studio_receipt import receipt_from_log, MARKER


def test_receipt_cannot_turn_failed_checks_into_success(tmp_path: Path):
    release = tmp_path / "compiled.rbxlx"
    studio = tmp_path / "studio-e2e.rbxlx"
    release.write_text("release", encoding="utf-8")
    studio.write_text("instrumented", encoding="utf-8")
    result = {"runner": "StudioTestService", "checks": {
        "jest_suites": True, "client_server": True, "coin_pickup": True,
        "shop_purchase": True, "datastore_restore": False,
    }}
    with pytest.raises(ValueError):
        receipt_from_log(MARKER + " " + json.dumps(result), release, studio)


def test_receipt_binds_release_and_test_hashes(tmp_path: Path):
    release = tmp_path / "compiled.rbxlx"
    studio = tmp_path / "studio-e2e.rbxlx"
    release.write_bytes(b"release")
    studio.write_bytes(b"instrumented")
    result = {"runner": "StudioTestService", "checks": {
        "client_server": True, "coin_pickup": True,
        "shop_purchase": True, "datastore_restore": True,
    }}
    output = receipt_from_log(MARKER + " " + json.dumps(result), release, studio)
    assert output["evidence_type"] == "local_studio_output"
    assert output["place_sha256"] != output["studio_test_place_sha256"]


def test_receipt_missing_marker_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        receipt_from_log('{"runner": "StudioTestService"}', tmp_path / "x", tmp_path / "y")
