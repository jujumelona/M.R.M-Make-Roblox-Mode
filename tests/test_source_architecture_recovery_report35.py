"""Regress report 35: one missing classifier must not erase all four game systems."""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.source_architecture_recovery import (
    SourceArchitectureRecoveryError, certify_unclassified_chunks,
)


SOURCE = "무기 선원 우주선 성능을 거래 구매 등으로 업그레이드 확장 할 수 있고"
FACET = "intent-source-crew-ship-weapon"
RID = "req-002"
CHUNK = "chunk-002"


def fixture(server_behavior=None, outcome=None):
    ledger = {
        "classification_unverified": [CHUNK],
        "atomic_intents": [{
            "chunk_id": CHUNK, "facet_id": FACET,
            "requirement_id": RID, "source_span": SOURCE,
            "classification_origin": "host_source_only",
        }],
    }
    server_behavior = server_behavior or (
        "Server validates weapon purchase, deducts earned currency and "
        "equips purchased weapons. Server validates crew hiring, deducts "
        "earned currency and records recruited crew. Server validates "
        "spaceship engine upgrade purchase, deducts earned currency and "
        "increases ship performance."
    )
    outcome = outcome or (
        "Weapons are equipped after purchase; crew is hired and assigned "
        "after payment; the ship engine performance is upgraded after purchase."
    )
    design = {
        "module_facets": {"dyn_purchase": [FACET]},
        "module_requirements": {"dyn_purchase": [RID]},
        "acceptance": {RID: outcome},
        "acceptance_facets": {FACET: outcome},
    }
    modules = [
        SimpleNamespace(
            module_id="dyn_purchase",
            kind=SimpleNamespace(value="server_module"),
            description=server_behavior,
        )
    ]
    return ledger, design, modules


def test_missing_classifier_recovered_only_by_source_owned_server_behavior():
    ledger, design, modules = fixture()
    assert certify_unclassified_chunks(ledger, design, modules) == [CHUNK]


def test_missing_crew_or_ship_upgrade_cannot_be_approved():
    ledger, design, modules = fixture(server_behavior=(
        "Server validates weapon purchase and equips the weapon. "
        "Server performs another weapon purchase and upgrades weapons."
    ))
    with pytest.raises(SourceArchitectureRecoveryError, match="crew"):
        certify_unclassified_chunks(ledger, design, modules)


def test_client_only_ownership_cannot_certify_gameplay():
    ledger, design, modules = fixture()
    modules[0].kind.value = "client_script"
    with pytest.raises(SourceArchitectureRecoveryError, match="server module"):
        certify_unclassified_chunks(ledger, design, modules)


def test_missing_per_requirement_acceptance_remains_blocked():
    ledger, design, modules = fixture()
    del design["acceptance"][RID]
    with pytest.raises(SourceArchitectureRecoveryError, match="requirement-specific"):
        certify_unclassified_chunks(ledger, design, modules)


def test_classifier_unknown_without_source_atom_is_not_claimed_implemented():
    ledger, design, modules = fixture()
    ledger["atomic_intents"] = []
    with pytest.raises(SourceArchitectureRecoveryError, match="source-owned"):
        certify_unclassified_chunks(ledger, design, modules)


def test_blueprint_admits_only_recertified_source_architecture_not_placeholder():
    """Report 35: planner recovery must also pass the NEXT codegen gate.

    The classifier never understood weapons, crew and ship purchases. A source
    owned design may replace its prose, but only while server effects and
    acceptance still satisfy the literal source requirement.
    """
    from roblox_mod_ai.implementation_blueprint import build_implementation_blueprint
    from roblox_mod_ai.spec import (
        ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
    )

    ledger, design, owners = fixture()
    ledger.update({
        "original_prompt": SOURCE,
        "requirements": [{"id": RID, "statement": SOURCE, "source": "user_prompt"}],
        "facets": [{"id": FACET, "requirements": [RID], "source_span": SOURCE}],
        "classification_unverified": [],
        "architecture_recovered_chunks": [CHUNK],
        "unimplemented_facets": [],
        "unmatched_requirements": [],
        "decomposition_pending": [],
    })
    atom = ledger["atomic_intents"][0]
    atom.update({
        "classification_origin": "architecture_source_verified",
        "intent": "Unclassified source: no meaningful English gameplay intent",
        "english_query": "Unknown unsupported generic game capability",
    })
    module = RobloxModuleSpec(
        module_id="dyn_purchase", name="GameplayPurchase",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/GameplayPurchase.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=owners[0].description,
    )
    proposal = RobloxProposal(
        requested_prompt=SOURCE, game_title="Report35", description="source recovery",
        modules=[module], game_design={
            "features": {}, "dynamic_design": design,
            "pre_design_research": {"ledger": ledger},
        },
    )
    accepted = build_implementation_blueprint(proposal)
    assert accepted["ready_for_codegen"], accepted["blocking_issues"]
    assert not any("classifier" in issue for issue in accepted["blocking_issues"])

    original = module.description
    module.description = "Server validates weapon purchase and equips a weapon."
    dropped = build_implementation_blueprint(proposal)
    assert not dropped["ready_for_codegen"]
    assert any("SOURCE_ARCHITECTURE_RECOVERY_INVALID" in item for item in
               dropped["blocking_issues"])
    module.description = original

    design["acceptance"][RID] = "The player buys and receives a weapon only."
    incomplete = build_implementation_blueprint(proposal)
    assert not incomplete["ready_for_codegen"]
    design["acceptance"][RID] = fixture()[1]["acceptance"][RID]

    atom["classification_origin"] = "host_source_only"
    forged = build_implementation_blueprint(proposal)
    assert not forged["ready_for_codegen"]
    assert any("SOURCE_ARCHITECTURE_RECOVERY_INVALID" in item for item in
               forged["blocking_issues"])
