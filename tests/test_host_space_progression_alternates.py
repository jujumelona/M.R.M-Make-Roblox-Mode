"""Alternate plan (23): ship sections, expansion, and launch gate are a single
persistent server progression, not three unconnected LLM-created state APIs.
"""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.luau_service_contract import service_contract_checks
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class NoModel:
    def complete(self, *_a, **_kw):
        raise AssertionError("Connected host-owned ship progression must not use 9B model")

    def complete_json(self, *_a, **_kw):
        raise AssertionError("Connected host-owned ship progression must not use 9B model")


def proposal23_ship():
    data = (
        ("ModularSpaceshipPartConstB327A61",
         "The server owns the modular spaceship construction system. When a player "
         "requests a part, the server validates the player's inventory, "
         "deducts resources and creates the part as a child of their owned spaceship.",
         "RemoteFunction"),
        ("SpaceshipUpgradeExpansionF063101",
         "The server owns all spaceship upgrade expansion state and checks that "
         "the ship exists and the player has sufficient resources for each upgrade.",
         "RemoteFunction"),
        ("SpaceLaunchGateAndLaunchS9368211",
         "The server owns the launch gate state and validates every launch attempt. "
         "The player may enter space only after the ship completion and upgrade "
         "prerequisites are satisfied.", "RemoteFunction"),
    )
    modules, actions, remotes, linked = [], {}, {}, {}
    for stem, description, kind in data:
        remote = stem + "Action"
        actions[remote] = {"service": stem + "Server", "kind": kind}
        remotes[remote] = kind
        server = RobloxModuleSpec(
            module_id="dyn_" + stem + "Server", name=stem + "Server",
            kind=ModuleKind.SERVER_MODULE,
            file_path="src/server/" + stem + "Server.luau",
            roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
            description=description,
        )
        client = RobloxModuleSpec(
            module_id="dyn_" + stem + "Client", name=stem + "Client",
            kind=ModuleKind.CLIENT_SCRIPT,
            file_path="src/client/" + stem + "Client.client.luau",
            roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
            description="Client requests server-authorized actions and shows state.",
            depends_on=["mod_network_bridge"],
        )
        modules += [server, client]
        linked[server.module_id] = [remote]
        linked[client.module_id] = [remote]
    return RobloxProposal(
        game_title="ShipProgression", description="Build upgrade launch",
        requested_prompt="우주선 부위마다 만들고 업그레이드 확장해서 우주로 나간다",
        modules=modules,
        game_design={"dynamic_design": {
            "host_actions": actions, "module_remotes": linked,
            "remotes": remotes, "world_objects": [],
        }},
    )


def test_plan23_ship_triplet_does_not_invoke_small_model_for_any_module():
    p = proposal23_ship()
    generator = LuauCodeGenerator(NoModel())
    for module in p.modules:
        module.code = "-- stale model-generated code, contains undefined vars"
    completed = generator.generate_all_modules(p)
    assert len(completed) == 6
    for m in completed:
        assert m.code == render_host_gameplay(m, p)
        assert m.code.startswith("--!strict")
        if m.kind == ModuleKind.SERVER_MODULE:
            checks = service_contract_checks(m.name, m.code,
                                             require_start=True, needs_action=True)
            assert all(t["passed"] for t in checks), checks


def test_plan23_build_and_upgrade_share_real_persistent_state():
    p = proposal23_ship()
    build = render_host_gameplay(p.modules[0], p)
    upgrade = render_host_gameplay(p.modules[2], p)
    launch = render_host_gameplay(p.modules[4], p)
    assert 'GetState(player, "RMMShipBuild")' in build
    assert 'GetState(player, "RMMInventory")' in build
    assert 'inventory.resources -= COSTS[requested]' in build
    assert 'build.sections[requested] = true' in build
    assert 'build.shipReady = build.sections.Engine == true' in build
    assert 'GetState(player, "RMMTravelProgress")' in upgrade
    assert "build.shipReady ~= true" in upgrade
    assert 'coins.Value -= coinCost' in upgrade
    assert "progress.unlocked = progress.tier >= MAX_TIER" in upgrade
    assert 'GetState(player, "RMMTravelProgress")' in launch
    assert "profile.unlocked ~= true or build.shipReady ~= true" in launch
    assert 'root.Position - gate.Position' in launch
    assert "Instance.new(\"Part\")" in launch
    assert "RMMLaunchGate" in launch
    assert "character:PivotTo" in launch


def test_launch_is_remote_function_but_prior_mode_event_remains_separate():
    p = proposal23_ship()
    src = render_host_gameplay(p.modules[5], p)
    assert "remote:InvokeServer()" in src
    assert "remote:FireServer()" not in src
    bootstrap = render_dynamic_server_bootstrap(p)
    assert bootstrap.count("remote.OnServerInvoke = function(player, ...)") == 3
    assert 'WaitForChild("SpaceLaunchGateAndLaunchS9368211Action")' in bootstrap


def test_all_alternate_roles_pass_real_parser_static_checks():
    p = proposal23_ship()
    gen = LuauCodeGenerator(NoModel())
    analyzer = LuauStaticAnalyzer()
    for m in p.modules:
        source = gen.generate_with_self_correction(m, p)
        problems = [d for d in analyzer.analyze_source(source, m.file_path)
                    if d.severity == "ERROR"]
        assert not problems, [(d.rule, d.message) for d in problems]


def test_triplet_requires_all_owners_and_exact_remote_classes():
    p = proposal23_ship()
    p.modules = [m for m in p.modules
                 if m.name != "SpaceshipUpgradeExpansionF063101Server"]
    assert render_host_gameplay(p.modules[0], p) is None
    p = proposal23_ship()
    p.game_design["dynamic_design"]["host_actions"][
        "SpaceLaunchGateAndLaunchS9368211Action"]["kind"] = "RemoteEvent"
    assert render_host_gameplay(p.modules[4], p) is None
    p = proposal23_ship()
    p.modules[0].description = "A decorative model with no ship parts or resource validation"
    assert render_host_gameplay(p.modules[0], p) is None
