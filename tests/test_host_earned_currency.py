"""Replay bounded currency failure without a 9B-generated unsafe mint handler."""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_earned_currency import (
    eligible_earned_currency, matching_ledger, render_host_earned_currency,
)
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, RobloxService, ModuleKind


class NoModel:
    def complete(self,*args,**kwargs):
        raise AssertionError("Currency grant and profile mutations belong to host")
    def complete_json(self,*args,**kwargs):
        raise AssertionError("The host ledger does not need fictional earn-source data")


def proposal_fixture(earning_already=False):
    def mod(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_" + name,name=name,kind=kind,
            file_path=("src/server/" + name + ".luau" if kind == ModuleKind.SERVER_MODULE
                       else "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    mining = mod("ResourceMiningAndGatherinBD361B1Server",ModuleKind.SERVER_MODULE,
        "The server owns all resource-node state and collection validation. Each "
        "resource node has a finite server-authoritative amount of extractable "
        "resource. The player initiates mining within the node interaction range; "
        "the server checks the player's mining timer and remaining resource. "
        "When depleted the server grants the extracted resource amount. "
        "Resource amounts are never granted without a validated mining cycle."
        + (" Server awards earned currency for mining." if earning_already else ""))
    mining_client = mod("ResourceMiningAndGatherinBD361B1Client",ModuleKind.CLIENT_SCRIPT,
        "Show authoritative resource extraction.")
    server = mod("EarnedGameCurrencyEconomyE7734E1Server",ModuleKind.SERVER_MODULE,
        "The server is the sole owner of every currency balance and every balance "
        "change. On each earn event, the server validates the player's identity, "
        "the earning source, and the amount against a server-side ledger before "
        "applying the change; it rejects duplicate, negative, or out-of-range "
        "changes and records the resulting balance. The server publishes the "
        "authoritative balance to the client only after the change is committed.")
    client = mod("EarnedGameCurrencyEconomyE7734E1Client",ModuleKind.CLIENT_SCRIPT,
        "The client reads the server-published balance, and renders it in a "
        "currency display. The client cannot write a balance.")
    mine_remote="MiningAction"
    econ_remote="CurrencyBalanceAction"
    design={
        "world_objects":[{"name":"ResourceNodeBD361B11","class":"Part"}],
        "module_world_objects":{mining.module_id:["ResourceNodeBD361B11"]},
        "remotes":{mine_remote:"RemoteFunction",econ_remote:"RemoteFunction"},
        "host_actions":{
            mine_remote:{"service":mining.name,"kind":"RemoteFunction"},
            econ_remote:{"service":server.name,"kind":"RemoteFunction"},
        },
        "module_remotes":{
            mining.module_id:[mine_remote],mining_client.module_id:[mine_remote],
            server.module_id:[econ_remote],client.module_id:[econ_remote],
        },
    }
    p=RobloxProposal(
        game_title="Any earned-resource game",
        description="Server-mined resources, server-owned money",
        requested_prompt="Earn coins by mining and buy player upgrades",
        game_design={"dynamic_design":design},
        modules=[mining,mining_client,server,client],
    )
    return p,mining,mining_client,server,client


def test_uploaded_currency_owner_is_host_owned_and_mining_source_is_verified():
    p,mining,mining_ui,ledger,client=proposal_fixture()
    assert matching_ledger(p)==("EarnedGameCurrencyEconomyE7734E1Server","CurrencyBalanceAction")
    assert eligible_earned_currency(ledger,p)
    assert eligible_earned_currency(client,p)
    scope=generation_scope(p)
    roles={x["name"]:x["strategy"] for x in scope["modules"]}
    assert roles[mining.name]=="host_verified_template"
    assert roles[ledger.name]=="host_verified_template"
    assert roles[client.name]=="host_verified_template"
    gen=LuauCodeGenerator(NoModel())
    code=gen.generate_with_self_correction(ledger,p)
    mining_code=gen.generate_with_self_correction(mining,p)
    client_code=gen.generate_with_self_correction(client,p)
    assert code==render_host_earned_currency(ledger,p)
    assert mining_code==render_host_mining(mining,p)
    assert "function Service.recordMiningReward(player, services)" in code
    assert 'GetState(player, "RMMCurrencyMiningLedger")' in code
    assert 'GetState(player, "RMMInventory")' in code
    assert 'local unpaid = mined - paid' in code
    assert 'if unpaid <= 0 or unpaid > 32' in code
    assert 'coins.Value += unpaid' in code
    assert 'record.paidThrough = mined' in code
    assert 'select("#", ...) > 1' in code
    assert '"read_only"' in code
    assert 'progress.totalMined = mined + 1' in mining_code
    assert 'rewardService.recordMiningReward(player, services)' in mining_code
    assert 'services["EarnedGameCurrencyEconomyE7734E1Server"]' in mining_code
    assert 'remote:InvokeServer("balance")' in client_code
    assert "coins.Value +=" not in client_code
    assert 'tonumber(...)' not in code
    assert "PlayerDataManager:GetState" not in code
    for mod,source in [(mining,mining_code),(ledger,code),(client,client_code)]:
        errors=[d for d in LuauStaticAnalyzer().analyze_source(source,mod.file_path)
                if d.severity=="ERROR"]
        assert not errors,[(mod.name,d.rule,d.line_number,d.message) for d in errors]


def test_no_double_reward_if_host_miner_already_grants_coins():
    p,mining,_,ledger,_=proposal_fixture(earning_already=True)
    mining_code=render_host_mining(mining,p)
    assert "coins.Value += 1" in mining_code
    assert 'rewardService.recordMiningReward' not in mining_code
    assert eligible_earned_currency(ledger,p)


def test_no_earning_producer_or_no_verified_transport_refuses_ledger_claim():
    p,mining,_,ledger,client=proposal_fixture()
    p.modules.remove(mining)
    assert eligible_earned_currency(ledger,p) is None
    p,mining,_,ledger,client=proposal_fixture()
    p.game_design["dynamic_design"]["host_actions"]["CurrencyBalanceAction"]["kind"]="RemoteEvent"
    assert eligible_earned_currency(ledger,p) is None
    p,mining,_,ledger,client=proposal_fixture()
    p.game_design["dynamic_design"]["module_remotes"][client.module_id]=["OtherRoute"]
    assert eligible_earned_currency(client,p) is None


def test_unrelated_economy_does_not_make_fake_reward_service():
    p,mining,_,ledger,client=proposal_fixture()
    ledger.description="The client can pay money to buy shop upgrades."
    assert matching_ledger(p) is None
    assert eligible_earned_currency(ledger,p) is None
    p,mining,_,ledger,client=proposal_fixture()
    ledger.name="GeneralAccountingServer"
    ledger.file_path="src/server/GeneralAccountingServer.luau"
    client.name="GeneralAccountingClient"
    client.file_path="src/client/GeneralAccountingClient.client.luau"
    p.game_design["dynamic_design"]["host_actions"]["CurrencyBalanceAction"]["service"]=ledger.name
    assert eligible_earned_currency(ledger,p)
    assert eligible_earned_currency(client,p)



def test_previously_accepted_space_mode_setup_is_host_owned_not_invalid_camera_code():
    from roblox_mod_ai.host_mode_world_action import render_host_mode_world_action
    p,miner,_,ledger,client=proposal_fixture()
    mode=RobloxModuleSpec(
        module_id="dyn_mode_setup",
        name="ArbitraryWorldModeActivationServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ArbitraryWorldModeActivationServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=("The server enables a dedicated Space Mode state for the "
                     "current game session, activates a themed space environment, "
                     "and exposes a dedicated game-mode setup that unlocks the "
                     "space-mode progression loop."),
    )
    p.modules.insert(0,mode)
    design=p.game_design["dynamic_design"]
    design["world_objects"].append({"name":"SpaceModeF5E8F011","class":"Part"})
    design["module_world_objects"][mode.module_id]=["SpaceModeF5E8F011"]
    design["host_world_actions"]={"SpaceModeF5E8F011":{
        "service":mode.name,"action_text":"Space Mode Setup",
    }}
    src=LuauCodeGenerator(NoModel()).generate_with_self_correction(mode,p)
    assert src==render_host_mode_world_action(mode,p)
    assert 'local TARGET = "SpaceModeF5E8F011"' in src
    assert 'local MODE = "Space Mode"' in src
    assert 'GetState(player,"RMMGameMode")' in src
    assert 'state.activeMode = MODE' in src
    assert 'spaceUnlocked=false' in src
    assert "CurrentCamera" not in src
    assert "services.Players" not in src
    assert 'services.PlayerDataManager.OnReady' in src
    errors=[d for d in LuauStaticAnalyzer().analyze_source(src,mode.file_path)
            if d.severity=="ERROR"]
    assert not errors, [(e.rule,e.message) for e in errors]


