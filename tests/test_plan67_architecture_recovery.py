"""Regression: source-verified architecture recovery must unblock codegen safely.

An original source chunk is not 'classified' merely because a placeholder
exists. It may be recovered only when the original facet/requirement IDs and
current authoritative server module + acceptance independently re-certify it.
"""
from roblox_mod_ai.implementation_blueprint import build_implementation_blueprint
from roblox_mod_ai.spec import (
    RobloxProposal, RobloxModuleSpec, RobloxService, ModuleKind,
)


def _proposal():
    server = RobloxModuleSpec(
        module_id="dyn_pet", name="PetHatchService",
        description=(
            "Server validates the player hatch request, charges the egg "
            "inventory and grants the hatched pet to the player."
        ),
        kind=ModuleKind.SERVER_SCRIPT,
        file_path="src/server/PetHatchService.server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
    )
    source = "펫 부화"
    ledger = {
        "requirements": [{"id": "req-001", "statement": source}],
        "facets": [{
            "id": "pets", "requirements": ["req-001"],
            "source_span": source,
        }],
        "atomic_intents": [{
            "chunk_id": "chunk-001", "source_span": source,
            "facet_id": "pets", "requirement_id": "req-001",
            "intent": "Implement only original source",
            "english_query": "Roblox gameplay scripting",
            "classification_origin": "architecture_source_verified",
        }],
        "classification_unverified": ["chunk-001"],
        "architecture_recovered_chunks": ["chunk-001"],
        "unimplemented_facets": [],
        "unmatched_requirements": [],
        "decomposition_pending": [],
    }
    dyn = {
        "module_facets": {"dyn_pet": ["pets"]},
        "module_requirements": {"dyn_pet": ["req-001"]},
        "acceptance": {
            "req-001": "The egg disappears and the owned pet appears.",
        },
        "acceptance_facets": {
            "pets": "The egg disappears and the owned pet appears.",
        },
    }
    return RobloxProposal(
        requested_prompt=source, game_title="PetTest", description="fixture",
        modules=[server],
        game_design={
            "features": {}, "dynamic_design": dyn,
            "storage_backend": "builtin",
            "pre_design_research": {"ledger": ledger},
        },
    )


def test_architecture_recertified_chunk_not_blocked_as_unknown():
    proposal = _proposal()
    blueprint = build_implementation_blueprint(proposal)
    assert not any(
        issue.startswith("unclassified_gameplay_requirements")
        for issue in blueprint["blocking_issues"]
    ), blueprint["blocking_issues"]


def test_forged_recovery_marker_does_not_silently_unblock_codegen():
    proposal = _proposal()
    ledger = proposal.game_design["pre_design_research"]["ledger"]
    ledger["atomic_intents"][0]["classification_origin"] = "host_source_only"
    blueprint = build_implementation_blueprint(proposal)
    assert not blueprint["ready_for_codegen"]
    assert any(
        "SOURCE_ARCHITECTURE_RECOVERY_INVALID" in issue
        for issue in blueprint["blocking_issues"]
    )
    assert any(
        "unclassified_gameplay_requirements" in issue
        for issue in blueprint["blocking_issues"]
    )
