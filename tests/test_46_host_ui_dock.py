"""46: generated first-party UI actions must not overlap as independent HUDs."""
from pathlib import Path

import pytest

from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.spec import (
    ModuleKind, RobloxModuleSpec, RobloxProposal, RobloxService,
)


def make_game(panel_count=3, conflicting=False):
    names = ("RMMShipAssembly", "RMMRankUpgrade", "RMM_AlienCombat")
    modules = [
        RobloxModuleSpec(
            module_id=f"dyn_ui_{index}", name=f"Action{index}",
            kind=ModuleKind.CLIENT_SCRIPT,
            file_path=f"src/client/Action{index}.client.luau",
            roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
            code='--!strict\nlocal gui=Instance.new("ScreenGui")\ngui.Name = "' +
                 name + '"\n' +
                 'game.ReplicatedStorage.Remotes.DoAction:InvokeServer({})\n',
        )
        for index, name in enumerate(names[:panel_count])
    ]
    if conflicting:
        modules.append(RobloxModuleSpec(
            module_id="dyn_collision", name="RMMHUDLayout",
            kind=ModuleKind.CLIENT_SCRIPT,
            file_path="src/client/RMMHUDLayout.client.luau",
            roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
            code="--!strict\nprint('user-owned HUD')\n",
        ))
    return RobloxProposal(
        requested_prompt="Space action game",
        game_title="NoOverlaySpace",
        description="Game with multiple action panels",
        game_design={},
        modules=modules,
    )


def test_ui_dock_generated_for_three_source_owned_actions(tmp_path: Path):
    root = tmp_path / "output"
    paths = RobloxProjectGenerator(tmp_path).materialize_project_tree(
        make_game(), root)
    dock = root / "src/client/RMMHUDLayout.client.luau"
    assert dock.is_file()
    assert paths["RMMHUDLayout"] == dock
    source = dock.read_text(encoding="utf-8")
    assert "UIListLayout" in source
    assert "ChildAdded" in source
    assert "child.Parent=section.frame" in source
    assert "actionGuis[candidate.Name]==true" in source
    assert 'gui.Name="RMMUnifiedHUD"' in source
    assert "OnServerInvoke" not in source
    assert source.count("RemoteFunction") == 0


def test_not_added_to_small_game(tmp_path: Path):
    root = tmp_path / "output"
    RobloxProjectGenerator(tmp_path).materialize_project_tree(
        make_game(panel_count=2), root)
    assert not (root / "src/client/RMMHUDLayout.client.luau").exists()


def test_existing_custom_hud_is_never_overwritten(tmp_path: Path):
    root = tmp_path / "output"
    with pytest.raises(ValueError, match="HUD source conflicts"):
        RobloxProjectGenerator(tmp_path).materialize_project_tree(
            make_game(conflicting=True), root)
    assert (root / "src/client/RMMHUDLayout.client.luau").read_text().startswith(
        "--!strict\nprint('user-owned HUD')")