def test_mode_world_action_never_claims_launch_or_unowned_part():
    from roblox_mod_ai.host_mode_world_action import render_host_mode_world_action
    p,_,_,_,_=proposal_fixture()
    mode=RobloxModuleSpec(
        module_id="dyn_arbitrary",
        name="ArbitraryModeServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ArbitraryModeServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="Server enables a dedicated Space Mode environment and progression state.",
    )
    p.modules.insert(0,mode)
    p.game_design["dynamic_design"]["host_world_actions"]={
        "MadeUpPart":{"service":mode.name,"action_text":"Start"},
    }
    assert render_host_mode_world_action(mode,p) is None



def test_followup_trade_and_ship_slot_contracts_do_not_require_specific_names():
    from roblox_mod_ai.host_peer_barter import render_host_peer_barter
    from roblox_mod_ai.host_ship_part_catalog import eligible_ship_part_catalog
    p,mining,_,ledger,_=proposal_fixture()
    trade=RobloxModuleSpec(
        module_id="dyn_real_barter",
        name="ArbitraryItemExchangeServer", kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ArbitraryItemExchangeServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server owns the trade state and validates every exchange. "
            "When a player submits a trade request, the server checks that "
            "the player owns each offered item, that each requested item is "
            "owned by the counterparty, and that quantities are positive integers. "
            "On approval the server transfers the exact offered quantities "
            "from the requester and the exact requested quantities from the "
            "counterparty and records the outcome."
        ),
    )
    parts=RobloxModuleSpec(
        module_id="dyn_slot_builder",
        name="ArbitraryPartRegistryServer",kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/ArbitraryPartRegistryServer.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description=(
            "The server owns the modular spaceship assembly state. It validates "
            "each part-selection request against the player's owned currency "
            "and the current ship's available slots, then applies the selected "
            "part to the ship's part registry, updates the ship's performance "
            "stats and records the resulting build state. Invalid selections "
            "are rejected with a clear reason."
        ),
    )
    p.modules.extend([trade,parts])
    # This follow-up explicitly authorizes a second player as an actor.
    # Market-only requests must never silently gain peer inventory transfers.
    from roblox_mod_ai.request_semantics import source_action_authorizations
    p.requested_prompt = "Earn coins by mining, upgrade, and trade items between players"
    d=p.game_design["dynamic_design"]
    d["source_action_authorizations"] = source_action_authorizations(p.requested_prompt)
    d["host_actions"]["TradeAction"]={"service":trade.name,"kind":"RemoteFunction"}
    d["remotes"]["TradeAction"]="RemoteFunction"
    d["host_actions"]["ShipPartAction"]={"service":parts.name,"kind":"RemoteFunction"}
    d["remotes"]["ShipPartAction"]="RemoteFunction"
    assert render_host_peer_barter(trade,p) is not None
    assert eligible_ship_part_catalog(parts,p) is not None
    strategies={x["name"]:x["strategy"] for x in generation_scope(p)["modules"]}
    assert strategies[trade.name]=="host_verified_template"
    assert strategies[parts.name]=="host_declarative_ship_part_catalog"



