"""Reproduce proposal (21): mode activation failed before any gameplay code.

The server mode request cannot mint ship unlock state. Its input is a
RemoteEvent, while ship assembly/upgrades are RemoteFunctions. This exact
combination must be handled without asking the small coder for full Luau.
"""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_space_progression import render_host_space_progression
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.luau_service_contract import service_contract_checks
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


class NoModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("Host-owned player progression must not run small coder")

    def complete_json(self, *_args, **_kwargs):
        raise AssertionError("Host-owned player progression must not run small coder")


def proposal21_progression():
    services = (
        ("SpaceModeActivationF5E8F01", "space-mode", "RemoteEvent",
         "The server owns the space-mode state machine. Entering space "
         "mode requires a validated launch condition, persisted by the server."),
        ("SectionBySectionSpaceship2A35951", "ship-build", "RemoteFunction",
         "The server owns spaceship sections: a player builds the ship "
         "section by section, validates resources, and tracks completed parts."),
        ("SpaceshipUpgradeUnlockAndABF5BA1", "ship-upgrade", "RemoteFunction",
         "The server owns spaceship upgrade progression, validates the required "
         "resources, and unlocks space travel only after upgrading the ship."),
    )
    modules = []
    actions = {}
    remotes = {}
    for stem, _label, kind, description in services:
        name = stem + "Server"
        remote = stem + "Action"
        actions[remote] = {"service": name, "kind": kind}
        remotes[remote] = kind
        modules.append(RobloxModuleSpec(
            module_id="dyn_" + stem, name=name, kind=ModuleKind.SERVER_MODULE,
            file_path="src/server/" + name + ".luau",
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
            description=description,
        ))
        modules.append(RobloxModuleSpec(
            module_id="dyn_" + stem + "Client", name=stem + "Client",
            kind=ModuleKind.CLIENT_SCRIPT,
            file_path="src/client/" + stem + "Client.client.luau",
            roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
            description="Client displays the state and calls only the authorized remote.",
            depends_on=["mod_network_bridge"],
        ))
    return RobloxProposal(
        requested_prompt="자원 파밍 돈모으고 우주선 부위마다 만든 다음 업그레이드하고 우주로 나가기",
        game_title="SpaceProgression",
        description="Assemble and upgrade a ship to unlock safe travel",
        modules=modules,
        game_design={"dynamic_design": {
            "host_actions": actions, "remotes": remotes,
            "host_world_actions": {}, "world_objects": [],
        }},
    )


def test_uploaded_mode_failure_and_linked_ship_roles_are_host_owned():
    proposal = proposal21_progression()
    gen = LuauCodeGenerator(NoModel())
    for module in proposal.modules:
        code = gen.generate_with_self_correction(module, proposal)
        assert code == render_host_gameplay(module, proposal)
        assert code == render_host_space_progression(module, proposal)
        assert "TODO" not in code
        assert "placeholder" not in code
        if module.kind == ModuleKind.SERVER_MODULE:
            assert code.startswith("--!strict")
            assert code.rstrip().endswith("return Service")
            checks = service_contract_checks(module.name, code, require_start=True, needs_action=True)
            assert all(c["passed"] for c in checks), checks


def test_space_transition_requires_server_owned_built_ship_and_unlock():
    p = proposal21_progression()
    server = p.modules[0]
    client = p.modules[1]
    source = render_host_space_progression(server, p)
    input_source = render_host_space_progression(client, p)
    assert 'GetState(player, "RMMShipBuild")' in source
    assert 'GetState(player, "RMMTravelProgress")' in source
    assert "profile.unlocked ~= true or build.shipReady ~= true" in source
    assert "if select" not in input_source
    assert "remote:FireServer()" in input_source
    assert "RMMInSpace" in input_source
    assert "local profile = services.PlayerDataManager.GetState" in source
    assert "profile.inSpace = true" in source
    assert "character:PivotTo" in source
    assert "profile.unlocked = true" not in source
    assert "shipReady = true" not in source


def test_real_building_creates_roblox_parts_and_upgrade_requires_payment():
    p = proposal21_progression()
    builder, upgrader = p.modules[2], p.modules[4]
    building = render_host_gameplay(builder, p)
    upgrade = render_host_gameplay(upgrader, p)
    assert 'GetState(player, "RMMInventory")' in building
    assert 'GetState(player, "RMMShipBuild")' in building
    assert 'build.sections[requested] = true' in building
    assert "Instance.new(\"Part\")" in building
    assert 'build.shipReady = build.sections.Engine == true' in building
    assert 'inventory.resources -= COSTS[requested]' in building
    assert "if not progress or not build or not inventory or build.shipReady ~= true" in upgrade
    assert "coins.Value < coinCost" in upgrade
    assert "inventory.resources -= oreCost" in upgrade
    assert "coins.Value -= coinCost" in upgrade
    assert "progress.unlocked = progress.tier >= MAX_TIER" in upgrade
    assert 'GetState(player, "RMMTravelProgress")' in upgrade


def test_bootstrap_connects_exact_declared_event_and_function_types():
    p = proposal21_progression()
    bootstrap = render_dynamic_server_bootstrap(p)
    assert 'WaitForChild("SpaceModeActivationF5E8F01Action")' in bootstrap
    assert 'WaitForChild("SectionBySectionSpaceship2A35951Action")' in bootstrap
    assert 'WaitForChild("SpaceshipUpgradeUnlockAndABF5BA1Action")' in bootstrap
    assert "remote.OnServerEvent:Connect" in bootstrap
    assert "remote.OnServerInvoke = function" in bootstrap
    assert bootstrap.count("service.handleAction(player, services, ...)") == 3


def test_all_progression_sources_pass_luau_static_analyzer():
    p = proposal21_progression()
    analyzer = LuauStaticAnalyzer()
    for module in p.modules:
        code = render_host_gameplay(module, p)
        errors = [d for d in analyzer.analyze_source(code, module.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(e.rule, e.line_number, e.message) for e in errors]


def test_missing_required_owner_or_wrong_ingress_remains_unmatched():
    p = proposal21_progression()
    p.modules = [m for m in p.modules
                 if m.name != "SectionBySectionSpaceship2A35951Server"]
    assert render_host_gameplay(p.modules[0], p) is None
    p = proposal21_progression()
    p.game_design["dynamic_design"]["host_actions"]["SpaceModeActivationF5E8F01Action"]["kind"] = "RemoteFunction"
    assert render_host_gameplay(p.modules[0], p) is None
    p = proposal21_progression()
    p.game_design["dynamic_design"]["host_actions"].pop("SpaceModeActivationF5E8F01Action")
    assert render_host_gameplay(p.modules[0], p) is None


def test_does_not_touch_an_unrelated_game_or_accept_unauthorized_roles():
    p = proposal21_progression()
    p.modules[0].name = "RandomDanceServer"
    assert render_host_gameplay(p.modules[0], p) is None
