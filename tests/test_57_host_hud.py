"""Regression: action HUD selection derives from executable Remotes, not names."""
from pathlib import Path
from roblox_mod_ai.host_hud import (
    HUD_FILE, install_host_hud, render_host_hud, action_gui_names,
)


def _client(root:Path,filename:str,gui:str,remote:bool=True):
    folder=root/"src"/"client"
    folder.mkdir(parents=True,exist_ok=True)
    code=('local gui=Instance.new("ScreenGui")\n'
          'gui.Name="'+gui+'"\n'
          'gui.Parent=game.Players.LocalPlayer.PlayerGui\n')
    if remote:
        code+='local result=game.ReplicatedStorage.Remotes.SomeAction:InvokeServer({})\n'
    (folder/(filename+".client.luau")).write_text(code,encoding="utf-8")


def test_57_real_action_screens_packaged_without_mutating_original_scripts(tmp_path):
    _client(tmp_path,"Worker","FarmingPanel")
    _client(tmp_path,"Tools","CraftingPanel")
    _client(tmp_path,"Quest","QuestJournal",remote=False)
    originals={p.name:p.read_bytes() for p in (tmp_path/"src"/"client").glob("*.luau")}
    assert action_gui_names(tmp_path)==["CraftingPanel","FarmingPanel"]
    assert install_host_hud(tmp_path)
    actual=(tmp_path/"src"/"client"/HUD_FILE).read_text()
    assert actual==render_host_hud(action_gui_names(tmp_path))
    assert '["' not in actual or 'actionGuis=' in actual
    for token in ("actionGuis[candidate.Name]==true",
                  "child.Parent=section.frame",
                  "candidate.ChildAdded:Connect(function(child)",
                  "playerGui.ChildAdded:Connect(register)"):
        assert token in actual
    assert "QuestJournal" not in actual
    assert originals=={p.name:p.read_bytes() for p in (tmp_path/"src"/"client").glob("*.luau")
                       if p.name!=HUD_FILE}
    assert install_host_hud(tmp_path)


def test_57_single_action_or_no_remote_does_not_generate_hud(tmp_path):
    _client(tmp_path,"Onboard","RMMOnboarding",remote=False)
    _client(tmp_path,"Inventory","AncientMenu",remote=False)
    assert not install_host_hud(tmp_path)
    _client(tmp_path,"Mine","MinerAction")
    assert not install_host_hud(tmp_path)
    _client(tmp_path,"Trade","MerchantAction")
    assert install_host_hud(tmp_path)
    result=(tmp_path/"src"/"client"/HUD_FILE).read_text()
    assert "MinerAction" in result and "MerchantAction" in result
    assert "AncientMenu" not in result


def test_57_existing_different_hud_is_not_silently_overwritten(tmp_path):
    import pytest
    _client(tmp_path,"Alpha","AlphaPanel")
    _client(tmp_path,"Beta","BetaPanel")
    path=tmp_path/"src"/"client"/HUD_FILE
    path.write_text("--!strict\nerror('my original code')\n")
    with pytest.raises(ValueError,match="HUD source conflicts"):
        install_host_hud(tmp_path)
    assert "my original code" in path.read_text()


def test_safe_regeneration_adds_new_action_without_overwriting_manual_edits(tmp_path):
    import json
    import pytest
    _client(tmp_path,"Trader","MerchantPanel")
    _client(tmp_path,"Builder","WorkshopPanel")
    assert install_host_hud(tmp_path)
    target=tmp_path/"src"/"client"/HUD_FILE
    receipt=tmp_path/".rmm_hud_source_receipt.json"
    assert "MerchantPanel" in target.read_text()
    sealed=json.loads(receipt.read_text())
    assert sealed["file"]==HUD_FILE
    _client(tmp_path,"Runner","RacePanel")
    assert install_host_hud(tmp_path)
    assert "RacePanel" in target.read_text()
    # Once edited by a human, even in an auto-managed file, never overwrite.
    target.write_text(target.read_text()+"\\n-- hand edited\\n")
    _client(tmp_path,"Gallery","GalleryPanel")
    with pytest.raises(ValueError,match="HUD source conflicts"):
        install_host_hud(tmp_path)


def test_source_scan_does_not_infer_remote_from_comment_or_steal_next_gui_name(tmp_path):
    root=tmp_path/"src"/"client"
    root.mkdir(parents=True)
    (root/"Decor.client.luau").write_text(
        '-- game.Remotes.Fake:InvokeServer({})\\n'
        'local gui=Instance.new("ScreenGui")\\n'
        'gui.Name="Decorations"\\n')
    (root/"Two.client.luau").write_text(
        'local first=Instance.new("ScreenGui")\\n'
        'local second=Instance.new("ScreenGui")\\n'
        'second.Name="SecondaryActions"\\n'
        'game.Remotes.Real:InvokeServer({})\\n')
    assert action_gui_names(tmp_path)==["SecondaryActions"]
    assert not install_host_hud(tmp_path)


def test_action_screen_names_are_data_not_ascii_or_genre_assumptions(tmp_path):
    _client(tmp_path,"Korean","상점 화면")
    _client(tmp_path,"Fancy","My Craft Menu")
    assert action_gui_names(tmp_path)==["My Craft Menu","상점 화면"]
    assert install_host_hud(tmp_path)
    hud=(tmp_path/"src"/"client"/HUD_FILE).read_text()
    assert '"상점 화면"' in hud
    assert '"My Craft Menu"' in hud
