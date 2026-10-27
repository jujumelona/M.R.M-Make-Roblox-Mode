"""Generic two-player barter must use host-owned asset and consent contracts."""
from types import SimpleNamespace
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_peer_barter import render_host_peer_barter
from roblox_mod_ai.request_semantics import source_action_authorizations
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService


class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Host transaction must not ask the model for invented APIs")


def make_plan():
    def mod(name, kind, description):
        return RobloxModuleSpec(
            module_id="dyn_" + name, name=name, kind=kind,
            file_path=("src/server/" + name + ".luau" if kind == ModuleKind.SERVER_MODULE
                       else "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=description, depends_on=[],
        )
    miner = mod("OreMiningEconomyServer", ModuleKind.SERVER_MODULE,
                "Server validates mining from resource nodes and credits earned currency.")
    trader = mod("PlayerAssetExchangeServer", ModuleKind.SERVER_MODULE,
                 "Server owns a trade exchange ledger. Validates two players' resource "
                 "and item balances for both sides and rejects stale exchanges.")
    client = mod("PlayerAssetExchangeClient", ModuleKind.CLIENT_SCRIPT,
                 "Client requests and accepts a mutually agreed trade offer.")
    design = {"world_objects": [{"name": "OreNode", "class": "Part"}],
              "source_action_authorizations": source_action_authorizations(
                  "Mine resources and barter items between players"),
              "host_actions": {
                  "OreMiningAction": {"service": miner.name, "kind": "RemoteFunction"},
                  "PlayerAssetExchangeAction": {
                      "service": trader.name, "kind": "RemoteFunction"}}}
    return trader, client, SimpleNamespace(modules=[miner, trader, client],
        requested_prompt="Mine resources and barter items between players",
        game_design={"dynamic_design": design})


def test_two_party_barter_uses_server_verified_host_source_without_model():
    server, client, plan = make_plan()
    generator = LuauCodeGenerator(router=NoModel())
    s = generator.generate_module_code(server, plan)
    c = generator.generate_module_code(client, plan)
    assert s == render_host_peer_barter(server, plan)
    assert c == render_host_gameplay(client, plan)
    assert 'GetState(player, "RMMInventory")' in s
    assert 'FindFirstChild("Coins")' in s
    assert 'offer.to ~= player.UserId' in s
    assert 'giverOut.amount < offer.giveQty' in s
    assert 'takerOut.amount < offer.wantQty' in s
    assert 'pending[a] = nil' in s
    assert 'setOwned(giverOut, giverOut.amount - offer.giveQty)' in s
    assert 'setOwned(takerIn, takerIn.amount + offer.giveQty)' in s
    assert 'return {success = true' in s
    assert 'remote:InvokeServer(table.unpack(args, 1, args.n))' in c
    assert '"list"' in c and '"accept"' in c and '"cancel"' in c
    assert 'reviewOffset = (reviewOffset % #response.pending) + 1' in c
    assert 'if reviewed == nil then' in c
    assert s.rstrip().endswith("return Service")


def test_peer_barter_does_not_invent_balances_without_mining_or_verified_route():
    server, client, plan = make_plan()
    plan.modules = [server, client]
    assert render_host_peer_barter(server, plan) is None
    _, _, plan = make_plan()
    plan.game_design["dynamic_design"]["host_actions"]["PlayerAssetExchangeAction"]["kind"] = "RemoteEvent"
    assert render_host_peer_barter(server, plan) is None
    _, _, plan = make_plan()
    plan.game_design["dynamic_design"]["host_actions"]["PlayerAssetExchangeAction"]["max_args"] = 0
    assert render_host_peer_barter(server, plan) is None


def test_peer_barter_rejects_single_sided_trade_or_unrelated_mechanics():
    server, client, plan = make_plan()
    server.description = "Sell one resource for credits at the world trading market."
    assert render_host_peer_barter(server, plan) is None
    server.description = "The server simulates two players in an arena battle."
    assert render_host_peer_barter(server, plan) is None



def test_bilateral_trade_never_collides_with_fixed_price_or_market_broker():
    server, client, plan = make_plan()
    server.name = "ResourceTradingExchangeServer"
    client.name = "ResourceTradingExchangeClient"
    server.description = (
        "A trade with a counterparty: both players validate each other's "
        "resource inventory and earned currency balances, then exchange "
        "agreed item quantities without accepting stale requests."
    )
    plan.game_design["dynamic_design"]["host_actions"]["PlayerAssetExchangeAction"]["service"] = server.name
    expected_server = render_host_peer_barter(server, plan)
    expected_client = render_host_peer_barter(client, plan)
    assert expected_server is not None and expected_client is not None
    assert render_host_gameplay(server, plan) == expected_server
    assert render_host_gameplay(client, plan) == expected_client


def test_unmatched_small_model_action_receives_actual_shared_economy_api():
    from roblox_mod_ai.host_service_codegen import try_scaffolded_server
    server, _, plan = make_plan()

    class CapturingCoder:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt, **_kwargs):
            self.prompts.append(prompt)
            return "invalid body -- no real mutation"

    router = CapturingCoder()
    result = try_scaffolded_server(server, plan, router, LuauStaticAnalyzer())
    assert result is None
    assert router.prompts
    assert all('GetState(player, "RMMInventory").resources' in p
               for p in router.prompts)
    assert all('player.leaderstats.Coins.Value' in p for p in router.prompts)
    assert all("Do NOT call nonexistent trading methods" in p
               for p in router.prompts)


