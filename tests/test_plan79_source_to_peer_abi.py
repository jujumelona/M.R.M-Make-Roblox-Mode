"""Production-79: source intent and the actual callable host API must agree.

The source did not ask for peer-to-peer trading. The small coder repeatedly
called ResourceGatherServer.handleAction because the 9B prompt listed it as
an "exported" API despite the runtime host prohibiting such calls.
The repair must be genre-neutral: separate lifecycle/ingress from services,
and reject unrequested buyer/seller transfers regardless of game theme.
"""
from roblox_mod_ai.request_semantics import request_semantic_errors
from roblox_mod_ai.scoped_luau_abi import (
    allowed_gameplay_peer_methods, host_abi_guidance,
)
from roblox_mod_ai.server_interface_audit import dependency_api_errors
from types import SimpleNamespace as NS


def test_buyer_seller_transfer_not_implied_by_generic_trade():
    original = "채굴한 자원을 거래해서 장비를 제작하고 업그레이드"
    generated = (
        "The server validates the trade offer against the seller's owned "
        "currency and inventory, then transfers the seller's owned "
        "currency to the buyer and marks the item as owned by the buyer."
    )
    assert any("UNREQUESTED_PEER_TRADE" in message
               for message in request_semantic_errors(generated, original))


def test_market_trade_stays_permitted():
    original = "Trade harvested resources to earn credits"
    design = (
        "The authenticated player sells owned mined resources to a "
        "server-owned market for earned currency; debit resources "
        "and credit the player's account."
    )
    assert not request_semantic_errors(design, original)


def test_explicit_player_to_player_trade_is_not_banned():
    original = "Players can trade with each other"
    design = (
        "The server transfers the seller's owned inventory to the buyer "
        "after both parties approve the trade."
    )
    assert not request_semantic_errors(design, original)


def test_coder_never_sees_internal_remote_handler_as_callable_service():
    actual_exported = {
        "ResourceProducerService": ["start", "handleAction"],
        "PlayerDataManager": ["GetState", "OnReady", "start"],
        "MarketBroker": ["start", "handleAction", "QuotePrice"],
    }
    callable = allowed_gameplay_peer_methods(actual_exported)
    assert callable["ResourceProducerService"] == []
    assert callable["PlayerDataManager"] == ["GetState"]
    assert callable["MarketBroker"] == ["QuotePrice"]
    prompt = host_abi_guidance(
        {"inputs": [{"id": "selection", "type": "text"}]},
        actual_exported,
    )
    assert '"ResourceProducerService": []' in prompt
    assert '"PlayerDataManager": ["GetState"]' in prompt
    assert "never call" in prompt.lower()
    # The string handleAction may occur only in the explicit prohibition,
    # never inside the machine-readable available-method list.
    assert '"handleAction"' not in prompt


def test_runtime_contract_still_blocks_cross_handler_execution():
    called = NS(
        module_id="dyn_resource", name="ResourceProducerService",
        file_path="src/server/ResourceProducerService.luau",
        code=(
            "local Service = {}\n"
            "function Service.handleAction(player, services, ...)\n"
            "  return true\n"
            "end\nreturn Service\n"
        ),
    )
    current = NS(
        module_id="dyn_market", name="MarketBroker",
        file_path="src/server/MarketBroker.luau", code="",
    )
    proposal = NS(modules=[called, current])
    source = (
        "local Service = {}\n"
        "function Service.start(services) end\n"
        "function Service.handleAction(player, services, ...)\n"
        " local result = services.ResourceProducerService.handleAction("
        "player, services, {quantity = 1})\n"
        " return result\n"
        "end\nreturn Service\n"
    )
    issues = dependency_api_errors(current, proposal, source)
    assert any("DEPENDENCY_ACTION_DISPATCH_FORBIDDEN" in issue
               for issue in issues), issues
