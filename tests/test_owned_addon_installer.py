import json
from pathlib import Path
import pytest

from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.addon_installer import prepare_owned_addon, apply_owned_addon


def make_base(root: Path) -> Path:
    base=root/"owner_place"
    base.mkdir()
    tree={
        "$className":"DataModel",
        "ServerScriptService":{"$className":"ServerScriptService","$path":"src/server"},
        "StarterPlayer":{"$className":"StarterPlayer",
            "StarterPlayerScripts":{"$className":"StarterPlayerScripts","$path":"src/client"}},
        "ReplicatedStorage":{"$className":"ReplicatedStorage",
            "Shared":{"$path":"src/shared"},
            "Remotes":{"$className":"Folder"}},
        "StarterGui":{"$className":"StarterGui","$path":"src/gui"},
        "Workspace":{"$className":"Workspace",
            "OriginalCastle":{"$className":"Model"},"SpawnLocation":{"$className":"SpawnLocation"}},
    }
    (base/"default.project.json").write_text(json.dumps({"name":"Owned","tree":tree}),encoding="utf-8")
    (base/"src/server").mkdir(parents=True)
    (base/"src/server/OriginalGame.server.luau").write_text("print('original')")
    return base


def make_addon(root: Path) -> Path:
    session=CompleteRobloxAISession(output_root=root/"staging")
    session.plan("코인 수집 상점",project_mode="existing_experience_addon")
    build=session.build(source_only=True)
    assert build.metadata["addon_prepared"],build.metadata
    return Path(build.project_dir)


def test_preflight_does_not_mutate_base(tmp_path: Path):
    addon=make_addon(tmp_path)
    base=make_base(tmp_path)
    original=(base/"default.project.json").read_bytes()
    plan=prepare_owned_addon(addon,base)
    assert plan["passed"],plan
    assert not plan["owner_permission_verified"]
    assert plan["has_new_player_data"]
    assert (base/"default.project.json").read_bytes()==original
    assert not (base/"src/server/CoinCollector.server.luau").exists()


def test_explicit_owned_apply_preserves_preexisting_game(tmp_path:Path):
    addon=make_addon(tmp_path)
    base=make_base(tmp_path)
    with pytest.raises(PermissionError):
        apply_owned_addon(addon,base)
    with pytest.raises(PermissionError):
        apply_owned_addon(addon,base,i_own_this_experience=True)
    result=apply_owned_addon(addon,base,i_own_this_experience=True,
                             reviewed_player_data=True)
    assert result["local_files_applied"]>=3
    assert not result["published"]
    assert (base/"src/server/OriginalGame.server.luau").read_text()=="print('original')"
    data=json.loads((base/"default.project.json").read_text(encoding="utf-8"))
    assert "OriginalCastle" in data["tree"]["Workspace"]
    assert "SpawnLocation" in data["tree"]["Workspace"]
    assert "Coins" in data["tree"]["Workspace"]
    assert "ShopStalls" in data["tree"]["Workspace"]
    assert "Baseplate" not in data["tree"]["Workspace"]
    assert not prepare_owned_addon(addon,base)["passed"]


def test_colliding_rojo_files_and_world_rejected(tmp_path:Path):
    addon=make_addon(tmp_path)
    base=make_base(tmp_path)
    (base/"src/server/ShopService.server.luau").write_text("original")
    plan=prepare_owned_addon(addon,base)
    assert not plan["passed"]
    with pytest.raises(ValueError):
        apply_owned_addon(addon,base,i_own_this_experience=True,reviewed_player_data=True)


def test_tampered_addon_rejected(tmp_path:Path):
    addon=make_addon(tmp_path)
    base=make_base(tmp_path)
    (addon/"src/server/ShopService.server.luau").write_text("unsafe")
    with pytest.raises(ValueError):
        prepare_owned_addon(addon,base)
