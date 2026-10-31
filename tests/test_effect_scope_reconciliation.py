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
    proposal.game_design["detailed_implementation_plan"]["required_functions"][0][
        "original_request"
    ] += "; A crew member is purchased and added to the player's roster"
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


def test_audit_aggregates_plan_omission_and_other_unverified_effect(tmp_path, monkeypatch):
    """One failure receipt exposes the next blocker instead of serial reruns."""
    import roblox_mod_ai.requirement_completion_audit as audit
    proposal, path = _integration_proposal(tmp_path)
    proposal.game_design["detailed_implementation_plan"]["required_functions"][0][
        "original_request"
    ] += "; A crew member is purchased and added to the player's roster"
    proposal.game_design["detailed_implementation_plan"]["required_functions"].append({
        "id": "req-next",
        "original_request": "Implement another independent counter in owned state",
        "owner_files": [path],
        "server_state_changes": ["The owned independent counter increases persistently"],
    })
    def witnessed(router, effect, sources, modules, **kwargs):
        if "independent counter" in effect["behavior"]:
            return None, {
                "stage": "host_witness_fallback",
                "status": "unverified",
                "reason": "no_conclusive_source_witness",
            }
        is_add = "added" in effect["behavior"]
        return {
            "verdict": "implemented", "file": path,
            "line": 2 if is_add else 1,
            "quote": "state.weaponInventory += 1" if is_add else "state.currency -= 5",
            "issue": "none", "repair": "none",
        }, {"stage": "host_witness_fallback", "status": "source_witness_selected"}
    monkeypatch.setattr(audit, "_fallback_effect_witness_review", witnessed)
    class Reporter:
        def complete_json(self, **kwargs):
            assert kwargs["prompt"].startswith("Find user-requested")
            return {"missing_actions": [
                "A crew member is purchased and added to the player's roster"
            ]}
    report = audit_whole_requirement_completion(
        proposal, tmp_path, Reporter(), host_witness_only=True,
    )
    assert report["status"] == "failed"
    assert report["unplanned_actions"]
    assert report["unverified_effects"]
    assert "original request omitted" in report["reason"]
    assert "cannot prove 1 independent effects" in report["reason"]

def test_model_invents_ship_build_currency_and_inventory_gain(tmp_path):
    from roblox_mod_ai.effect_scope_reconciliation import (
        reconcile_original_scope_claims,
    )
    original = "Collect materials, trade for currency and assemble a vehicle."
    effects = _obligations({"server_state_changes": [
        "Accepted source extraction increases player inventory.",
        "Trade decreases resources and increases currency.",
        "Vehicle section builds consume materials and attach the section.",
    ]})
    claims = [
        "After building the vehicle section, the player's currency decreases by its price",
        "After building the vehicle section, their inventory increases by the consumed materials",
        "The player's built vehicle sections are attached to the vehicle",
    ]
    missing, duplicate, unverified = reconcile_original_scope_claims(
        claims, original, effects,
    )
    assert missing == []
    assert set(unverified + duplicate) == set(claims)


def test_new_literal_user_obligation_is_still_blocking():
    from roblox_mod_ai.effect_scope_reconciliation import (
        reconcile_original_scope_claims,
    )
    original = (
        "Build an automated tower; collect rare gems from the northern cave"
    )
    effects = _obligations({"server_state_changes": [
        "The tower is built from collected materials",
    ]})
    claims = ["collect rare gems from the northern cave"]
    missing, _, unverified = reconcile_original_scope_claims(
        claims, original, effects,
    )
    assert missing == claims
    assert unverified == []


def test_cross_language_unanchored_claim_is_not_authority():
    from roblox_mod_ai.effect_scope_reconciliation import (
        reconcile_original_scope_claims,
    )
    effects = _obligations({"server_state_changes": [
        "The spacecraft physically launches into space",
    ]})
    missing, duplicates, unverified = reconcile_original_scope_claims(
        ["The player receives a free rocket and funds on launch"],
        "우주로 나갈 수 있다", effects,
    )
    assert not missing and not duplicates
    assert len(unverified) == 1
