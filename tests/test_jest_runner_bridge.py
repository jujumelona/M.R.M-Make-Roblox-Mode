from pathlib import Path
import json
from tools.build_studio_test_place import create_studio_project
from roblox_mod_ai.api import CompleteRobloxAISession

def test_jest_runs_only_in_real_studio_test_place(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 수집 상점 아레나")
    result = session.build(source_only=True)
    place_dir = Path(result.project_dir)
    test_project = create_studio_project(place_dir, Path(__file__).resolve().parents[1])
    test_tree = json.loads(test_project.read_text(encoding="utf-8"))["tree"]
    assert "RMMJestRunner" in test_tree["ServerScriptService"]
    assert "RMMJestRunner" not in json.loads(
        (place_dir / "default.project.json").read_text(encoding="utf-8")
    )["tree"]["ServerScriptService"]
    script = (Path(__file__).resolve().parents[1] / "studio_tests/RMMJestRunner.server.luau").read_text(encoding="utf-8")
    assert "Jest.runCLI" in script
    assert 'RMM_JEST_STATUS' in script

def test_studio_result_requires_jest_pass():
    source = (Path(__file__).resolve().parents[1] / "studio_tests/RMMStudioServer.server.luau").read_text(encoding="utf-8")
    assert 'GetAttribute("RMM_JEST_STATUS") ~= "PASSED"' in source
