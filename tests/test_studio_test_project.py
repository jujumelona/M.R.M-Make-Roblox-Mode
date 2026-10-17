from pathlib import Path
import json
from tools.build_studio_test_place import create_studio_project
from roblox_mod_ai.api import CompleteRobloxAISession


def test_studio_instrumentation_is_separate_from_release(tmp_path: Path):
    session = CompleteRobloxAISession(output_root=tmp_path)
    session.plan("코인 수집과 상점, 검투 아레나")
    result = session.build(source_only=True)
    root = Path(result.project_dir)
    original = (root / "default.project.json").read_bytes()
    output = create_studio_project(root, Path(__file__).resolve().parents[1])
    assert output.is_file()
    assert (root / "default.project.json").read_bytes() == original
    test_tree = json.loads(output.read_text(encoding="utf-8"))["tree"]
    assert "RMMStudioServer" in test_tree["ServerScriptService"]
    assert "RMMStudioClient" in test_tree["StarterPlayer"]["StarterPlayerScripts"]
    release = json.loads(original)["tree"]
    assert "RMMStudioServer" not in release["ServerScriptService"]
