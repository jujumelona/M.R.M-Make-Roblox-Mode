from pathlib import Path
from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.project_generator import RobloxProjectGenerator

def test_profilestore_real_wally_mapping_and_api(tmp_path: Path):
    proposal=RobloxGameDesignPlanner().plan("코인 상점과 리더보드 ProfileStore Fusion").proposal
    gen=LuauCodeGenerator()
    scripts=gen.generate_all_modules(proposal)
    assert proposal.game_design["storage_backend"]=="profilestore"
    assert proposal.game_design["ui_backend"]=="fusion"
    byname={m.name:m.code for m in scripts}
    assert 'StartSessionAsync' in byname["PlayerDataManager"]
    assert 'ProfileStore.New' in byname["PlayerDataManager"]
    assert 'scope:Computed' in byname["HUDController"]
    project=RobloxProjectGenerator(tmp_path)
    data=project.generate_rojo_project_json(proposal)["tree"]
    assert "ServerPackages" in data["ServerScriptService"]
    assert "Packages" in data["ReplicatedStorage"]
    wally=project.generate_wally_toml(proposal)
    assert '[server-dependencies]' in wally
    assert 'ProfileStore = "lm-loleris/profilestore@1.0.3"' in wally
    assert 'Fusion = "elttob/fusion@0.3.0"' in wally

def test_default_existing_backend_preserved(tmp_path: Path):
    proposal=RobloxGameDesignPlanner().plan("코인 상점").proposal
    assert proposal.game_design["storage_backend"] == "builtin"
    assert proposal.game_design["ui_backend"] == "builtin"
    s=RobloxProjectGenerator(tmp_path).generate_wally_toml(proposal)
    assert 'ProfileStore = ' not in s
    assert 'Fusion = ' not in s