def test_source_owned_mining_and_currency_module_is_not_claimed_as_two_services():
    # The uploaded failure stopped BEFORE inference: a real mining source
    # simultaneously looked like a currency balance owner.
    from roblox_mod_ai.host_gameplay import render_host_gameplay
    p, other_miner, _mine_ui, owner, _client = proposal_fixture()
    owner.name = "ResourceMiningCurrencyAcc0388601Server"
    owner.file_path = "src/server/" + owner.name + ".luau"
    owner.description = (
        "The server is the sole owner of currency balances and publishes "
        "the authoritative client balance. On each earn event it rejects "
        "duplicate or invalid earning transactions. The server validates "
        "mining actions on nearby resource nodes, verifies gathering radius "
        "and depletion, then awards earned currency and gathered resources."
    )
    d = p.game_design["dynamic_design"]
    d["host_actions"]["CurrencyBalanceAction"]["service"] = owner.name
    d["world_objects"].append({"name": "ResourceNode0388601", "class": "Part"})
    d["module_world_objects"][owner.module_id] = ["ResourceNode0388601"]
    assert render_host_mining(owner, p) is not None
    assert matching_ledger(p) is None
    source = render_host_gameplay(owner, p)
    assert source == render_host_mining(owner, p)
    assert 'coins.Value += 1' in source
    role = next(x for x in generation_scope(p)["modules"]
                if x["name"] == owner.name)
    assert role["strategy"] == "host_verified_template"
    assert LuauCodeGenerator(NoModel()).generate_with_self_correction(owner,p) == source
