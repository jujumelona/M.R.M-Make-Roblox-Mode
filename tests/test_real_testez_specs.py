"""Spec files must never contain fake gameplay assertions."""
from roblox_mod_ai.planner import RobloxGameDesignPlanner


def test_generated_testez_specs_only_check_real_instances():
    proposal = RobloxGameDesignPlanner().plan(
        "코인 수집, 상점 시스템, 리더보드가 포함된 검투 아레나"
    ).proposal
    specs = {s.target_module: s for s in proposal.tests}
    for system in ("CoinCollector", "ShopService", "CombatSystem"):
        assert system in specs
        assert "FindFirstChild" in specs[system].test_code
        assert "NOT gameplay" in specs[system].name
    joined = "\\n".join(s.test_code for s in proposal.tests)
    assert "baseHealth - damage" not in joined
    assert "simulatedDistance > maxReach" not in joined
    assert "maxRetries).to.equal(maxRetries)" not in joined