def test_peer_barter_luau_static_analysis_for_both_roles():
    server, client, plan = make_plan()
    analyzer = LuauStaticAnalyzer()
    for mod in (server, client):
        code = render_host_peer_barter(mod, plan)
        errors = [d for d in analyzer.analyze_source(code, mod.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(e.rule, e.line_number, e.message) for e in errors]


def test_prompt_text_cannot_change_validated_barter_dispatch():
    from roblox_mod_ai.generation_scope import (
        generation_scope, assert_prompt_invariant_routing,
    )
    server, client, plan = make_plan()
    expected = (render_host_peer_barter(server, plan),
                render_host_peer_barter(client, plan))
    assert all(expected)
    # Regression: the production resolver previously failed because the
    # barter host reread the raw prompt, changing both source routes.
    scope = generation_scope(plan)
    assert_prompt_invariant_routing(plan, original_scope=scope)
    plan.requested_prompt = "[raw prompt withheld: use validated contracts]"
    assert (render_host_peer_barter(server, plan),
            render_host_peer_barter(client, plan)) == expected


def test_vague_trade_cannot_enable_peer_exchange_even_if_model_invents_it():
    server, client, plan = make_plan()
    plan.requested_prompt = "Mine resources, earn coins, trade, and build gear"
    plan.game_design["dynamic_design"]["source_action_authorizations"] = (
        source_action_authorizations(plan.requested_prompt)
    )
    assert plan.game_design["dynamic_design"]["source_action_authorizations"] == {
        "schema": "rmm/source-action-authorizations-v1",
        "peer_asset_exchange": False,
        "earned_resource_market": True,
    }
    generated = render_host_peer_barter(server, plan)
    assert generated is not None
    assert "pending[a]" not in generated  # no two-party offer transfer
    assert "Market" in generated or "price" in generated.lower()
    # The strategy and resulting source are now insensitive to the raw text.
    before = render_host_peer_barter(client, plan)
    plan.requested_prompt = "A completely unrelated sample sentence"
    assert render_host_peer_barter(server, plan) == generated
    assert render_host_peer_barter(client, plan) == before


def test_source_authorization_tampering_is_detected_before_build():
    import pytest
    from roblox_mod_ai.request_semantics import assert_source_action_authorizations
    _server, _client, plan = make_plan()
    assert_source_action_authorizations(plan)
    plan.game_design["dynamic_design"]["source_action_authorizations"][
        "peer_asset_exchange"] = False
    with pytest.raises(ValueError, match="SOURCE_AUTHORIZATIONS_INVALID"):
        assert_source_action_authorizations(plan)


def test_between_players_without_trade_is_not_asset_exchange_permission():
    from roblox_mod_ai.request_semantics import (
        request_semantic_errors, source_action_authorizations,
    )
    vague = "Players can chat between players while exploring the world"
    assert source_action_authorizations(vague)["peer_asset_exchange"] is False
    assert any("UNREQUESTED_PEER_TRADE" in error for error in
               request_semantic_errors(
                   "Players can trade owned inventory assets with each other",
                   vague,
               ))
    explicit = "Players barter inventory items between players."
    assert source_action_authorizations(explicit)["peer_asset_exchange"] is True
    assert not any("UNREQUESTED_PEER_TRADE" in error for error in
                   request_semantic_errors(
                       "Players can trade owned inventory assets with each other",
                       explicit,
                   ))
