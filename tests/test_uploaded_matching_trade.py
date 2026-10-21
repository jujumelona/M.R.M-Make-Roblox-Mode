"""Replay a concrete failed bilateral trade as a host-owned bounded action.

The source plan requires one actual mining producer and RemoteFunction.
No generated Luau body from the model is allowed to call fake player APIs or
invent sender balances. Consent/asset checks stay in host runtime code.
"""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_peer_barter import is_bilateral_asset_exchange, render_host_peer_barter
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec, ModuleKind, RobloxService


class FailOnLuau:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Model cannot own cross-player inventory exchange")
    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Host trade contracts require no model JSON")


def fixture():
    def module(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name, kind=kind,
            file_path=("src/server/" + name + ".luau" if kind == ModuleKind.SERVER_MODULE
                       else "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    mine = module("ResourceMiningAndCurrency23C0F11Server", ModuleKind.SERVER_MODULE,
        "The server owns all resource quantities and currency balances. When a player "
        "performs a mining action, the server validates the player is in a valid mining "
        "state and applies a fixed resource yield to earned game currency.")
    server = module("PlayerToPlayerTradingViaMD228CB1Server", ModuleKind.SERVER_MODULE,
        "The server owns the trade lifecycle: it validates each player's request, "
        "resolves the selected offer against the player's owned inventory, applies "
        "the exchange atomically, and records the result in player data. A request "
        "is rejected if the sender has no matching offer, the receiver has no "
        "matching offer, either side's inventory lacks the selected item, or the "
        "trade is already in progress for that player. The server rejects duplicate "
        "or stale requests and prevents a player from trading the same item instance "
        "to two receivers. On success, the server updates both inventories and "
        "persists the trade outcome; on failure, it returns the specific rejection "
        "reason to the requesting client.")
    client = module("PlayerToPlayerTradingViaMD228CB1Client", ModuleKind.CLIENT_SCRIPT,
        "The client shows a trading UI with the player's owned items, recipient "
        "selector, and confirmation. On response it shows insufficient inventory "
        "or trade already in progress, never grants inventory locally.")
    mine_remote="ResourceMiningAndCurrency23C0F11Action"
    trade_remote="PlayerToPlayerTradingViaMD228CB1Action"
    design={
        "world_objects": [{"name":"ResourceNode23C0F111","class":"Part"}],
        "module_world_objects": {mine.module_id:["ResourceNode23C0F111"],
                                 server.module_id: [], client.module_id: []},
        "host_actions": {
            mine_remote: {"service":mine.name,"kind":"RemoteFunction"},
            trade_remote: {"service":server.name,"kind":"RemoteFunction"},
        },
        "remotes": {mine_remote:"RemoteFunction",trade_remote:"RemoteFunction"},
        "module_remotes": {mine.module_id:[mine_remote],server.module_id:[trade_remote],
                           client.module_id:[trade_remote]},
    }
    proposal=RobloxProposal(
        requested_prompt="Construct a game with mined resources and peer trades",
        game_title="Any resource game",description="Player asset exchange",
        game_design={"dynamic_design":design},
        modules=[mine, server, client],
    )
    return proposal, mine, server, client


def test_uploaded_bilateral_offer_contract_is_host_owned_not_llm_body():
    p, mining, server, client = fixture()
    assert is_bilateral_asset_exchange(server.description)
    assert not is_bilateral_asset_exchange(
        "The player sells items to a world marketplace at fixed prices.")
    scope=generation_scope(p)
    assert next(x["strategy"] for x in scope["modules"]
                if x["name"]==server.name)=="host_verified_template"
    assert next(x["strategy"] for x in scope["modules"]
                if x["name"]==client.name)=="host_verified_template"
    coder=LuauCodeGenerator(FailOnLuau())
    server_code=coder.generate_with_self_correction(server,p)
    client_code=coder.generate_with_self_correction(client,p)
    assert server_code==render_host_peer_barter(server,p)
    assert client_code==render_host_peer_barter(client,p)
    assert server_code==render_host_gameplay(server,p)
    assert "trade_in_progress" in server_code
    assert "duplicate_offer" in server_code
    assert "if offer.giveAsset == b" in server_code
    assert 'services.PlayerDataManager' in server_code
    assert 'GetState(player, "RMMInventory")' in server_code
    assert 'return {success = true, pending = items, ownedItems = ownedItems}' in server_code
    assert 'offer.to ~= player.UserId' in server_code
    assert 'giverOut.amount < offer.giveQty' in server_code
    assert 'takerOut.amount < offer.wantQty' in server_code
    assert 'setOwned(giverOut, giverOut.amount - offer.giveQty)' in server_code
    assert 'setOwned(takerIn, takerIn.amount + offer.giveQty)' in server_code
    assert 'ownedItems' in client_code
    assert "amountReceived" not in server_code
    assert "profile.resources -= 5000" not in server_code
    assert "PlayerDataManager:GetState" not in server_code
    assert "</parameter>" not in server_code
    for m,source in ((server,server_code),(client,client_code)):
        errors=[d for d in LuauStaticAnalyzer().analyze_source(source,m.file_path)
                if d.severity=="ERROR"]
        assert not errors,[(d.rule,d.line_number,d.message) for d in errors]



def test_seller_buyer_ledger_is_selected_without_model_generation():
    """Regression: distinct seller/buyer offer inventory contracts need the host."""
    p, mine, server, client = fixture()
    server.description = (
        "The server owns the entire trade flow: it validates each player's "
        "offered and wanted item lists against their current inventory. "
        "On a confirmed trade the server atomically removes offered items "
        "from the seller's inventory, adds wanted items to the buyer's "
        "inventory, records the trade in player data, and rejects duplicates."
    )
    assert is_bilateral_asset_exchange(server.description)
    assert render_host_peer_barter(server, p) is not None
    assert render_host_peer_barter(client, p) is not None
    for mod in (server, client):
        selected = next(row for row in generation_scope(p)["modules"]
                        if row["name"] == mod.name)
        assert selected["strategy"] == "host_verified_template"
        source = LuauCodeGenerator(FailOnLuau()).generate_with_self_correction(mod, p)
        assert source == render_host_peer_barter(mod, p)
        assert not [error for error in LuauStaticAnalyzer().analyze_source(
            source, mod.file_path) if error.severity == "ERROR"]


def test_source_ownership_required_and_no_market_as_two_party_trade():
    p, mine, server, client=fixture()
    p.modules.remove(mine)
    assert render_host_peer_barter(server,p) is None
    p,mine,server,client=fixture()
    p.game_design["dynamic_design"]["host_actions"][
        "PlayerToPlayerTradingViaMD228CB1Action"]["kind"]="RemoteEvent"
    assert render_host_peer_barter(server,p) is None
    p,mine,server,client=fixture()
    server.description="Server sells owned resources to central broker market."
    assert render_host_peer_barter(server,p) is None


def test_semantic_variations_support_two_party_offers_without_triggers_on_sales():
    descriptions=[
        "The server validates the sender and receiver's selected offer, exchanges "
        "their owned items and rejects duplicate and stale trade requests.",
        "Each sender and receiver must confirm an offer before any trade or "
        "inventory exchange; the server checks both sides.",
        "A two-player trade exchanges inventory items after validation and consent.",
    ]
    for text in descriptions:
        assert is_bilateral_asset_exchange(text),text
    assert not is_bilateral_asset_exchange(
        "The market buys user inventory with currency after validation.")
