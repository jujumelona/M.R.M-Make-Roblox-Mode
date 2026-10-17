from pathlib import Path
from roblox_mod_ai.planner import RobloxGameDesignPlanner
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.api import CompleteRobloxAISession
from tools.build_studio_test_place import create_studio_project
import json

def test_new_default_jest_is_real_registered_dependency(tmp_path):
    proposal=RobloxGameDesignPlanner().plan("코인 수집 상점 아레나").proposal
    wally=RobloxProjectGenerator(tmp_path).generate_wally_toml(proposal)
    assert 'Jest = "roblox/jest@=3.20.0"' in wally
    assert 'JestGlobals = "roblox/jest-globals@=3.20.0"' in wally
    assert proposal.tests
    assert all("JestGlobals" in t.test_code for t in proposal.tests)
    assert all(".toBe(true)" in t.test_code for t in proposal.tests)

def test_jest_mapped_only_in_test_place(tmp_path):
    session=CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 수집 상점")
    result=session.build(source_only=True)
    root=Path(result.project_dir)
    compiled=create_studio_project(root,Path(__file__).resolve().parents[1])
    testtree=json.loads(compiled.read_text())["tree"]["ReplicatedStorage"]
    released=json.loads((root/"default.project.json").read_text())["tree"]["ReplicatedStorage"]
    assert "DevPackages" in testtree and "TestSuites" in testtree
    assert "DevPackages" not in released and "TestSuites" not in released
