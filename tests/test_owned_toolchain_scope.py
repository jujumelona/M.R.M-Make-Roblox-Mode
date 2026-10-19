"""Regression for Wally/Jest parser errors outside MRM-owned game source.

A real production failure previously called StyLua on the entire project,
including DevPackages/_Index/roblox_jest-core/.../TestScheduler.lua and
crashed on third-party >> generic syntax before Rojo packaging.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from roblox_mod_ai.roblox_toolchain import RobloxToolchainManager


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "generated"
    owned = root / "src/server/CombatSystem.server.luau"
    test = root / "tests/Combat.spec.luau"
    bad = root / "DevPackages/_Index/roblox_jest-core@3.20.1/jest-core/src/TestScheduler.lua"
    package = root / "Packages/_Index/some_package/src/init.luau"
    for path in (owned, test, bad, package):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("type Broken = Map<string, Array<number>>\n"
                        if path in (bad, package) else "return {}\n",
                        encoding="utf-8")
    return root, owned


def test_stylua_never_reads_vendored_jest_or_wally_source(tmp_path):
    root, owned = _fixture(tmp_path)
    manager = RobloxToolchainManager()
    manager.stylua_path = "stylua"
    with patch("roblox_mod_ai.roblox_toolchain.subprocess.run",
               return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run:
        result = manager.run_stylua(root)
    assert result["success"] is True
    assert result["checked_authored_files"] == 2
    argv = run.call_args.args[0]
    assert argv[0] == "stylua"
    assert str(owned) in argv
    assert any(x.endswith("Combat.spec.luau") for x in argv)
    assert all("Packages" not in x and "TestScheduler" not in x
               for x in argv[1:])
    assert run.call_args.kwargs["cwd"] == str(root)


def test_stylua_fails_on_actual_author_source_error(tmp_path):
    root, _ = _fixture(tmp_path)
    manager = RobloxToolchainManager()
    manager.stylua_path = "stylua"
    with patch("roblox_mod_ai.roblox_toolchain.subprocess.run",
               return_value=SimpleNamespace(returncode=1, stdout="", stderr="authored Lua error")):
        result = manager.run_stylua(root)
    assert result["executed"] and not result["success"]
    assert "authored Lua error" in result["stderr"]


def test_luau_analyzer_never_receives_external_package_files(tmp_path):
    root, owned = _fixture(tmp_path)
    manager = RobloxToolchainManager()
    with patch("roblox_mod_ai.roblox_toolchain.shutil.which", return_value="luau-analyze"), patch(
        "roblox_mod_ai.roblox_toolchain.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="", stderr="")
    ) as run:
        result = manager.run_luau_analyze(root)
    assert result["success"] and result["checked_authored_files"] == 1
    assert run.call_args.args[0] == ["luau-analyze", str(owned)]


def test_no_user_sources_reports_missing_instead_of_scanning_dependencies(tmp_path):
    root = tmp_path / "only-vendor"
    third_party = root / "DevPackages/_Index/a/thing.lua"
    third_party.parent.mkdir(parents=True)
    third_party.write_text("return {}", encoding="utf-8")
    manager = RobloxToolchainManager()
    manager.stylua_path = "stylua"
    with patch("roblox_mod_ai.roblox_toolchain.subprocess.run") as run:
        result = manager.run_stylua(root)
    assert not result["success"] and not result["executed"]
    assert "No authored" in result["message"]
    run.assert_not_called()
