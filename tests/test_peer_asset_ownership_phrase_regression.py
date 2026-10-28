"""Never infer bilateral inventory exchange from unrelated multiplayer source."""
from roblox_mod_ai.request_semantics import (
    request_semantic_errors, source_action_authorizations,
)

CHAT_ONLY = "Players can chat between players while exploring the world"

def test_no_trade_permission_from_chat_only_source():
    assert source_action_authorizations(CHAT_ONLY)["peer_asset_exchange"] is False
    for generated in (
        "Players can trade owned inventory assets with each other",
        "Players can exchange their weapons with each other",
        "Players barter inventory items with one another",
    ):
        assert any("UNREQUESTED_PEER_TRADE" in err for err in
                   request_semantic_errors(generated, CHAT_ONLY))

def test_explicit_peer_asset_exchange_remains_source_authorized():
    source = "Players barter inventory items between players."
    assert source_action_authorizations(source)["peer_asset_exchange"] is True
    assert not any("UNREQUESTED_PEER_TRADE" in err for err in
                   request_semantic_errors(
                       "Players can trade owned inventory assets with each other",
                       source,
                   ))
