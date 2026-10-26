"""Tests for RobloxProjectGenerator (.rbxlx XML and Rojo generation)."""

import xml.etree.ElementTree as ET
from pathlib import Path
from roblox_mod_ai import (
    ModuleKind,
    RobloxModuleSpec,
    RobloxProjectGenerator,
    RobloxProposal,
    RobloxService,
)


def test_roblox_project_and_rbxlx_generation(tmp_path: Path):
    generator = RobloxProjectGenerator(tmp_path)

    proposal = RobloxProposal(
        requested_prompt="Obstacle Parkour",
        game_title="ObbyRun",
        description="Speed parkour game",
        game_design={},
        modules=[
            RobloxModuleSpec(
                module_id="mod_server",
                name="CheckpointManager",
                kind=ModuleKind.SERVER_SCRIPT,
                file_path="src/server/CheckpointManager.server.luau",
                roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
                code="--!strict\nprint('Checkpoint server running')",
            ),
            RobloxModuleSpec(
                module_id="mod_client",
                name="TimerHUD",
                kind=ModuleKind.CLIENT_SCRIPT,
                file_path="src/client/TimerHUD.client.luau",
                roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
                code="--!strict\nprint('Timer running on client')",
            ),
        ],
    )

    # Test file tree materialization
    project_dir = tmp_path / "project_files"
    generator.materialize_project_tree(proposal, project_dir)

    assert (project_dir / "default.project.json").is_file()
    assert (project_dir / "wally.toml").is_file()
    assert "evaera/promise" in (project_dir / "wally.toml").read_text(encoding="utf-8")
    assert (project_dir / "src/server/CheckpointManager.server.luau").is_file()
    assert (project_dir / "src/client/TimerHUD.client.luau").is_file()

    # Test .rbxlx XML compilation
    rbxlx_path = tmp_path / "ObbyRun.rbxlx"
    generator.build_rbxlx_place_file(proposal, rbxlx_path)

    assert rbxlx_path.is_file()

    # Validate XML parsing
    tree = ET.parse(str(rbxlx_path))
    root = tree.getroot()
    assert root.tag == "roblox"
    assert root.attrib.get("version") == "4"

    # Verify Service items exist
    item_classes = [item.attrib.get("class") for item in root.findall("Item")]
    assert "Workspace" in item_classes
    assert "ServerScriptService" in item_classes
    assert "StarterPlayer" in item_classes
    assert "ReplicatedStorage" in item_classes

    # Verify script code is embedded in ProtectedString
    script_items = root.findall(".//Item[@class='Script']")
    assert len(script_items) >= 1
    found_source = False
    for script in script_items:
        source_elem = script.find(".//ProtectedString[@name='Source']")
        if source_elem is not None and "Checkpoint server running" in (source_elem.text or ""):
            found_source = True
            break
    assert found_source


def test_modding_system_generation():
    from roblox_mod_ai.code_generator import LuauCodeGenerator
    generator = LuauCodeGenerator()
    proposal = RobloxProposal(
        requested_prompt="Sandbox game with modding support",
        game_title="SandboxWorld",
        description="Sandbox game",
        game_design={},
        modules=[],
    )
    mod = RobloxModuleSpec(
        module_id="mod_system",
        name="ModdingSystem",
        kind="shared_module",
        file_path="src/shared/ModdingSystem.luau",
        roblox_service=RobloxService.REPLICATED_STORAGE,
    )
    code = generator.generate_module_code(mod, proposal)
    assert "registerMod" in code
    assert "exportModToJSON" in code
    assert "importModFromJSON" in code
    assert "damageMultiplier" in code



def test_generated_jest_config_contains_real_newline(tmp_path):
    from roblox_mod_ai.spec import RobloxProposal
    from roblox_mod_ai.project_generator import RobloxProjectGenerator
    proposal=RobloxProposal(requested_prompt="demo",game_title="Demo",description="",
        game_design={})
    project=tmp_path/"sample"
    RobloxProjectGenerator(tmp_path).materialize_project_tree(proposal,project)
    source=(project/"tests/jest.config.lua").read_text(encoding="utf-8")
    assert source == 'return { testMatch = {"**/*.spec"} }\n'
    assert r"\n" not in source


def test_rojo_world_positions_use_serialized_cframe_not_derived_position(tmp_path):
    proposal = RobloxProposal(
        requested_prompt="우주선 제작 후 우주 이동", game_title="Space",
        description="", modules=[],
        game_design={"dynamic_design": {
            "world_objects": [
                {"name": "RMMOrbitArrival_real", "class": "Part",
                 "size": [96, 4, 96], "position": [0, 8000, 0]},
                {"name": "PlanetTarget_real", "class": "Part",
                 "size": [6, 7, 6], "position": [20, 8012, 0]},
            ],
            "remotes": {},
        }},
    )
    project = RobloxProjectGenerator(tmp_path).generate_rojo_project_json(proposal)
    ws = project["tree"]["Workspace"]
    for name, coords in (
        ("RMMOrbitArrival_real", [0, 8000, 0]),
        ("PlanetTarget_real", [20, 8012, 0]),
        ("Baseplate", [0, -10, 0]),
        ("SpawnLocation", [0, 1, 0]),
    ):
        props = ws[name]["$properties"]
        assert "Position" not in props, name
        assert props["CFrame"] == [*coords, 1, 0, 0, 0, 1, 0, 0, 0, 1]


def test_standalone_rbxlx_part_contains_complete_rotation_matrix(tmp_path):
    proposal = RobloxProposal(
        requested_prompt="Demo", game_title="Demo",
        description="", modules=[], game_design={}
    )
    generated = tmp_path / "test.rbxlx"
    RobloxProjectGenerator(tmp_path).build_rbxlx_place_file(
        proposal, generated
    )
    root = ET.parse(generated).getroot()
    part = next(item for item in root.findall(".//Item[@class='Part']")
                if item.findtext("./Properties/string[@name='Name']") == "Baseplate")
    pose = part.find("./Properties/CoordinateFrame[@name='CFrame']")
    assert pose is not None
    for component, expected in (
        ("X", "0"), ("Y", "-10"), ("Z", "0"),
        ("R00", "1"), ("R01", "0"), ("R02", "0"),
        ("R10", "0"), ("R11", "1"), ("R12", "0"),
        ("R20", "0"), ("R21", "0"), ("R22", "1"),
    ):
        assert pose.findtext(component) == expected
