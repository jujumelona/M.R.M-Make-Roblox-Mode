"""State/progression coordinating services must not become mint-anything remotes."""
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.generation_scope import generation_scope
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_progress_dashboard import eligible_progress_dashboard
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class NoCodeModel:
    def complete(self, *_args, **_kwargs):
        raise AssertionError("A cross-system dashboard must not ask model for arbitrary mutation code")


def make_plan():
    def module(name, kind, desc):
        return RobloxModuleSpec(
            module_id="dyn_" + name,
            name=name, kind=kind,
            file_path=("src/server/" + name + ".luau"
                       if kind == ModuleKind.SERVER_MODULE else
                       "src/client/" + name + ".client.luau"),
            roblox_service=(RobloxService.SERVER_SCRIPT_SERVICE
                            if kind == ModuleKind.SERVER_MODULE
                            else RobloxService.STARTER_PLAYER_SCRIPTS),
            description=desc,
        )
    owner = module("GameProgressCoordinatorServer", ModuleKind.SERVER_MODULE,
        "The server owns authoritative game state and progression for a modular "
        "ship, current currency, earned upgrades, and planetary expansion. "
        "It validates every requested activity and tracks account state.")
    client = module("GameProgressCoordinatorClient", ModuleKind.CLIENT_SCRIPT,
        "The client renders the current game progress, owned parts, and currency.")
    mining = module("HarvestingServer", ModuleKind.SERVER_MODULE,
                    "Player mining and harvesting earn resource and currency with cooldowns.")
    shopping = module("MarketplaceServer", ModuleKind.SERVER_MODULE,
                      "Shop validates currency purchase of equipment and upgrades.")
    building = module("ShipBuilderServer", ModuleKind.SERVER_MODULE,
                      "Player constructs modular spaceship parts from owned resources.")
    travel = module("PlanetTravelServer", ModuleKind.SERVER_MODULE,
                    "Player launch and travel to planets is server-authorized.")
    remote = "CoordinatedProgressRequest"
    return RobloxProposal(
        game_title="Arbitrary game", description="Game with composite state",
        requested_prompt="An open-world sandbox game with shared progress",
        game_design={"dynamic_design": {
            "host_actions": {remote: {"service": owner.name, "kind": "RemoteFunction"}},
            "remotes": {remote: "RemoteFunction"},
            "module_remotes": {client.module_id: [remote], owner.module_id: [remote]},
        }},
        modules=[owner, client, mining, shopping, building, travel],
    )


def test_cross_system_progress_is_read_only_host_not_bogus_mutation():
    plan = make_plan()
    owner, client = plan.modules[:2]
    assert eligible_progress_dashboard(owner, plan)
    assert eligible_progress_dashboard(client, plan)
    scoped = generation_scope(plan)
    selected = [m for m in scoped["modules"] if m["name"] in {owner.name, client.name}]
    assert all(x["strategy"] == "host_verified_template" for x in selected)
    gen = LuauCodeGenerator(NoCodeModel())
    server_code = gen.generate_module_code(owner, plan)
    client_code = gen.generate_module_code(client, plan)
    assert server_code == render_host_gameplay(owner, plan)
    assert client_code == render_host_gameplay(client, plan)
    assert 'manager.GetState(player, "RMMInventory")' in server_code
    assert 'manager.GetState(player, "RMMShipSections")' in server_code
    assert 'manager.GetState(player, "RMMUpgradePurchases")' in server_code
    assert 'select("#", ...)' in server_code
    assert 'action ~= "snapshot"' in server_code
    assert 'reason = "use_domain_service"' in server_code
    assert 'remote:InvokeServer("snapshot")' in client_code
    for not_allowed in ("SetState(", "tonumber(args[1])", "profile.resources +",
                        "math.floor(amount)", "DataStoreService"):
        assert not_allowed not in server_code
    analyzer = LuauStaticAnalyzer()
    for peer, source in [(owner, server_code), (client, client_code)]:
        errors = [d for d in analyzer.analyze_source(source, peer.file_path)
                  if d.severity == "ERROR"]
        assert not errors, [(x.rule, x.line_number, x.message) for x in errors]


def test_coordinator_fails_closed_without_real_domain_services():
    plan = make_plan()
    plan.modules = plan.modules[:2]
    assert eligible_progress_dashboard(plan.modules[0], plan) is None
    plan = make_plan()
    plan.game_design["dynamic_design"]["host_actions"]["CoordinatedProgressRequest"]["kind"] = "RemoteEvent"
    assert eligible_progress_dashboard(plan.modules[0], plan) is None
    plan = make_plan()
    plan.modules[0].description = "A cosmetic GUI showing the player's avatar."
    assert eligible_progress_dashboard(plan.modules[0], plan) is None


def test_no_module_name_or_game_title_special_case():
    plan = make_plan()
    plan.modules[0].name = "ArbitraryCompositeStatsServer"
    plan.modules[1].name = "ArbitraryCompositeStatsClient"
    plan.game_design["dynamic_design"]["host_actions"]["CoordinatedProgressRequest"]["service"] = plan.modules[0].name
    assert render_host_gameplay(plan.modules[0], plan) is not None
    assert render_host_gameplay(plan.modules[1], plan) is not None
