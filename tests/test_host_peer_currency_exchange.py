"""Generic coin-to-coin consent exchange, independent of named game/modules."""
from types import SimpleNamespace

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_peer_currency_exchange import (
    eligible_peer_currency_exchange, render_host_peer_currency_exchange,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxService


class FailIfModelUsed:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Model must not author two-wallet trading Luau")


def make_plan():
    def module(name, kind, description):
        client = kind == ModuleKind.CLIENT_SCRIPT
        return RobloxModuleSpec(
            module_id="dyn_" + name, name=name, kind=kind,
            file_path=("src/client/" + name + ".client.luau" if client
                       else "src/server/" + name + ".luau"),
            roblox_service=(RobloxService.STARTER_PLAYER_SCRIPTS if client
                            else RobloxService.SERVER_SCRIPT_SERVICE),
            description=description,
        )
    miner = module("OreMiningEconomyServer", ModuleKind.SERVER_MODULE,
                   "Server validates mining from resource nodes and credits earned currency.")
    trader = module("CounterpartyLedgerServer", ModuleKind.SERVER_MODULE,
                    "The server owns all trading state and validates every trade atomically: "
                    "it reads the initiator's and counterparty's current balances, "
                    "checks that the offered currency amount is positive and does not exceed "
                    "the initiator's balance, checks that the received amount is non-negative "
                    "and does not exceed the counterparty's balance, applies both debits "
                    "and credits in one transaction, and only then persists the result. "
                    "It rejects duplicate, stale, or out-of-order trade requests, rejects "
                    "insufficient balances, rejects same-player trades, and enforces a "
                    "session lock per player.")
    client = module("CounterpartyLedgerClient", ModuleKind.CLIENT_SCRIPT,
                    "Client displays balances and requests a confirmed currency trade.")
    design = {
        "world_objects": [{"name": "OreNode", "class": "Part"}],
        "host_actions": {
            "OreMiningAction": {"service": miner.name, "kind": "RemoteFunction"},
            "CurrencyExchangeAction": {"service": trader.name, "kind": "RemoteFunction"},
        },
        "remotes": {"OreMiningAction": "RemoteFunction", "CurrencyExchangeAction": "RemoteFunction"},
        "module_remotes": {
            trader.module_id: ["CurrencyExchangeAction"],
            client.module_id: ["CurrencyExchangeAction"],
        },
    }
    return miner, trader, client, SimpleNamespace(
        modules=[miner, trader, client],
        game_design={"dynamic_design": design},
        requested_prompt="Earn coins and exchange currency with another player",
    )


def test_bilateral_currency_uses_host_code_not_small_model_luau():
    miner, server, client, proposal = make_plan()
    assert eligible_peer_currency_exchange(server, proposal) == (
        server.name, "CurrencyExchangeAction")
    assert eligible_peer_currency_exchange(client, proposal) is not None
    coder = LuauCodeGenerator(FailIfModelUsed())
    s = coder.generate_module_code(server, proposal)
    c = coder.generate_module_code(client, proposal)
    assert s == render_host_gameplay(server, proposal)
    assert c == render_host_gameplay(client, proposal)
    assert 'manager.GetState(p, "RMMTrades")' in s
    assert 'offers[a] = nil' in s
    assert 'senderCoins.Value = senderAfter' in s
    assert 'receiverCoins.Value = receiverAfter' in s
    assert 'offer.to ~= player.UserId' in s
    assert 'senderCoins.Value < fromAmount' in s
    assert 'receiverCoins.Value < toAmount' in s
    assert 'senderLedger.lastExchange = ' in s
    assert "NOT atomic as a pair" in s
    assert 'remote:InvokeServer(table.unpack(packed, 1, packed.n))' in c
    assert 'request("offer", other.UserId' in c
    assert 'request("accept", reviewed)' in c
    assert 'WaitForChild("CurrencyExchangeAction", 20)' in c
    for mod, source in ((server, s), (client, c)):
        issues = [x for x in LuauStaticAnalyzer().analyze_source(
            source, mod.file_path) if x.severity == "ERROR"]
        assert not issues, [(x.rule, x.line_number, x.message) for x in issues]


def test_unbacked_or_unconfirmed_trade_does_not_get_fake_money_or_success():
    _, server, client, proposal = make_plan()
    proposal.modules = [server, client]
    assert render_host_peer_currency_exchange(server, proposal) is None

    miner, server, client, proposal = make_plan()
    proposal.game_design["dynamic_design"]["host_actions"]["CurrencyExchangeAction"]["kind"] = "RemoteEvent"
    assert render_host_peer_currency_exchange(server, proposal) is None

    miner, server, client, proposal = make_plan()
    proposal.game_design["dynamic_design"]["host_actions"]["CurrencyExchangeAction"]["max_args"] = 2
    assert render_host_peer_currency_exchange(server, proposal) is None

    miner, server, client, proposal = make_plan()
    server.description = "Single player buys a coin bundle from the market."
    assert render_host_peer_currency_exchange(server, proposal) is None

    miner, server, client, proposal = make_plan()
    proposal.game_design["dynamic_design"]["module_remotes"][client.module_id] = ["MissingRemote"]
    assert render_host_peer_currency_exchange(client, proposal) is None
