"""Plan42: failure artifacts identify the actual *loaded* reviewer implementation.

Timestamp/HEAD alone cannot prove the Colab kernel imported the latest code.
"""
import hashlib
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai import source_review


def test_policy_fingerprint_matches_installed_validator_files():
    identity = source_review._policy_fingerprint()
    assert identity["policy"] == source_review.REVIEW_POLICY
    assert set(identity["source_sha256"]) == {
        "source_review.py", "source_finding_adjudication.py",
        "source_repair_cycle.py"}
    for name, value in identity["source_sha256"].items():
        actual = Path(source_review.__file__).parent / name
        assert value == hashlib.sha256(actual.read_bytes()).hexdigest()


def test_disabled_review_still_reports_loaded_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_AI_SOURCE_REVIEW", "0")
    proposal = SimpleNamespace(
        game_design={}, modules=[], requested_prompt="Build a space game")
    result = source_review.review_generated_sources(
        proposal, tmp_path, object())
    assert result["status"] == "not_run"
    assert not result["fully_covered"]
    assert result["review_code_provenance"]["source_sha256"]
    assert result["review_code_provenance"]["policy"] == source_review.REVIEW_POLICY
