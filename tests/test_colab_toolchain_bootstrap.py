"""Offline bootstrap checks for pinned official tool downloads and cell ownership."""
from __future__ import annotations

import json
from pathlib import Path
import stat
import zipfile

import pytest

from roblox_mod_ai import colab_toolchain_bootstrap as setup
from tools import generate_colab_notebook


@pytest.mark.parametrize("name,asset", [
    ("rojo", "rojo-7.4.4-linux-x86_64.zip"),
    ("wally", "wally-v0.3.2-linux.zip"),
    ("selene", "selene-0.27.1-linux.zip"),
    ("stylua", "stylua-linux-x86_64.zip"),
])
def test_official_pinned_asset_names(name, asset):
    owner, tag, actual = setup.RELEASES[name]
    assert owner and tag and actual == asset
    assert name in ("rojo", "wally", "selene", "stylua")


def test_single_binary_extracted_and_given_execute_permissions(tmp_path):
    archive = tmp_path / "rojo.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("docs/README.md", "do not extract this")
        out.writestr("artifact/bin/rojo", "#!/bin/sh\necho rojo 7.4.4\n")
    dest = tmp_path / "rojo"
    setup._extract_executable(archive, "rojo", dest)
    assert dest.is_file()
    # Windows filesystems do not expose POSIX execute permission bits.
    if setup.os.name == "posix":
        assert dest.stat().st_mode & stat.S_IXUSR
    assert not (tmp_path / "artifact").exists()
    assert not (tmp_path / "docs").exists()


def test_duplicate_binary_and_symlink_payload_are_rejected(tmp_path):
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as out:
        out.writestr("one/rojo", "1")
        out.writestr("two/rojo", "2")
    with pytest.raises(setup.ToolchainInstallError, match="exactly one"):
        setup._extract_executable(duplicate, "rojo", tmp_path / "rojo")
    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as out:
        info = zipfile.ZipInfo("rojo")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        out.writestr(info, "../../escape")
    with pytest.raises(setup.ToolchainInstallError, match="exactly one"):
        setup._extract_executable(symlink, "rojo", tmp_path / "rojo")


def test_four_tools_installed_and_visible_to_path(monkeypatch, tmp_path):
    # This fixture mocks the four mandatory assets only. Optional tools use
    # their own release tests and may be unavailable without blocking a build.
    monkeypatch.setenv("RMM_INSTALL_OPTIONAL_TOOLS", "0")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup.platform, "machine", lambda: "x86_64")
    requested = []

    def fake_download(url, target):
        requested.append(url)
        binary = next(k for k in setup.RELEASES if target.name == setup.RELEASES[k][2])
        with zipfile.ZipFile(target, "w") as file:
            file.writestr(binary, f"#!mock {binary}".encode())

    monkeypatch.setattr(setup, "_download", fake_download)
    monkeypatch.setattr(setup, "_command_version", lambda p:
                        setup.RELEASES[p.name][1].lstrip("v"))
    monkeypatch.setattr(
        setup.RobloxToolchainManager, "check_tools",
        lambda self: dict.fromkeys(["Rojo", "Wally", "Selene", "StyLua"], True)
    )
    bin_dir = tmp_path / "bin"
    installed = setup.setup_colab_toolchain(bin_dir)
    assert sorted(installed) == sorted(setup.RELEASES)
    assert len(requested) == 4
    assert all(x.startswith("https://github.com/") and "/releases/download/" in x
               for x in requested)
    assert setup.os.environ["PATH"].split(setup.os.pathsep)[0] == str(bin_dir)
    assert all((bin_dir / name).is_file() for name in setup.RELEASES)
    setup.setup_colab_toolchain(bin_dir)
    assert len(requested) == 4  # reuse; no redownload


def test_generator_and_committed_notebook_agree_about_cells(tmp_path, monkeypatch):
    generated = tmp_path / "generated.ipynb"
    monkeypatch.setattr(generate_colab_notebook, "NOTEBOOK_PATH", generated)
    generate_colab_notebook.build_notebook()
    actual = json.loads(
        (Path(__file__).resolve().parents[1] /
         "R.M.M_Make_Roblox_Mode_Colab.ipynb").read_text(encoding="utf-8"))
    expected = json.loads(generated.read_text(encoding="utf-8"))
    for index in (1, 2, 4, 6, 7):
        a = "".join(actual["cells"][index]["source"])
        b = "".join(expected["cells"][index]["source"])
        assert a == b, f"Committed Colab cell {index} diverged from generator"
        if index == 1:
            assert 'ENGINE_VERIFICATION_POLICY = "Auto"' in a
            assert "CLOUD_ENGINE_READY" in a
            assert "ENGINE_VERIFY_BEFORE_FINAL = " in a
        elif index == 2:
            assert a.index("setup_colab_toolchain(") < a.index("ensure_model_runtime(")
        elif index == 4:
            assert "ensure_model_runtime(" not in a
            assert "setup_colab_toolchain(" not in a
        elif index == 6:
            assert "PLAN_FAILURE_LOGS_ZIP = session.export_plan_failure()" in a
            assert "failure_logs_zip" in a
        elif index == 7:
            assert "DOWNLOAD_TARGETS.append(Path(failure_path))" in a


def test_optional_official_lune_and_luau_release_assets_are_pinned():
    assert setup.OPTIONAL_RELEASES["lune"] == (
        "lune-org/lune", "v0.11.0", "lune-0.11.0-linux-x86_64.zip")
    assert setup.OPTIONAL_RELEASES["luau-compile"] == (
        "luau-lang/luau", "0.743", "luau-ubuntu.zip")


def test_optional_download_failure_does_not_break_mandatory_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("RMM_INSTALL_OPTIONAL_TOOLS", "1")
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup.platform, "machine", lambda: "x86_64")
    def download(url, target):
        for name, (_, _, filename) in setup.RELEASES.items():
            if target.name == filename:
                with zipfile.ZipFile(target, "w") as archive:
                    archive.writestr(name, "binary-placeholder")
                return
        raise setup.ToolchainInstallError("optional GitHub unavailable")
    monkeypatch.setattr(setup, "_download", download)
    monkeypatch.setattr(setup, "_command_version", lambda p:
                        setup.RELEASES[p.name][1].removeprefix("v"))
    monkeypatch.setattr(
        setup.RobloxToolchainManager, "check_tools",
        lambda self: dict.fromkeys(["Rojo", "Wally", "Selene", "StyLua"], True)
    )
    installed = setup.setup_colab_toolchain(tmp_path / "bin")
    assert set(installed) == set(setup.RELEASES)
    assert all(not (tmp_path / "bin" / name).exists()
               for name in setup.OPTIONAL_RELEASES)
