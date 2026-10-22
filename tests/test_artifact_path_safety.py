"""Reject AI-owned paths that would write outside the project or override tests."""
from types import SimpleNamespace

import pytest

from roblox_mod_ai.artifact_path_safety import safe_project_file, safe_segment
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, ModuleKind, RobloxService


@pytest.mark.parametrize("unsafe", [
    "..", ".", "../host", "host/name", "C:\\temp", "/tmp/escape", "",
])
def test_game_title_cannot_be_used_as_parent_path(unsafe):
    with pytest.raises(ValueError, match="INVALID_ARTIFACT_SEGMENT"):
        safe_segment(unsafe, field="game_title")


@pytest.mark.parametrize("unsafe", [
    "../../unrelated.py", "src/../../outside.luau",
    "/tmp/owned.luau", "src/server/../other.luau",
    "src\\server\\file.luau", "tests/user.py",
    "C:\\Windows\\thing.luau", "src//server/File.luau",
])
def test_module_source_path_must_remain_canonical_and_owned(tmp_path, unsafe):
    with pytest.raises(ValueError, match="RMM_"):
        safe_project_file(tmp_path, unsafe, prefixes=("src",))


def test_valid_source_and_test_paths_remain_writable(tmp_path):
    assert safe_project_file(tmp_path, "src/server/GameServer.luau",
                             prefixes=("src",)) == tmp_path / "src/server/GameServer.luau"
    assert safe_project_file(tmp_path, "tests/Game.spec.luau",
                             prefixes=("tests",)) == tmp_path / "tests/Game.spec.luau"


def test_materialization_rejects_path_escape_before_luau_write(tmp_path):
    module = RobloxModuleSpec(
        module_id="dyn_bad",
        name="BadServer",
        kind=ModuleKind.SERVER_MODULE,
        file_path="src/../../../hijack.luau",
        roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        code="--!strict\nreturn {}\n",
    )
    proposal = RobloxProposal(
        requested_prompt="Create a world", game_title="Game",
        description="test", game_design={}, modules=[module],
    )
    with pytest.raises(ValueError, match="RMM_PROJECT_PATH_OUTSIDE_OWNERSHIP"):
        RobloxProjectGenerator(tmp_path).materialize_project_tree(
            proposal, tmp_path / "game")
    assert not (tmp_path / "hijack.luau").exists()
