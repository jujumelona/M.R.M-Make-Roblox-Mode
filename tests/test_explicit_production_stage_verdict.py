"""A missing status cannot mark code generation or packaging successful."""
import pytest

from roblox_mod_ai.orchestrator import explicit_stage_verdict


@pytest.mark.parametrize("invalid", [
    None, True, {}, {"module_order": ["foo"]},
    {"success": 1}, {"passed": "true"},
    {"success": True, "passed": False},
    {"success": None, "passed": True},
])
def test_missing_or_conflicting_stage_status_fails_closed(invalid):
    with pytest.raises(ValueError, match="STAGE_RESULT"):
        explicit_stage_verdict(invalid)


def test_explicit_stage_success_and_failure_remain_distinct():
    assert explicit_stage_verdict({"success": True}) is True
    assert explicit_stage_verdict({"passed": True}) is True
    assert explicit_stage_verdict({"success": False, "error": "real compiler failure"}) is False
    assert explicit_stage_verdict({"success": True, "passed": True}) is True
