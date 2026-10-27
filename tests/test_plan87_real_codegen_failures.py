"""Failure log (14): first-party crew Luau contained Python ternary syntax,
and a 9B weapon coder truncated JSON twice then invented WeaponRegistry.
No runtime result is asserted: these are static/codegen contract tests.
"""
from types import SimpleNamespace as NS
from copy import deepcopy

from roblox_mod_ai.spec import ModuleKind
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import (
    generation_scope, assert_prompt_invariant_routing,
)
from roblox_mod_ai.host_owned_weapon_performance import (
    eligible_owned_weapon_performance, render_owned_weapon_performance,
)
from roblox_mod_ai.host_trade_catalog import try_trade_catalog
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer

from test_plan86_market_sale_and_ship_catalog import with_sale
from test_host_trade_catalog import _plan as catalog_plan


REAL_WEAPON_DESC = (
    "Validate that the request comes from a local player with a valid weapon "
    "instance in the current server-owned weapon registry, then mutate the "
    "server-owned weapon performance state (damage multiplier, fire rate, and "
    "cooldown) on that instance and persist the change to the server-owned "
    "registry. Reject requests from unknown players, requests targeting "
    "missing or invalid weapons, and requests that would exceed the "
    "server-owned weapon performance limits."
)


class NeverWritesLuau:
    def complete(self, *_a, **_kw):
        raise AssertionError("Small 9B must not author weapon Luau")


def weapon_plan():
    p, _, _ = with_sale()
    # A complete production plan always supplies this core service.
    p.modules.append(NS(name="PlayerDataManager", module_id="mod_player_data",
                        file_path="src/server/PlayerDataManager.luau",
                        kind=ModuleKind.DATA_STORE,
                        description="Persistent, server-authoritative player profiles"))
    server = NS(
        name="AnyOwnedWeaponPerformanceServer", module_id="dyn_weapon_upgrade",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/AnyOwnedWeaponPerformanceServer.luau",
        description=REAL_WEAPON_DESC,
    )
    client = NS(
        name="AnyOwnedWeaponPerformanceClient", module_id="dyn_weapon_ui",
        kind=ModuleKind.CLIENT_SCRIPT,
        file_path="src/client/AnyOwnedWeaponPerformanceClient.client.luau",
        description="Host owns the schema UI for a selected upgraded weapon",
    )
    p.modules += [server, client]
    d = p.game_design["dynamic_design"]
    d["host_actions"]["WeaponPerformanceAction"] = {
        "service": server.name, "kind": "RemoteFunction", "max_args": 1,
    }
    d["remotes"]["WeaponPerformanceAction"] = "RemoteFunction"
    d["module_remotes"][server.module_id] = ["WeaponPerformanceAction"]
    d["module_remotes"][client.module_id] = ["WeaponPerformanceAction"]
    d["host_typed_actions"]["WeaponPerformanceAction"] = {
        "server": server.name, "client": client.name,
        "transport_only": True, "world_entities": [],
        "contract": {
            "inputs": [
                {"id": "selection", "label": "Owned weapon", "type": "text"},
                {"id": "quantity", "label": "Requested count", "type": "integer", "min": 1, "max": 10000},
            ],
            "target": {"kind": "none"}, "state_changes": [],
        },
    }
    return p, server, client


def test_uploaded_crew_trade_compiler_emits_valid_luau_not_python_ternary():
    p = catalog_plan()
    server = p.modules[0]
    p.game_design["_host_trade_catalogs"] = {server.name: [
        {"id": "crew_mara", "label": "Mara Voss", "category": "crew",
         "cost": 1200, "bonus": 100},
        {"id": "weapon_railgun", "label": "Railgun", "category": "weapon",
         "cost": 800, "bonus": 90},
        {"id": "ship_engine", "label": "Ion Drive", "category": "ship",
         "cost": 1800, "bonus": 150},
        {"id": "hull_license", "label": "Hull section", "category": "section",
         "cost": 400, "bonus": 0},
    ]}
    code = try_trade_catalog(server, p)
    assert code is not None
    assert '(1 if item.kind == "section" else item.bonus)' not in code
    assert 'local contribution = item.bonus' in code
    assert 'if item.kind == "section" then' in code
    assert 'totals[item.kind] + contribution' in code
    problems = [d for d in LuauStaticAnalyzer().analyze_source(
        code, server.file_path) if d.severity == "ERROR"]
    assert problems == [], [(d.rule, d.message) for d in problems]


def test_weapon_performance_real_9b_failure_has_bounded_host_route():
    p, server, client = weapon_plan()
    assert eligible_owned_weapon_performance(server, p) == (
        server.name, "WeaponPerformanceAction")
    assert render_owned_weapon_performance(client, p) is None
    strategy = {row["name"]: row["strategy"] for row in generation_scope(p)["modules"]}
    assert strategy[server.name] == "host_owned_weapon_performance"
    assert strategy[client.name] == "host_typed_client_ui"
    assert_prompt_invariant_routing(p)
    result = LuauCodeGenerator(NeverWritesLuau()).generate_with_self_correction(server, p)
    assert "GetState(player, \"RMMWeaponPerformance\")" in result
    assert "GetState(player, \"RMMTradeEntitlements\")" in result
    assert "setStats(tool, level + 1)" in result
    assert "saved[tool.Name] = {level = level + 1}" in result
    assert 'type(args.selection) ~= "string"' in result
    assert 'args.quantity ~= 1' in result
    assert '"WeaponRegistry"' not in result
    assert "tool:IsA(\"Tool\")" in result
    assert "coins.Value -= price" in result
    diagnostics = [d for d in LuauStaticAnalyzer().analyze_source(
        result, server.file_path) if d.severity == "ERROR"]
    assert not diagnostics, [(d.rule,d.message) for d in diagnostics]


def test_weapon_route_requires_real_ownership_and_validated_typed_pair():
    p, server, client = weapon_plan()
    d = p.game_design["dynamic_design"]
    for variant in ("no_client", "wrong_max_args", "untrusted_price", "no_profile", "non_weapon"):
        q = deepcopy(p)
        des = q.game_design["dynamic_design"]
        if variant == "no_client":
            q.modules = [m for m in q.modules if m.name != client.name]
        elif variant == "wrong_max_args":
            des["host_actions"]["WeaponPerformanceAction"]["max_args"] = 2
        elif variant == "untrusted_price":
            des["host_typed_actions"]["WeaponPerformanceAction"]["contract"]["inputs"].append(
                {"id":"clientPrice","type":"integer","min":1,"max":10000})
        elif variant == "no_profile":
            q.modules = [m for m in q.modules if m.name != "PlayerDataManager"]
        else:
            next(m for m in q.modules if m.name == server.name).description = (
                "Server handles displaying weapon market catalog")
        selected = next(m for m in q.modules if m.name == server.name)
        assert eligible_owned_weapon_performance(selected, q) is None, variant
