"""Prompt-independent guards for scope-omission false positives."""
from pathlib import Path
from types import SimpleNamespace

from roblox_mod_ai.effect_scope_reconciliation import (
    already_planned_action, reconcile_omitted_actions,
)
from roblox_mod_ai.requirement_completion_audit import (
    _obligations, audit_whole_requirement_completion,
)


WEAPON_PLAN = {
    "server_state_changes": [
        "The equipped weapon's damage multiplier, fire rate, and magazine "
        "size are updated and persisted in server-owned data. "
        "The buyer's owned funds decrease by the server price and the crew's "
        "performance state increases. The spaceship's performance state is "
        "upgraded and the buyer's owned currency is debited by the server-priced cost. "
        "The buyer's owned currency balance decreases by the weapon upgrade price, "
        "and the weapon upgrade is added to their inventory."
    ]
}
DUPLICATE = "The weapon upgrade is purchased and added to the player's inventory"


def test_log17_exact_failure_is_a_duplicate_of_the_existing_effects():
    effects = _obligations(WEAPON_PLAN)
    assert len(effects) >= 8
    assert already_planned_action(DUPLICATE, effects)
    missing, duplicates = reconcile_omitted_actions([DUPLICATE], effects)
    assert missing == []
    assert duplicates == [DUPLICATE]


def test_missing_independent_addition_remains_a_real_omission():
    effects = _obligations({"server_state_changes": [
        "Buyer currency balance decreases by the weapon upgrade price",
    ]})
    assert not already_planned_action(DUPLICATE, effects)


def test_purchase_of_one_entity_cannot_borrow_inventory_write_of_another():
    effects = _obligations({"server_state_changes": [
        "Buyer currency balance decreases by the ship purchase price",
        "The weapon upgrade is added to the player's inventory",
    ]})
    assert not already_planned_action(
        "The ship is purchased and added to the player's inventory", effects,
    )


def test_inverse_mutation_and_unrelated_actions_remain_blocking():
    effects = _obligations({"server_state_changes": [
        "The ship section is added to the player's inventory",
        "The crew member gains a performance level",
    ]})
    assert not already_planned_action(
        "The ship section is removed from the player's inventory", effects)
    assert not already_planned_action(
        "The crew member is purchased and added to the inventory", effects)


def test_trade_sale_is_not_a_purchase_of_inventory():
    effects = _obligations({"server_state_changes": [
        "The seller's currency increases by the server price",
        "The seller's inventory decreases after a successful sale",
    ]})
    assert not already_planned_action(
        "A weapon is purchased and added to the seller inventory", effects)


def _integration_proposal(root: Path):
    path = "src/server/GenericUpgradeServer.luau"
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        "state.currency -= 5\nstate.weaponInventory += 1\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        modules=[SimpleNamespace(name="GenericUpgradeServer", file_path=path)],
        game_design={"detailed_implementation_plan": {"required_functions": [{
            "id": "req-purchase",
            "original_request": "Buy equipment upgrades and add them to inventory",
            "owner_files": [path],
            "server_state_changes": [
                "The buyer's currency decreases by the weapon upgrade price",
                "The weapon upgrade is added to the player's inventory",
            ],
        }]}}
    ), path


def test_real_audit_does_not_fail_from_duplicate_omission(tmp_path, monkeypatch):
    import roblox_mod_ai.requirement_completion_audit as audit
    proposal, path = _integration_proposal(tmp_path)
    def witnessed(router, effect, sources, modules, **kwargs):
        is_add = "added" in effect["behavior"]
        line = 2 if is_add else 1
        quote = "state.weaponInventory += 1" if is_add else "state.currency -= 5"
        return {
            "verdict": "implemented", "file": path, "line": line,
            "quote": quote, "issue": "none", "repair": "none",
        }, {"stage": "host_witness_fallback", "status": "source_witness_selected"}
    monkeypatch.setattr(audit, "_fallback_effect_witness_review", witnessed)
    class Router:
        def complete_json(self, **kwargs):
            assert kwargs["prompt"].startswith("Find user-requested")
            return {"missing_actions": [DUPLICATE]}
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(), host_witness_only=True,
    )
    assert report["fully_covered"], report
    assert report["status"] == "reviewed_no_blockers", report
    assert any(
        x.get("status") == "duplicates_in_existing_effect_ledger"
        for x in report.get("recovery", [])
    )


def test_real_audit_still_blocks_a_new_unplanned_behavior(tmp_path, monkeypatch):
    import roblox_mod_ai.requirement_completion_audit as audit
    proposal, path = _integration_proposal(tmp_path)
    def witnessed(router, effect, sources, modules, **kwargs):
        is_add = "added" in effect["behavior"]
        return {
            "verdict": "implemented", "file": path,
            "line": 2 if is_add else 1,
            "quote": "state.weaponInventory += 1" if is_add else "state.currency -= 5",
            "issue": "none", "repair": "none",
        }, {"stage": "host_witness_fallback", "status": "source_witness_selected"}
    monkeypatch.setattr(audit, "_fallback_effect_witness_review", witnessed)
    class Router:
        def complete_json(self, **kwargs):
            return {"missing_actions": [
                "A crew member is purchased and added to the player's roster"
            ]}
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Router(), host_witness_only=True,
    )
    assert not report["fully_covered"], report
    assert report["unplanned_actions"], report
    assert "original request omitted" in report["reason"]
