"""Reproducible Roblox command-line tool setup for Linux Colab.

Download pinned official GitHub release archives as data, extract only the
expected executable, and expose it to the current notebook via PATH.
No install shell scripts, unpinned cargo installs, or silent skipping.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from .roblox_toolchain import RobloxToolchainManager

# Official release filenames confirmed against GitHub Releases for these tags.
RELEASES = {
    "rojo": ("rojo-rbx/rojo", "v7.4.4", "rojo-7.4.4-linux-x86_64.zip"),
    "wally": ("UpliftGames/wally", "v0.3.2", "wally-v0.3.2-linux.zip"),
    "selene": ("Kampfkarren/selene", "0.27.1", "selene-0.27.1-linux.zip"),
    "stylua": ("JohnnyMorganz/StyLua", "v2.0.2", "stylua-linux-x86_64.zip"),
}
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


class ToolchainInstallError(RuntimeError):
    pass


def _log(message: str) -> None:
    print("[RMM setup] " + message, flush=True)


def _download(url: str, target: Path) -> None:
    """Bounded download with periodically flushed progress in notebook output."""
    request = urllib.request.Request(url, headers={
        "User-Agent": "RMM-Colab-Toolchain/1.0",
        "Accept": "application/octet-stream",
    })
    received = 0
    last_message = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=75) as response, target.open("wb") as output:
            length_raw = response.headers.get("Content-Length", "")
            expected = int(length_raw) if length_raw.isdigit() else None
            if expected is not None and expected > _MAX_ARCHIVE_BYTES:
                raise ToolchainInstallError("Oversized toolchain archive: " + url)
            while True:
                block = response.read(1024 * 512)
                if not block:
                    break
                received += len(block)
                if received > _MAX_ARCHIVE_BYTES:
                    raise ToolchainInstallError("Toolchain archive exceeds safety limit: " + url)
                output.write(block)
                if time.monotonic() - last_message >= 5:
                    suffix = f"/{expected / 1048576:.1f} MiB" if expected else ""
                    _log(f"download: {target.name}: {received / 1048576:.1f} MiB{suffix}")
                    last_message = time.monotonic()
    except (OSError, urllib.error.URLError) as exc:
        raise ToolchainInstallError("Download failed from official release: " + url +
                                    " (" + str(exc) + ")") from exc
    if received < 1000:
        raise ToolchainInstallError("Toolchain archive is empty or too small: " + url)
    _log(f"downloaded {target.name}: {received / 1048576:.1f} MiB")


def _extract_executable(archive: Path, name: str, target: Path) -> None:
    """Do not extract archive paths, symlinks or unrelated files."""
    with zipfile.ZipFile(archive) as file:
        candidates = [
            item for item in file.infolist()
            if not item.is_dir() and Path(item.filename).name == name
            and not (item.external_attr >> 16) & stat.S_IFMT(0o170000) == stat.S_IFLNK
        ]
        if len(candidates) != 1:
            raise ToolchainInstallError(
                f"Expected exactly one '{name}' binary in {archive.name}; found {len(candidates)}"
            )
        info = candidates[0]
        if info.file_size > _MAX_ARCHIVE_BYTES:
            raise ToolchainInstallError("Oversized binary in " + archive.name)
        temporary = target.with_suffix(".partial")
        with file.open(info) as src, temporary.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        temporary.chmod(0o755)
        os.replace(temporary, target)


def _command_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "--version"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolchainInstallError(f"{path.name} binary cannot start: {exc}") from exc
    message = (result.stdout or result.stderr).strip()
    if result.returncode != 0 and not message:
        raise ToolchainInstallError(f"{path.name} --version exited {result.returncode}")
    return message.splitlines()[0][:180] or "version output unavailable"


def setup_colab_toolchain(install_dir: str | Path = "/content/rmm-tools/bin",
                          *, in_colab: bool = True) -> dict[str, str]:
    """Install four pinned CLI tools once; report exactly what is installed."""
    if not in_colab:
        return {name: shutil.which(name) or "" for name in RELEASES}
    if platform.system() != "Linux" or platform.machine().lower() not in (
            "x86_64", "amd64"):
        raise ToolchainInstallError(
            "Colab installer requires Linux x86_64; no unsupported binary guesses."
        )
    bin_dir = Path(install_dir).expanduser().resolve()
    bin_dir.mkdir(parents=True, exist_ok=True)
    # Update PATH before querying the manager (it snapshots locations).
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    installed = {}
    with tempfile.TemporaryDirectory(prefix="rmm-tools-") as scratch:
        for name, (repository, tag, filename) in RELEASES.items():
            destination = bin_dir / name
            if not destination.is_file():
                url = f"https://github.com/{repository}/releases/download/{tag}/{filename}"
                _log(f"installing {name} ({tag}) from verified upstream release")
                downloaded = Path(scratch) / filename
                _download(url, downloaded)
                _extract_executable(downloaded, name, destination)
            else:
                _log(f"reusing installed {name}")
            version = _command_version(destination)
            installed[name] = str(destination)
            _log(f"{name}: {version}")
    checks = RobloxToolchainManager().check_tools()
    missing = [name for name in ("Rojo", "Wally", "Selene", "StyLua")
               if not checks.get(name, False)]
    if missing:
        raise ToolchainInstallError("Toolchain verification failed: " + ", ".join(missing))
    _log("4/4 required command-line tools available; Studio bridge is not needed in Colab")
    return installed
