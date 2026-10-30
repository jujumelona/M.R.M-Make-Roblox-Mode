"""Prevent plan 94's false AUTHORITY_PRODUCER_NOT_DECLARED replan loop.

All eligibility gates remain active. The authenticated user's source
permissions must be bound BEFORE the authority checker selects host code.
"""
from copy import deepcopy

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.authority_architecture_repair import inspect_authority_design
from roblox_mod_ai.request_semantics import source_action_authorizations
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_resource_market_sale import eligible_resource_market_sale
from roblox_mod_ai.model_action_authority import unproven_model_actions
from test_plan86_market_sale_and_ship_catalog import with_sale

SOURCE = ("우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
          "부위마다 만들어서 만들수있고")


def _plan_without_early_permissions():
    proposal, sale, client = with_sale()
    raw = deepcopy(proposal.game_design["dynamic_design"])
    raw.pop("source_action_authorizations", None)
    raw["modules"] = list(proposal.modules)
    return raw, sale, client


def test_early_source_contract_is_bound_before_preflight(monkeypatch):
    raw, sale, client = _plan_without_early_permissions()
    assert raw.get("source_action_authorizations") is None
    monkeypatch.setattr("roblox_mod_ai.dynamic_architect.dynamic_design_enabled",
                        lambda: True)
    monkeypatch.setattr("roblox_mod_ai.dynamic_architect.implementation_facets",
                        lambda ledger: [{"id": "source-1"}])
    def fake_scoped(self, prompt, research, existing):
        # Models and the scoped architect never provide source permissions;
        # the HOST binds immutable permissions at the design boundary.
        return deepcopy(raw)
    monkeypatch.setattr(RobloxDynamicArchitect,
                        "_design_by_facets", fake_scoped)
    architect = RobloxDynamicArchitect(router=object())
    compiled = architect.design(
        SOURCE, {"ledger": {"requirements": []}}, [],
    )
    assert compiled["source_action_authorizations"] == source_action_authorizations(SOURCE)
    assert compiled["source_action_authorizations"]["earned_resource_market"] is True
    assert compiled["source_action_authorizations"]["peer_asset_exchange"] is False

    # Proven source authorizations now travel into the very FIRST preview,
    # rather than appearing only after replan_unproven_authority completes.
    assert not any(
        x.get("module") == sale.name
        for x in inspect_authority_design(compiled, [], requested_prompt=SOURCE)
    )


def test_generic_sale_still_fails_closed_without_authorization_or_miner():
    proposal, sale, _ = with_sale()
    design = proposal.game_design["dynamic_design"]
    design["source_action_authorizations"]["earned_resource_market"] = False
    assert eligible_resource_market_sale(sale, proposal) is None
    design["source_action_authorizations"]["earned_resource_market"] = True
    design["module_world_objects"]["dyn_mine"] = []
    assert eligible_resource_market_sale(sale, proposal) is None


def test_host_produced_sale_is_not_a_transport_only_model_obligation():
    proposal, sale, _ = with_sale()
    scope = generation_scope(proposal)
    route = next(x for x in scope["modules"] if x["name"] == sale.name)
    assert route["strategy"] == "host_resource_market_sale"
    assert not any(x.get("module") == sale.name
                   for x in unproven_model_actions(proposal, scope))
