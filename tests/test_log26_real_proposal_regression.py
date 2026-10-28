"""Regression extracted from failure_logs (26), plan (62) generated structure.

Uses reproductions of the actual module descriptions and source-owned world
names but no uploaded private logs. Covers the exact model-risk handoff.
"""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_verified_typed_effects import (
    eligible_verified_effect, render_verified_effect,
)
from roblox_mod_ai.typed_action_contract import render_typed_client
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind
from test_log25_verified_typed_effects import _fixture, NeverCallCoder


REAL_DESCRIPTIONS = {
    "purchase": "Validate the request against a server-owned purchase record "
                "for the weapon upgrade, then debit the buyer's owned currency "
                "balance and apply the upgrade state. Reject requests with "
                "missing or invalid identifiers, insufficient balance, expired "
                "records, or any attempt to supply a currency amount.",
    "combat": "Validate that the player is on the alien planet and that the "
              "target is a server-owned alien entity within range; apply a "
              "real server-owned damage mutation to that entity and resolve "
              "the combat result server-side. Reject requests targeting "
              "non-alien entities, players, or entities outside the valid combat zone.",
    "harvest": "Validate that the player is within range of a server-owned "
               "special mineral deposit and that the deposit has remaining "
               "extractable quantity. On success, mutate the deposit's "
               "server-owned quantity and increment the player's server-owned "
               "inventory count. Reject requests from players outside range, "
               "against depleted deposits, or with invalid deposit references.",
}


def _log26_fixture(role):
    plan, server = _fixture(role)
    server.description = REAL_DESCRIPTIONS[role]
    world = plan.game_design["dynamic_design"]
    old_ore = "SpecialMineralDeposit1"
    old_alien = "AlienEntities1"
    replacements = {
        old_ore: "SpecialMineralDeposit77D3DB31",
        old_alien: "AlienEntitiesSpawnedOnT77D3DB11",
        "OrbitArrival": "RMMOrbitArrival_4b4b05bceb",
    }
    for part in world["world_objects"]:
        part["name"] = replacements.get(part["name"], part["name"])
    for key, names in world["module_world_objects"].items():
        world["module_world_objects"][key] = [
            replacements.get(n, n) for n in names
        ]
    world["host_arrival_materializations"][0]["arrival"] = replacements["OrbitArrival"]
    world["host_typed_actions"]["ActionSomethingRemote"]["world_entities"] = (
        [] if role == "purchase" else
        ["Alien entities spawned on the alien planet"] if role == "combat"
        else ["SpecialMineralDeposit"])
    return plan, server


def test_log26_exact_server_descriptions_and_world_names_resolve_to_host():
    for role in ("purchase", "combat", "harvest"):
        plan, server = _log26_fixture(role)
        selected = eligible_verified_effect(server, plan)
        assert selected is not None, role
        assert selected[0] == {
            "purchase": "owned_tool_purchase",
            "combat": "world_damage",
            "harvest": "world_harvest",
        }[role]
        source = render_verified_effect(server, plan)
        assert source and "function Service.handleAction" in source
        assert LuauCodeGenerator(NeverCallCoder()).generate_module_code(server, plan) == source
        scope = generation_scope(plan)
        assert next(row["strategy"] for row in scope["modules"]
                    if row["name"] == server.name) == "host_verified_typed_effect"
        errors = [diag for diag in LuauStaticAnalyzer().analyze_source(
            source, server.file_path) if diag.severity == "ERROR"]
        assert not errors, [(e.rule, e.message) for e in errors]


def test_log26_world_id_prefill_is_actual_server_owned_part():
    for role, exact_part in (
        ("combat", "AlienEntitiesSpawnedOnT77D3DB11"),
        ("harvest", "SpecialMineralDeposit77D3DB31"),
    ):
        plan, _ = _log26_fixture(role)
        client = next(m for m in plan.modules
                      if m.kind == ModuleKind.CLIENT_SCRIPT)
        code = render_typed_client(client, plan)
        assert code is not None
        assert 'box.Text = "' + exact_part + '"' in code
        assert 'remote:InvokeServer(payload)' in code


def test_log26_unmatched_description_fails_closed_not_fake_success():
    plan, server = _log26_fixture("harvest")
    server.description = "Show a mineral icon when opening the HUD"
    assert render_verified_effect(server, plan) is None
