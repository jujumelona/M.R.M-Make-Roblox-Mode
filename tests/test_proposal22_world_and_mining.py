"""Regression for the real ownership/transport split in proposal (22).

Previous pipeline generated 2/22 modules then failed its passive
SpaceModeSetupF5E8F01Server full Luau file. The *next* module declared a
zero-argument RemoteFunction but omitted the gatherable resource Part.
Both are reproducible without a local generative coder.
"""
from copy import deepcopy

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.host_gameplay import render_host_gameplay
from roblox_mod_ai.host_mining_contract import ensure_mining_world_contract
from roblox_mod_ai.host_world_setup import render_host_world_setup
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.luau_service_contract import service_contract_checks
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap
from roblox_mod_ai.spec import ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService


class NoModel:
    def complete(self, *args, **kwargs):
        raise AssertionError("Host-owned setup and mining must never invoke small coder")

    def complete_json(self, *args, **kwargs):
        raise AssertionError("Host-owned setup and mining must never invoke small planner")


def proposal22_first_mechanics():
    setup = RobloxModuleSpec(
        module_id="dyn_0164d61fe784", name="SpaceModeSetupF5E8F01Server",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/SpaceModeSetupF5E8F01Server.luau",
        description=(
            "The server owns the dedicated space-mode state: it enables "
            "the themed environment, space-themed assets, and the dedicated "
            "game-mode setup, and it validates that the mode is active "
            "before any space-mode gameplay action is accepted."
        ),
    )
    mining = RobloxModuleSpec(
        module_id="dyn_c9b317d4e834",
        name="ResourceGatheringAndEarne23C0F11Server",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/ResourceGatheringAndEarne23C0F11Server.luau",
        description=(
            "The server owns all resource quantities, currency balances, and upgrade state. "
            "A player action is validated against the player's current currency balance "
            "before any deduction; the balance is decremented only after the resource yield "
            "is computed, and the resulting resource amount is added to the player's inventory. "
            "Currency is never modified by client-side scripts, and all balances are reconciled "
            "server-side. Resource nodes are finite and become depleted when their remaining "
            "yield reaches zero. Currency earned from gathering is ordinary in-game currency only."
        ),
    )
    client = RobloxModuleSpec(
        module_id="dyn_22775f26c856", name="ResourceGatheringAndEarne23C0F11Client",
        kind=ModuleKind.CLIENT_SCRIPT,
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        file_path="src/client/ResourceGatheringAndEarne23C0F11Client.client.luau",
        description="Client displays mining/harvesting, currency, and resource result.",
        depends_on=["mod_network_bridge"],
    )
    design = {
        "host_actions": {
            "ResourceGatheringAndEarne23C0F11Action": {
                "service": mining.name, "kind": "RemoteFunction", "max_args": 0,
            },
        },
        "remotes": {"ResourceGatheringAndEarne23C0F11Action": "RemoteFunction"},
        "host_client_actions": {
            client.name: {
                "remote": "ResourceGatheringAndEarne23C0F11Action",
                "label": "Gather resources", "kind": "RemoteFunction",
                "input_mode": "host_button", "argument_count": 0,
            },
        },
        "module_remotes": {
            mining.module_id: ["ResourceGatheringAndEarne23C0F11Action"],
            client.module_id: ["ResourceGatheringAndEarne23C0F11Action"],
        },
        "module_world_objects": {setup.module_id: [], mining.module_id: [],
                                 client.module_id: []},
        "world_objects": [
            {"name": "SpecialMineralNode75F66611", "class": "Part",
             "position": [24.0, 2.0, 24.0], "size": [4.0, 4.0, 4.0]},
            {"name": "AlienHumanoid9044DE11", "class": "Part",
             "position": [36.0, 2.0, 24.0], "size": [4.0, 4.0, 4.0]},
        ],
        "host_world_actions": {
            "SpecialMineralNode75F66611": {
                "service": "PlanetMineralMining75F6661Server",
                "action_text": "Planet Mineral Mining",
            },
        },
    }
    special_mineral = RobloxModuleSpec(
        module_id="dyn_e3fcd4b3b788", name="PlanetMineralMining75F6661Server",
        kind=ModuleKind.SERVER_MODULE,
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        file_path="src/server/PlanetMineralMining75F6661Server.luau",
        description="Planet mining of special minerals after reaching space.",
    )
    return RobloxProposal(
        game_title="SpaceResourceGame", description="Mine and build a ship",
        requested_prompt=("우주모드 인데 자원파밍 돈모으기 거래 등으로 우주선을 "
                          "부위마다 만들고 업그레이드해서 우주로 간다"),
        game_design={"dynamic_design": design},
        modules=[setup, mining, client, special_mineral],
    )


