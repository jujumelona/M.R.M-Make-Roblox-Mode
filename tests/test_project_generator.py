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
