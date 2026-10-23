"""Allow bounded source-owned architecture recovery, but never approve omissions."""
from copy import deepcopy

from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.pre_design_research import build_request_ledger


def test_unknown_source_chunk_recovery_must_verify_actual_server_owners(monkeypatch, tmp_path):
    import roblox_mod_ai.planner as planning

    prompt = "Buy spaceship upgrades, then colonize another planet"
    ledger = build_request_ledger(prompt)
    ledger["decomposition_pending"] = []
    ledger["unimplemented_facets"] = ["intent-custom"]
    ledger["unmatched_requirements"] = []
    ledger["classification_unverified"] = ["chunk-007"]
    ledger["atomic_intents"] = [{
        "facet_id": "intent-custom", "requirement_id": ledger["requirements"][0]["id"],
        "source_span": ledger["requirements"][0]["statement"],
        "intent": "Implement only the requested gameplay",
        "english_query": "Roblox gameplay scripting for the source",
        "chunk_id": "chunk-007",
        "classification_origin": "host_source_only",
    }]
    ledger["facets"] = [{
        "id": "intent-custom",
        "requirements": [ledger["requirements"][0]["id"]],
        "implementation_key": None,
        "source_span": ledger["requirements"][0]["statement"],
        "search_query": "Roblox source game action",
    }]

    class StaticResearch:
        def research(self, request):
            assert request == prompt
            return deepcopy({
                "ledger": ledger, "status": "partial",
                "queries": [], "evidence": [], "asset_candidates": [],
                "provider_failures": [],
            })

    attempts = []
    def incomplete_architecture(*_args, **_kwargs):
        # The scoped designer is permitted to retry from immutable original
        # source, but empty gameplay modules must never become a runnable plan.
        attempts.append(True)
        return {
            "modules": [], "module_facets": {}, "module_requirements": {},
            "acceptance": {}, "acceptance_facets": {},
        }

    monkeypatch.setattr(planning, "dynamic_design_enabled", lambda: True)
    monkeypatch.setattr(planning.RobloxDynamicArchitect, "design", incomplete_architecture)
    designer = RobloxGameDesignPlanner(
        pre_design_research=StaticResearch(), output_root=tmp_path)
    authored = designer.plan(prompt)
    plan = authored.proposal
    assert not plan.game_design.get("dynamic_design")
    assert attempts == [True]
    failures = plan.game_design["pre_design_research"]["provider_failures"]
    assert any(f["facet"] == "dynamic_game_design"
               and "SOURCE_ARCHITECTURE_RECOVERY_FAILED" in f["reason"]
               and "chunk-007" in f["reason"] for f in failures)
    assert "chunk-007" in plan.game_design["pre_design_research"]["ledger"]["classification_unverified"]
    assert not plan.game_design["implementation_blueprint"]["ready_for_codegen"]
