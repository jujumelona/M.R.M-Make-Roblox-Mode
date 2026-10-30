"""Regression coverage for report 55: typed transport is not gameplay."""
from types import SimpleNamespace as NS

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.host_level_upgrade import eligible_rank_protocol
from roblox_mod_ai.host_verified_colony import eligible_colony, render_colony
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.code_generator import LuauCodeGenerator


PAID_CASES = {
    "crew_performance_state": (
        "For the requested purchase, the server validates the buyer's item "
        "selection, actual owned balance and server-owned price or recipe; "
        "after validation, Server upgrades the crew's performance state "
        "and atomically debits the buyer's owned funds or materials."
    ),
    "Spaceship": (
        "For the requested purchase, the server validates actual owned balance "
        "and server-owned price, then upgrades the spaceship's performance "
        "state and debits the buyer's currency in one transaction."
    ),
    "owned_weapon": (
        "For the requested weapon upgrade purchase, the server validates the "
        "actual owned balance and price, then debits the buyer's owned "
        "currency for the weapon upgrade purchase."
    ),
}


def pair(name, description, *, remote=None):
    server = NS(
        name=name+"Server", module_id="dyn_"+name+"_s",
        kind=ModuleKind.SERVER_MODULE, file_path="src/server/"+name+"Server.luau",
        description=description, code="",
    )
    client = NS(
        name=name+"Client", module_id="dyn_"+name+"_c",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/"+name+"Client.client.luau",
        description="Typed UI", code="",
    )
    remote = remote or name+"Action"
    typed = {
        "server": server.name, "client": client.name,
        "transport_only": True, "world_entities": [],
        "contract": {
            "inputs": [
                {"id": "selection", "type": "text"},
                {"id": "quantity", "type": "integer", "min": 1, "max": 10000},
            ],
            "target": {"kind": "none"}, "state_changes": [],
        },
    }
    design = {
        "host_typed_actions": {remote: typed},
        "host_actions": {remote: {
            "service": server.name, "kind": "RemoteFunction", "max_args": 1,
        }},
        "remotes": {remote: "RemoteFunction"},
        "module_remotes": {server.module_id: [remote], client.module_id: [remote]},
    }
    return NS(modules=[server, client], game_design={"dynamic_design": design},
              requested_prompt="Space mining and player upgrades"), server, client


def test_55_paid_ranks_do_not_require_model_created_state_or_world_entities():
    for target, description in PAID_CASES.items():
        p, server, client = pair("Paid"+target, description)
        for module in (server, client):
            chosen = eligible_rank_protocol(module, p)
            assert chosen is not None
            assert chosen[2] == target
        scope = generation_scope(p, for_protocol_handoff=True)
        by_name = {row["name"]: row["strategy"] for row in scope["modules"]}
        assert by_name[server.name] == "host_declarative_rank_upgrade"
        assert by_name[client.name] == "host_declarative_rank_upgrade"


def test_55_paid_ambiguous_and_unsourced_targets_fail_closed():
    p, server, client = pair(
        "Confused", PAID_CASES["Spaceship"]+" Also upgrade the crew's performance state."
    )
    assert eligible_rank_protocol(server, p) is None
    server.description = "Buy a thing at a price and debit the currency."
    assert eligible_rank_protocol(server, p) is None


def colony_fixture(monkeypatch):
    p, server, client = pair(
        "ColonizePlanet", "Validate a server-owned colonist on the planet; "
        "planet not already colonized. On success server-owned state marks "
        "planet colonized and updates its colonized status."
    )
    d = p.game_design["dynamic_design"]
    builder = NS(
        name="ShipAssemblyServer", module_id="dyn_ship",
        kind=ModuleKind.SERVER_MODULE, description="Assembly",
        file_path="src/server/ShipAssemblyServer.luau",
    )
    launch = NS(
        name="ShipLaunchServer", module_id="dyn_launch",
        kind=ModuleKind.SERVER_MODULE, description="Launch",
        file_path="src/server/ShipLaunchServer.luau",
    )
    p.modules += [builder, launch]
    d.update(
        host_vehicle_identity_bindings=[{
            "server": launch.name, "builder": builder.name,
        }],
        host_arrival_materializations=[{
            "server": launch.name, "builder": builder.name,
            "arrival": "OrbitLanding",
        }],
        world_objects=[
            {"name": "OrbitLanding", "class": "Part"},
            {"name": "AlienEntity", "class": "Part"},
        ],
        module_world_objects={server.module_id: ["AlienEntity"]},
    )
    monkeypatch.setattr(
        "roblox_mod_ai.host_ship_attachment.eligible_ship_attachment",
        lambda module, proposal: ("ShipAssemblyServer", "AttachAction")
        if module is builder else None,
    )
    return p, server, client


def test_55_colony_uses_real_arrival_and_persistent_player_settlement(monkeypatch):
    p, server, client = colony_fixture(monkeypatch)
    assert eligible_colony(server, p) is not None
    assert eligible_colony(client, p) is not None
    by_name = {x["name"]: x["strategy"] for x in generation_scope(p)["modules"]}
    assert by_name[server.name] == "host_verified_planet_colony"
    assert by_name[client.name] == "host_verified_planet_colony"
    src = LuauCodeGenerator().generate_module_code(server, p)
    cli = LuauCodeGenerator().generate_module_code(client, p)
    assert "spawnColony(player,ARRIVAL,stamp)" in src
    assert 'GetState(player,"RMMPlanetProgress")' in src
    assert 'RMMFlightState' in src
    assert "GetOwnedActor(player)" in src
    assert 'ARRIVAL = "OrbitLanding"' in src
    assert "AlienEntity" not in src
    assert 'remote:InvokeServer({selection="planet",quantity=1})' in cli


def test_55_unmaterialized_colony_surface_never_passes(monkeypatch):
    p, server, client = colony_fixture(monkeypatch)
    p.game_design["dynamic_design"]["world_objects"] = [
        {"name": "AlienEntity", "class": "Part"}
    ]
    assert eligible_colony(server, p) is None
    assert eligible_colony(client, p) is None


def test_55_verified_paid_crew_and_weapon_changes_affect_real_combat():
    from test_log25_verified_typed_effects import _fixture
    from roblox_mod_ai.host_verified_typed_effects import render_verified_effect
    from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer

    plan, combat = _fixture("combat")
    pay, crew_server, crew_client = pair(
        "PaidCrew", PAID_CASES["crew_performance_state"]
    )
    for field in ("host_actions", "remotes", "module_remotes", "host_typed_actions"):
        plan.game_design["dynamic_design"][field].update(
            pay.game_design["dynamic_design"][field]
        )
    plan.modules.extend((crew_server, crew_client))
    source = render_verified_effect(combat, plan)
    assert source is not None
    assert 'GetState(player, "RMMRankProgress")' in source
    assert "crew_performance_state" in source
    assert "2 * crew" in source
    assert "math.min(70" in source
    assert "_services" not in source
    errors = [e for e in LuauStaticAnalyzer().analyze_source(
        source, combat.file_path) if e.severity == "ERROR"]
    assert errors == [], [(e.rule, e.message) for e in errors]
