"""Real failure-13: 9B repeats an invalid sale Luau body and invalid ship
section design JSON. Run a first-party sale and a bounded, clearly audited
host-design fallback only after a proven builder/launcher link.
"""
from types import SimpleNamespace as NS

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.host_resource_market_sale import (
    eligible_resource_market_sale, render_resource_market_sale,
)
from roblox_mod_ai.host_ship_attachment import try_ship_attachment
from roblox_mod_ai.vehicle_identity_binding import bind_verified_vehicle_providers
from roblox_mod_ai.generation_scope import (
    generation_scope, assert_prompt_invariant_routing,
)
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer

from test_plan84_source_linked_ship_actor_provider import sample


SALE_DESC = (
    "When the authenticated player requests a resource sale, the server "
    "verifies the selected owned resource, positive quantity, stock and "
    "server-owned market price. On acceptance it atomically deducts the sold "
    "resource inventory and credits earned money to that same player's "
    "authoritative currency balance; invalid, duplicate and insufficient-stock "
    "requests change neither balance."
)


def with_sale():
    p, builder, ui, launch, launch_ui = sample(terse=True)
    owner = NS(name="OwnedResourceMarketSaleServer", module_id="dyn_sale",
               file_path="src/server/OwnedResourceMarketSaleServer.luau",
               kind=ModuleKind.SERVER_MODULE, description=SALE_DESC)
    client = NS(name="OwnedResourceMarketSaleClient", module_id="dyn_sale_ui",
                file_path="src/client/OwnedResourceMarketSaleClient.client.luau",
                kind=ModuleKind.CLIENT_SCRIPT,
                description="Host generates market UI inputs")
    p.modules.extend([owner, client])
    d = p.game_design["dynamic_design"]
    d["source_action_authorizations"] = {
        "earned_resource_market": True, "peer_asset_exchange": False,
    }
    d["host_actions"]["ResourceSale"] = {
        "service": owner.name, "kind": "RemoteFunction", "max_args": 1}
    d["remotes"]["ResourceSale"] = "RemoteFunction"
    d["module_remotes"][owner.module_id] = ["ResourceSale"]
    d["module_remotes"][client.module_id] = ["ResourceSale"]
    d["module_world_objects"][owner.module_id] = ["ResourceNode11"]
    d["module_world_objects"][client.module_id] = ["ResourceNode11"]
    d["host_typed_actions"]["ResourceSale"] = {
        "server": owner.name, "client": client.name, "transport_only": True,
        "world_entities": [],
        "contract": {
            "inputs": [
                {"id": "selection", "type": "text"},
                {"id": "quantity", "type": "integer", "min": 1, "max": 10000},
            ],
            "target": {"kind": "none"}, "state_changes": [],
        },
    }
    return p, owner, client


class NoCodeModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Never ask 9B for server/client Luau market code")

    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Never ask 9B for any sale implementation")


class InvalidCatalog:
    def __init__(self):
        self.calls = 0

    def complete_json(self, *_args, **_kwargs):
        self.calls += 1
        return {"sections": [
            {"id": "엔진!", "label": "엔진", "cost": -1, "performance": 9999}
        ]}


def test_real_market_description_compiles_as_host_server_client_not_typed_llm():
    p, owner, client = with_sale()
    assert eligible_resource_market_sale(owner, p) == (owner.name, "ResourceSale")
    assert eligible_resource_market_sale(client, p) == (owner.name, "ResourceSale")
    scope = generation_scope(p)
    by_name = {r["name"]: r["strategy"] for r in scope["modules"]}
    assert by_name[owner.name] == by_name[client.name] == "host_resource_market_sale"
    assert_prompt_invariant_routing(p, original_scope=scope)
    gen = LuauCodeGenerator(NoCodeModel())
    server = gen.generate_with_self_correction(owner, p)
    ui = gen.generate_with_self_correction(client, p)
    assert "inventory.resources = resources - quantity" in server
    assert "coins.Value = balance + payout" in server
    assert "PRICE_PER_RESOURCE = 1" in server
    assert "quantity > 10000" in server
    assert 'payload.selection ~= "resources"' in server
    assert '"RMMInventory"' in server
    assert "lastSale" not in server
    assert "GetState(player, \"RMMMarketPrices\")" not in server
    assert 'selection = "resources", quantity = quantity' in ui
    assert ':InvokeServer(' in ui
    for mod, code in ((owner, server), (client, ui)):
        problems = [e for e in LuauStaticAnalyzer().analyze_source(
            code, mod.file_path) if e.severity == "ERROR"]
        assert not problems, [(x.rule, x.message) for x in problems]


def test_sale_refused_without_source_authorization_or_real_miner():
    p, owner, client = with_sale()
    d = p.game_design["dynamic_design"]
    d["source_action_authorizations"] = {
        "earned_resource_market": False, "peer_asset_exchange": False}
    assert render_resource_market_sale(owner, p) is None
    d["source_action_authorizations"]["earned_resource_market"] = True
    d["module_world_objects"]["dyn_mine"] = []
    assert render_resource_market_sale(owner, p) is None


def test_client_cannot_claim_unpaired_market_or_change_price():
    p, owner, client = with_sale()
    d = p.game_design["dynamic_design"]
    d["host_typed_actions"]["ResourceSale"]["contract"]["inputs"].append(
        {"id": "unitPrice", "type": "integer"}
    )
    assert render_resource_market_sale(owner, p) is None
    d["host_typed_actions"]["ResourceSale"]["contract"]["inputs"].pop()
    d["module_remotes"][client.module_id] = ["OtherRemote"]
    assert render_resource_market_sale(client, p) is None


def test_two_invalid_section_catalogs_become_cached_and_audited_host_defaults():
    p, builder, client, launch, launch_ui = sample(terse=True)
    assert bind_verified_vehicle_providers(p)
    model = InvalidCatalog()
    server = try_ship_attachment(builder, p, model)
    ui = try_ship_attachment(client, p, model)
    assert model.calls == 2
    assert '["Hull"]' in server and '["Engine"]' in server
    assert '["Cabin"]' in server
    assert '"Hull"' in ui and '"Cabin"' in ui
    rows = p.game_design["_host_ship_attachment_catalogs"][builder.name]
    assert [row["id"] for row in rows] == ["Hull", "Engine", "Cabin"]
    evidence = p.game_design["_host_catalog_recoveries"]
    assert len(evidence) == 1
    assert evidence[0]["not_user_specified"] is True
    assert evidence[0]["source"] == "verified_launch_assembly_host_default"
    assert evidence[0]["previous_data_error"]
    assert "GetOwnedActor" in server
    assert "VehicleSeat" in server
    assert not [e for e in LuauStaticAnalyzer().analyze_source(
        server, builder.file_path) if e.severity == "ERROR"]


def test_invalid_catalog_outside_verified_flight_contract_still_fails():
    import pytest
    p, builder, _, launch, _ = sample(terse=True)
    p.game_design["dynamic_design"]["host_world_motion"].clear()
    model = InvalidCatalog()
    # Direct catalog authoring retains strict failure for unverified source.
    from roblox_mod_ai.host_ship_attachment import _catalog
    with pytest.raises(ValueError, match="HOST_SHIP_ATTACHMENT_CATALOG_EXHAUSTED"):
        _catalog(p, builder.name, model)
    assert model.calls == 2
