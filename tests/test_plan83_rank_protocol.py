"""Plan 83: substitute validated design DATA for failing speculative Luau.

Generic single-target paid rank progression has a real server-side currency
debit, saved level increase and exact matching client request. No model owns
the Lua code or invents server service methods.
"""
from types import SimpleNamespace as NS
import pytest

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.host_level_upgrade import (
    eligible_rank_protocol, render_rank_protocol, _check,
)
from roblox_mod_ai.host_protocol_handoff import rebase_complete_host_protocols


class Router:
    def __init__(self, data=None):
        self.data = data or {
            "label": "Increase performance", "cost": 25,
            "increment": 2, "max_level": 10,
        }
        self.calls = 0

    def complete_json(self, *a, **kw):
        self.calls += 1
        assert kw["role"] == "planner"
        assert kw["max_tokens"] <= 225
        return self.data


def fixture(*, target="crew_performance_state", owned=False, transport=True):
    description = (
        "For the paid upgrade, validate the player's owned balance and "
        "currency, deduct the exact catalog cost and upgrade crew "
        "performance; persist the increased rank."
    )
    if owned:
        description = (
            "Validate a weapon upgrade purchase; the weapon exists and is "
            "owned, check available currency, deduct the cost, and apply "
            "an improved weapon upgrade rank to player state."
        )
    srv = NS(
        module_id="dyn_rank_server", kind=ModuleKind.SERVER_MODULE,
        name="GenericRankServer", file_path="src/server/GenericRankServer.luau",
        description=description, code="",
    )
    cli = NS(
        module_id="dyn_rank_client", kind=ModuleKind.CLIENT_SCRIPT,
        name="GenericRankClient", file_path="src/client/GenericRankClient.client.luau",
        description="Rank purchase button", code="",
    )
    remote = "GenericRankAction"
    design = {
        "host_actions": {
            remote: {"service": srv.name, "kind": "RemoteFunction", "max_args": 1},
        },
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {srv.module_id: [remote], cli.module_id: [remote]},
        "host_typed_actions": {
            remote: {
                "server": srv.name, "client": cli.name,
                "transport_only": transport,
                "world_entities": ["player_currency", target],
                "contract": {
                    "inputs": [{"id": "selection", "label": "Target", "type": "text"}],
                    "target": {"kind": "none"}, "state_changes": [],
                },
            }
        },
    }
    return NS(
        game_design={"dynamic_design": design}, modules=[srv, cli]
    ), srv, cli, remote


def test_83_crew_and_owned_weapon_are_both_source_grounded():
    for target, owned in (
        ("crew_performance_state", False), ("owned_weapon", True)
    ):
        plan, srv, cli, route = fixture(target=target, owned=owned)
        for m in (srv, cli):
            details = eligible_rank_protocol(m, plan)
            assert details and details[2] == target and details[3] == owned


def test_matched_pair_handoff_and_compiled_server_client_share_same_target():
    p, server, client, route = fixture()
    scope = {"modules": [
        {"name": server.name, "strategy": "host_declarative_rank_upgrade"},
        {"name": client.name, "strategy": "host_declarative_rank_upgrade"},
    ]}
    changes = rebase_complete_host_protocols(p, scope)
    assert len(changes) == 1
    assert route in p.game_design["dynamic_design"]["host_rank_contracts"]
    assert route not in p.game_design["dynamic_design"]["host_typed_actions"]
    coder = Router()
    scode = render_rank_protocol(server, p, coder)
    ccode = render_rank_protocol(client, p, coder)
    assert coder.calls == 1
    assert 'TARGET="crew_performance_state"' not in scode.replace(" ", "")
    assert '"crew_performance_state"' in scode
    assert 'remote:InvokeServer("crew_performance_state")' in ccode
    assert 'coins.Value-=COST' in scode
    assert 'ranks[TARGET]=nextRank' in scode
    assert "GetState(player" in scode
    assert "SetState" not in scode
    assert "return Service" in scode
    assert rebase_complete_host_protocols(p, scope) == []


def test_owned_weapon_requires_authoritative_inventory_possession():
    p, srv, cli, _ = fixture(target="owned_weapon", owned=True)
    code = render_rank_protocol(srv, p, Router())
    assert "local OWNED=true" in code
    assert "inventory.items[TARGET]" in code
    assert "return {success=false,reason=\"not_owned\"}" in code


def test_unmatched_or_effectful_transport_not_replaced():
    p, srv, cli, route = fixture(transport=False)
    assert eligible_rank_protocol(srv, p) is None
    p2, srv2, cli2, route2 = fixture()
    p2.game_design["dynamic_design"]["host_typed_actions"][route2]["world_entities"] = [
        "currency", "crew", "weapon",
    ]
    assert eligible_rank_protocol(srv2, p2) is None


@pytest.mark.parametrize("data", [
    {"label": "Crew", "cost": True, "increment": 1, "max_level": 5},
    {"label": "Crew", "cost": -1, "increment": 1, "max_level": 5},
    {"label": "Crew", "cost": 100, "increment": 0, "max_level": 5},
    {"label": "Crew", "cost": 100, "increment": 1, "max_level": 0},
    {"label": "Crew", "cost": 100, "increment": 1, "max_level": 5, "lua": "return true"},
])
def test_no_free_or_arbitrary_generated_code_in_bounded_data(data):
    with pytest.raises(ValueError):
        _check(data)
