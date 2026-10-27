"""Reproduce proposal_partial in failure_logs (14): composite mining+trade.

The failed plan has only alien/mineral world Parts and a module whose
name truncates Gathering. The host must materialize the mineable Part and
implement both mining and bilateral trade behind one RemoteFunction.
"""
from __future__ import annotations

import copy
import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
from roblox_mod_ai.host_mining_exchange import (
    eligible_mining_exchange, render_host_mining_exchange,
)
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class NoCoder:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("No raw Luau belongs to a client/model for server ledger mechanics")
    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("No extra unspecified balances, trade rates or source APIs")


def make_plan(server_name="SpaceModeResourceGatherin0388601Server"):
    def module(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name, kind=kind,
            file_path=("src/server/" + name + ".luau"
                       if kind == ModuleKind.SERVER_MODULE
                       else "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    client_name = server_name.removesuffix("Server") + "Client"
    server = module(server_name, ModuleKind.SERVER_MODULE,
        "The server owns the economy ledger and validates every resource-gathering, "
        "currency, and trade action. Mining a resource node grants a finite, "
        "server-issued quantity of the node's resource and credits the player's "
        "in-game currency balance. Currency is only ever added by validated "
        "server-side events; the server rejects duplicate mining, overspend, "
        "negative balances, and any trade that would violate the ledger. "
        "Trade actions are validated against the player's balance and inventory "
        "before the server commits the exchange, then updates both sides atomically.")
    client = module(client_name, ModuleKind.CLIENT_SCRIPT,
        "The client shows the player's currency balance and resource counts as "
        "read-only HUD values, mining success and two-party trade results.")
    d = {
        "host_actions":{"EconomyAction":{"service":server.name,"kind":"RemoteFunction"}},
        "remotes":{"EconomyAction":"RemoteFunction"},
        "module_remotes":{server.module_id:["EconomyAction"],
                          client.module_id:["EconomyAction"]},
        "module_world_objects":{server.module_id:[],client.module_id:[]},
        "host_world_actions":{},
        "world_objects":[
            {"name":"AlienEnemy1F017B11","class":"Part",
             "position":[24,2,24],"size":[4,4,4]},
            {"name":"SpecialMineralDeposit1F017B12","class":"Part",
             "position":[36,2,24],"size":[4,4,4]},
        ],
    }
    p=RobloxProposal(requested_prompt="우주모드 자원파밍 돈모으기 거래 우주선 제작",
        game_title="An arbitrary built world", description="Mine, barter and build",
        modules=[server,client],game_design={"dynamic_design":d})
    return p,server,client


def test_actual_truncated_module_gets_world_node_and_host_owned_complete_behavior():
    p,server,client=make_plan()
    assert not eligible_mining_exchange(server,p)
    original=copy.deepcopy(p.game_design["dynamic_design"]["world_objects"])
    changed=ensure_mining_world_contract(p)
    assert len(changed)==1
    assert changed[0]["service"] == server.name
    assert p.game_design["dynamic_design"]["world_objects"][:2] == original
    assert p.game_design["dynamic_design"]["world_objects"][-1]["name"] == "ResourceNode03886011"
    assert p.game_design["dynamic_design"]["module_world_objects"][server.module_id] == ["ResourceNode03886011"]
    assert p.game_design["dynamic_design"]["module_world_objects"][client.module_id] == ["ResourceNode03886011"]
    assert ensure_mining_world_contract(p)==[]
    assert eligible_mining_exchange(server,p)
    assert eligible_mining_exchange(client,p)
    scope=generation_scope(p)
    role={row["name"]:row["strategy"] for row in scope["modules"]}
    assert role[server.name]=="host_verified_template"
    assert role[client.name]=="host_verified_template"
    coder=LuauCodeGenerator(NoCoder())
    server_code=coder.generate_with_self_correction(server,p)
    client_code=coder.generate_with_self_correction(client,p)
    assert server_code==render_host_gameplay(server,p)
    assert client_code==render_host_gameplay(client,p)
    assert server_code==render_host_mining_exchange(server,p)
    for token in (
        'local NODE_NAMES = {"ResourceNode03886011"}',
        'GetState(player, "RMMInventory")',
        'inv.resources = resources + 1',
        'coins.Value += 1',
        'state.remaining -= 1',
        'local function makeOffer(player, services, payload)',
        'local function acceptOffer(player, services, id)',
        'sellerInv.resources = sellerResources - offer.resources',
        'buyerInv.resources = buyerResources + offer.resources',
        'buyerCoins.Value -= offer.coins',
        'sellerCoins.Value += offer.coins',
        'pending[id] = nil',
        'seller:SetAttribute("RMMCurrencyBalance"',
        'return {success = false, reason = "invalid_action"}',
    ):
        assert token in server_code, token
    assert 'remote:InvokeServer(action, payload)' in client_code
    assert 'request("mine", nil)' in client_code
    assert 'request("offer", {buyerUserId' in client_code
    assert 'request("accept", list.pending[1].id)' in client_code
    assert "PlayerDataManager:GetState" not in server_code
    assert "findNode(" not in server_code
    assert 'math.huge' in server_code
    for module,source in ((server,server_code),(client,client_code)):
        diagnostics=LuauStaticAnalyzer().analyze_source(source,module.file_path)
        assert not [d for d in diagnostics if d.severity=="ERROR"], [
            (d.rule,d.line_number,d.message) for d in diagnostics
        ]
    bootstrap=render_dynamic_server_bootstrap(p)
    assert 'WaitForChild("EconomyAction", 20)' in bootstrap
    assert 'remote.OnServerInvoke = function(player, ...)' in bootstrap


def test_real_rojo_world_declares_source_part_and_remote(tmp_path):
    from roblox_mod_ai.project_generator import RobloxProjectGenerator
    p,server,client=make_plan()
    ensure_mining_world_contract(p)
    result=RobloxProjectGenerator(tmp_path).generate_rojo_project_json(p)
    assert result["tree"]["Workspace"]["ResourceNode03886011"]["$className"]=="Part"
    assert result["tree"]["ReplicatedStorage"]["Remotes"]["EconomyAction"]["$className"]=="RemoteFunction"


def test_other_module_names_are_allowed_when_real_mechanic_is_present():
    p,server,client=make_plan("GenericPlayerLedgerServer")
    changed=ensure_mining_world_contract(p)
    assert len(changed)==1
    assert eligible_mining_exchange(server,p)
    assert eligible_mining_exchange(client,p)
    assert render_host_gameplay(server,p)


def test_other_resource_users_and_absent_owner_do_not_get_free_nodes():
    p,server,client=make_plan()
    server.description = "Server displays a global resource leaderboard and trade history"
    before=copy.deepcopy(p.game_design["dynamic_design"])
    assert not ensure_mining_world_contract(p)
    assert p.game_design["dynamic_design"]==before
    p,server,client=make_plan()
    p.game_design["dynamic_design"]["host_actions"]["EconomyAction"]["kind"]="RemoteEvent"
    assert not ensure_mining_world_contract(p)
    assert eligible_mining_exchange(server,p) is None
    p,server,client=make_plan()
    p.requested_prompt="우주선 부품 조립만 수행"
    assert not ensure_mining_world_contract(p)


def test_composite_never_degrades_to_mining_only_when_trading_is_missing():
    p,server,client=make_plan()
    ensure_mining_world_contract(p)
    assert eligible_mining_exchange(server,p)
    server.description="The server mines resource nodes and credits currency only."
    assert eligible_mining_exchange(server,p) is None


@pytest.mark.parametrize("max_args", [0,1,"two",True])
def test_composite_rejects_incompatible_or_malformed_action_signatures(max_args):
    p,server,client=make_plan()
    p.game_design["dynamic_design"]["host_actions"]["EconomyAction"]["max_args"]=max_args
    ensure_mining_world_contract(p)
    assert eligible_mining_exchange(server,p) is None



def test_real_failure_15_mining_and_bilateral_barter_are_composed_not_conflicted():
    # Source reports exactly these two owners colliding during resolve_dependencies.
    # Preserve full peer-to-peer *item/coin* support, not a one-resource shortcut.
    from roblox_mod_ai.host_mining import render_host_mining
    from roblox_mod_ai.host_peer_barter import render_host_peer_barter
    p,server,client=make_plan("ResourceMiningAndTradeEco0388601Server")
    server.description=(
        "The server validates mining actions at nearby resource nodes, "
        "checking the player radius and remaining deposit, then grants earned "
        "currency and resources. The server also validates trade exchange "
        "actions between two players: both sides confirm a matching offer of "
        "resource and item inventory balances, and each participant's "
        "asset quantities are checked to reject stale and duplicate trades. "
        "Both sides receive a server-confirmed exchange result."
    )
    # This regression verifies bilateral exchange, which must be explicitly
    # source-owned. A generic "거래" request never authorizes peer inventory.
    p.requested_prompt = (
        "우주모드 자원파밍 돈모으기 거래 우주선 제작, "
        "플레이어 간 아이템과 화폐 거래도 허용"
    )
    from roblox_mod_ai.request_semantics import source_action_authorizations
    p.game_design["dynamic_design"]["source_action_authorizations"] = (
        source_action_authorizations(p.requested_prompt)
    )
    ensure_mining_world_contract(p)
    for mod in (server,client):
        mine=render_host_mining(mod,p)
        barter=render_host_peer_barter(mod,p)
        assert mine is not None and barter is not None
        combined=render_host_gameplay(mod,p)
        assert combined==render_host_mining_exchange(mod,p)
        assert mine != combined and barter != combined
        assert "local Mine = (function()" in combined if mod is server else "do\n" in combined
        assert 'remote:InvokeServer(table.unpack(args, 1, args.n))' in combined if mod is client else 'Barter.handleAction(player, services, ...)' in combined
        errors=[d for d in LuauStaticAnalyzer().analyze_source(combined,mod.file_path)
                if d.severity=="ERROR"]
        assert not errors, [(d.rule,d.message) for d in errors]
        assert LuauCodeGenerator(NoCoder()).generate_module_code(mod,p) == combined


def test_two_distinct_services_remain_independent_without_ownership_overlap():
    from test_host_peer_barter import make_plan as split_plan
    from roblox_mod_ai.host_peer_barter import render_host_peer_barter
    p_server,p_client,p=split_plan()
    expected=render_host_peer_barter(p_server,p)
    assert expected is not None
    assert render_host_gameplay(p_server,p)==expected
    assert render_host_mining_exchange(p_server,p) is None
