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
