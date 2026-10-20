"""Code-level regressions for real generated Roblox runtime semantics.

These assertions inspect exported executable Luau text and bootstrap startup
order, not CI results or claims of Roblox Studio end-to-end verification.
"""
from roblox_mod_ai.server_modules import (
    normalize_dynamic_server_modules, render_dynamic_server_bootstrap,
)
from roblox_mod_ai.host_mining import render_host_mining
from roblox_mod_ai.host_space_progression import render_host_space_progression
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)
from test_host_space_progression_alternates import proposal23_ship
from test_source_owned_mining_site import uploaded_mining_plan


def _server(name, mid, depends=()):
    return RobloxModuleSpec(
        module_id=mid, name=name, kind=ModuleKind.SERVER_MODULE,
        file_path="src/server/" + name + ".luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="A persistent server runtime service.",
        depends_on=list(depends),
    )


def test_bootstrap_starts_dependencies_before_alphabetically_earlier_dependents():
    # ZStorage must start before AConsumer, even though lexicographic sorting
    # would start AConsumer first.
    data = _server("PlayerDataManager", "mod_player_data")
    producer = _server("ZStorage", "dyn_storage")
    consumer = _server("AConsumer", "dyn_consumer", ["dyn_storage"])
    proposal = RobloxProposal(
        requested_prompt="Create persistent services",
        game_title="DependencyStartup", description="Linked host services",
        game_design={"dynamic_design": {"host_actions": {}, "world_objects": []}},
        modules=[consumer, data, producer],
    )
    source = render_dynamic_server_bootstrap(proposal)
    active = source.split("local active = {", 1)[1].split("}", 1)[0]
    assert active.index('"PlayerDataManager"') < active.index('"ZStorage"')
    assert active.index('"ZStorage"') < active.index('"AConsumer"')
    assert "service.start(services)" in source


def test_server_normalization_preserves_real_dependencies_not_network_bridge():
    data = _server("PlayerDataManager", "mod_player_data")
    producer = _server("ZStorage", "dyn_storage")
    consumer = RobloxModuleSpec(
        module_id="dyn_consumer", name="AConsumer",
        kind=ModuleKind.SERVER_SCRIPT,
        file_path="src/server/AConsumer.server.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        description="The dynamic service depends on the server storage API.",
        depends_on=["dyn_storage", "mod_network_bridge"],
    )
    proposal = RobloxProposal(
        requested_prompt="Link persistent Roblox services",
        game_title="NormalizedDependency", description="Service dependencies",
        game_design={"dynamic_design": {"world_objects": [], "host_actions": {}}},
        modules=[consumer, data, producer],
    )
    assert normalize_dynamic_server_modules(proposal)
    assert consumer.kind == ModuleKind.SERVER_MODULE
    assert consumer.depends_on == ["dyn_storage"]
    source = render_dynamic_server_bootstrap(proposal)
    active = source.split("local active = {", 1)[1].split("}", 1)[0]
    assert active.index('"ZStorage"') < active.index('"AConsumer"')


def test_space_mode_does_not_persist_phantom_orbit_through_respawn():
    proposal = proposal23_ship()
    launch = next(m for m in proposal.modules
                  if m.name.startswith("SpaceLaunchGateAndLaunchS")
                  and m.kind == ModuleKind.SERVER_MODULE)
    server = render_host_space_progression(launch, proposal)
    assert server is not None
    assert 'progress.inSpace = false' in server
    assert 'player.CharacterAdded:Connect(function()' in server
    assert 'current.inSpace = false' in server
    assert 'status(player, services)' in server
    assert 'profile.unlocked ~= true or build.shipReady ~= true' in server


def test_ship_lots_do_not_alias_every_eighth_player():
    proposal = proposal23_ship()
    builder = proposal.modules[0]
    code = render_host_space_progression(builder, proposal)
    assert code is not None
    assert 'while occupiedLots[lot] do' in code
    assert 'lotByPlayer[player] = lot' in code
    assert 'math.floor(lot / 8) * 38' in code
    assert 'occupiedLots[lot] = nil' in code
    assert 'player.UserId % 8' not in code


def test_space_ui_launch_entitlement_requires_built_ship_not_just_save_flag():
    proposal = proposal23_ship()
    upgrade = proposal.modules[2]
    code = render_host_space_progression(upgrade, proposal)
    assert code is not None
    assert 'progress.unlocked == true and build ~= nil and build.shipReady == true' in code
    assert 'publish(player, progress, build)' in code


def test_empty_resource_part_cannot_block_valid_nearby_vein():
    proposal = uploaded_mining_plan()
    plan = proposal.game_design["dynamic_design"]
    action = next(iter(plan["host_actions"].values()))
    action["max_args"] = 0
    code = render_host_mining(proposal.modules[0], proposal)
    assert code is not None
    assert 'local resource = getNode(candidate)' in code
    assert 'resource and resource.remaining > 0' in code
