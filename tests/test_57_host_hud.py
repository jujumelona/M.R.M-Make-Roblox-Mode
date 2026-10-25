"""57: generated independent rank GUIs must have a packaged, playable HUD."""
from pathlib import Path
from roblox_mod_ai.host_hud import HUD_FILE, HUD_SOURCE, install_host_hud


def _client(root: Path, name: str, gui: str):
    client=root/"src"/"client"
    client.mkdir(parents=True,exist_ok=True)
    (client/(name+".client.luau")).write_text(
        '--!strict\nlocal gui=Instance.new("ScreenGui")\n'
        'gui.Name="'+gui+'"\n'
        'gui.Parent=game.Players.LocalPlayer.PlayerGui\n',
        encoding="utf-8")


def test_57_docks_duplicate_rank_buttons_without_changing_gameplay(tmp_path):
    _client(tmp_path,"Crew","RMMRankUpgrade")
    _client(tmp_path,"Weapon","RMMRankUpgrade")
    _client(tmp_path,"Ship","RMMShipAssembly")
    originals={p.name:p.read_bytes() for p in (tmp_path/"src"/"client").glob("*.luau")}
    assert install_host_hud(tmp_path)
    adapter=(tmp_path/"src"/"client"/HUD_FILE).read_text()
    assert adapter==HUD_SOURCE
    for token in (
        'playerGui.ChildAdded:Connect(register)',
        'for _,child in playerGui:GetChildren() do register(child) end',
        'candidate.ChildAdded:Connect(function(child)',
        'sections=setmetatable({},{__mode="k"})',
        'if child.Parent~=candidate then return end',
        'child.Parent=section.frame',
        'scroll.AutomaticCanvasSize=Enum.AutomaticSize.Y',
        'toggle.Activated:Connect(function()',
        'or candidate.Name=="RMMRankUpgrade"',
    ):
        assert token in adapter,token
    assert originals=={p.name:p.read_bytes() for p in (tmp_path/"src"/"client").glob("*.luau")
                       if p.name!=HUD_FILE}
    assert install_host_hud(tmp_path)


def test_57_no_ui_injection_into_non_rmm_or_single_button_games(tmp_path):
    _client(tmp_path,"Custom","SomeOtherGameGui")
    _client(tmp_path,"Onboard","RMMOnboarding")
    assert not install_host_hud(tmp_path)
    assert not (tmp_path/"src"/"client"/HUD_FILE).exists()
    _client(tmp_path,"Mining","RMMMiningPanel")
    assert not install_host_hud(tmp_path)
    _client(tmp_path,"Trading","RMMResourceMarket")
    assert install_host_hud(tmp_path)


def test_57_existing_different_hud_is_not_silently_overwritten(tmp_path):
    import pytest
    _client(tmp_path,"Mining","RMMMiningPanel")
    _client(tmp_path,"Trading","RMMResourceMarket")
    conflicting=tmp_path/"src"/"client"/HUD_FILE
    conflicting.write_text("--!strict\nerror('user authored')\n")
    with pytest.raises(ValueError,match="HUD source conflicts"):
        install_host_hud(tmp_path)
    assert "user authored" in conflicting.read_text()