def test_proposal22_exact_passive_setup_is_host_generated_without_luau_model():
    p = proposal22_first_mechanics()
    gen = LuauCodeGenerator(NoModel())
    module = p.modules[0]
    code = gen.generate_with_self_correction(module, p)
    assert code == render_host_world_setup(module, p)
    assert code == render_host_gameplay(module, p)
    assert "Instance.new(\"Part\")" in code
    assert 'workspace:SetAttribute("RMMWorldSceneReady", true)' in code
    assert "function Service.start(services)" in code
    assert "function Service.isReady()" in code
    assert "function Service.handleAction" not in code
    assert 'player:SetAttribute("RMMSpaceUnlocked"' not in code
    checks = service_contract_checks(module.name, code, require_start=True, needs_action=False)
    assert all(r["passed"] for r in checks), checks


def test_noarg_mining_materializes_separate_ore_never_claims_special_minerals():
    p = proposal22_first_mechanics()
    original = deepcopy(p.game_design["dynamic_design"]["world_objects"])
    generated = ensure_mining_world_contract(p)
    assert len(generated) == 1
    node = generated[0]["resource_node"]
    assert node.startswith("ResourceNode")
    assert node != "SpecialMineralNode75F66611"
    assert p.game_design["dynamic_design"]["world_objects"][:2] == original
    assert p.game_design["dynamic_design"]["module_world_objects"][p.modules[1].module_id] == [node]
    assert ensure_mining_world_contract(p) == []
    gen = LuauCodeGenerator(NoModel())
    source = gen.generate_with_self_correction(p.modules[1], p)
    client = gen.generate_with_self_correction(p.modules[2], p)
    assert 'if select("#", ...) ~= 0 then return false end' in source
    assert "candidate = workspace:FindFirstChild(name, true)" in source
    assert "(root.Position - candidate.Position).Magnitude" in source
    assert "part = candidate" in source
    assert "node.remaining -= 1" in source
    assert "coins.Value += 1" in source
    assert 'progress.resources = ' in source
    assert "remote:InvokeServer()" in client
    assert "remote:InvokeServer(target)" not in client
    assert "MiningResult" in client
    assert "SpecialMineralNode75F66611" not in source
    assert "SpecialMineralNode75F66611" not in client


def test_rojo_and_bootstrap_still_have_the_exact_zero_argument_remote(tmp_path):
    p = proposal22_first_mechanics()
    materialized = ensure_mining_world_contract(p)
    target = materialized[0]["resource_node"]
    project = RobloxProjectGenerator(tmp_path).generate_rojo_project_json(p)
    assert project["tree"]["Workspace"][target]["$className"] == "Part"
    assert project["tree"]["Workspace"]["SpecialMineralNode75F66611"]["$className"] == "Part"
    assert project["tree"]["ReplicatedStorage"]["Remotes"]["ResourceGatheringAndEarne23C0F11Action"]["$className"] == "RemoteFunction"
    bootstrap = render_dynamic_server_bootstrap(p)
    assert 'WaitForChild("ResourceGatheringAndEarne23C0F11Action", 20)' in bootstrap
    assert 'if select("#", ...) > 0 then return nil end' in bootstrap


def test_all_host_sources_pass_static_luau_analyzer():
    p = proposal22_first_mechanics()
    ensure_mining_world_contract(p)
    analyzer = LuauStaticAnalyzer()
    gen = LuauCodeGenerator(NoModel())
    for module in p.modules[:3]:
        code = gen.generate_with_self_correction(module, p)
        errs = [e for e in analyzer.analyze_source(code, module.file_path)
                if e.severity == "ERROR"]
        assert not errs, [(e.rule, e.line_number, e.message) for e in errs]


def test_no_generic_passive_grant_and_no_unrelated_mining_creation():
    p = proposal22_first_mechanics()
    p.modules[0].description = "The player requests to activate a mode and receive launch permission."
    assert render_host_world_setup(p.modules[0], p) is None
    p = proposal22_first_mechanics()
    p.requested_prompt = "우주선 정비와 우주복 색상 변경"
    original = deepcopy(p.game_design["dynamic_design"])
    assert ensure_mining_world_contract(p) == []
    assert p.game_design["dynamic_design"] == original
    p = proposal22_first_mechanics()
    p.game_design["dynamic_design"]["host_actions"]["ResourceGatheringAndEarne23C0F11Action"]["kind"] = "RemoteEvent"
    assert ensure_mining_world_contract(p) == []
