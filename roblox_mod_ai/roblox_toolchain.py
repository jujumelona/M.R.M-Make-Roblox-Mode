"""Direct execution and management connector for the official Roblox Open-Source Toolchain.

Supports:
- Rojo (rojo build, rojo serve)
- Wally (wally install)
- Selene (selene lint)
- StyLua (stylua format)
- RobloxStudio MCP bridge (npx robloxstudio-mcp)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolchainStatus:
    rojo_available: bool = False
    rojo_version: str = ""
    wally_available: bool = False
    wally_version: str = ""
    selene_available: bool = False
    selene_version: str = ""
    stylua_available: bool = False
    stylua_version: str = ""
    npx_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rojo": {"available": self.rojo_available, "version": self.rojo_version},
            "wally": {"available": self.wally_available, "version": self.wally_version},
            "selene": {"available": self.selene_available, "version": self.selene_version},
            "stylua": {"available": self.stylua_available, "version": self.stylua_version},
            "npx": {"available": self.npx_available},
        }


class RobloxToolchainManager:
    """Detects, connects, and executes official Roblox development binaries."""

    def __init__(self) -> None:
        self.rojo_path = shutil.which("rojo")
        self.wally_path = shutil.which("wally")
        self.selene_path = shutil.which("selene")
        self.stylua_path = shutil.which("stylua")
        self.npx_path = shutil.which("npx")

    def _get_version(self, cmd_path: str | None) -> str:
        if not cmd_path:
            return ""
        try:
            res = subprocess.run([cmd_path, "--version"], capture_output=True, text=True, timeout=3)
            return res.stdout.strip() or res.stderr.strip()
        except Exception:
            return "unknown"

    def get_status(self) -> ToolchainStatus:
        """Returns availability and versions of all Roblox open-source tools."""
        return ToolchainStatus(
            rojo_available=self.rojo_path is not None,
            rojo_version=self._get_version(self.rojo_path),
            wally_available=self.wally_path is not None,
            wally_version=self._get_version(self.wally_path),
            selene_available=self.selene_path is not None,
            selene_version=self._get_version(self.selene_path),
            stylua_available=self.stylua_path is not None,
            stylua_version=self._get_version(self.stylua_path),
            npx_available=self.npx_path is not None,
        )

    def check_tools(self) -> dict[str, bool]:
        """Returns tool availability dictionary for quick environment diagnostics."""
        status = self.get_status()
        return {
            "Rojo": status.rojo_available,
            "Wally": status.wally_available,
            "Selene": status.selene_available,
            "StyLua": status.stylua_available,
            "NPX (Studio Bridge)": status.npx_available,
        }

    def generate_rokit_manifest(self) -> str:
        """Generates standard rokit.toml for toolchain installation."""
        return """[tools]
rojo = "rojo-rbx/rojo@7.4.4"
wally = "UpliftGames/wally@0.3.2"
selene = "Kampfkarren/selene@0.27.1"
stylua = "JohnnyMorganz/StyLua@2.0.2"
"""

    def generate_aftman_manifest(self) -> str:
        """Generates standard aftman.toml for toolchain installation."""
        return """[tools]
rojo = "rojo-rbx/rojo@7.4.4"
wally = "UpliftGames/wally@0.3.2"
selene = "Kampfkarren/selene@0.27.1"
stylua = "JohnnyMorganz/StyLua@2.0.2"
"""

    def run_stylua(self, target_dir: str | Path) -> dict[str, Any]:
        """Runs StyLua formatter on all Luau code in target_dir."""
        path = str(Path(target_dir).resolve())
        if not self.stylua_path:
            return {"success": True, "executed": False, "message": "StyLua not in PATH, skipped"}
        try:
            res = subprocess.run([self.stylua_path, path], capture_output=True, text=True, timeout=15)
            return {
                "success": res.returncode == 0,
                "executed": True,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as exc:
            return {"success": False, "executed": True, "error": str(exc)}

    def run_selene(self, target_dir: str | Path) -> dict[str, Any]:
        """Runs Selene linter on all Luau code in target_dir."""
        path = str(Path(target_dir).resolve())
        if not self.selene_path:
            return {"success": True, "executed": False, "message": "Selene not in PATH, using built-in analyzer"}
        try:
            res = subprocess.run([self.selene_path, path], capture_output=True, text=True, timeout=15)
            return {
                "success": res.returncode == 0,
                "executed": True,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as exc:
            return {"success": False, "executed": True, "error": str(exc)}

    def run_wally_install(self, project_dir: str | Path) -> dict[str, Any]:
        """Executes 'wally install' in project_dir if wally.toml exists."""
        p_dir = Path(project_dir).resolve()
        wally_toml = p_dir / "wally.toml"
        if not wally_toml.is_file():
            return {"success": False, "error": "No wally.toml found"}

        if not self.wally_path:
            return {"success": True, "executed": False, "message": "Wally not in PATH, skipped package download"}

        try:
            res = subprocess.run([self.wally_path, "install"], cwd=str(p_dir), capture_output=True, text=True, timeout=30)
            return {
                "success": res.returncode == 0,
                "executed": True,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as exc:
            return {"success": False, "executed": True, "error": str(exc)}

    def run_rojo_build(self, project_json: str | Path, output_file: str | Path) -> dict[str, Any]:
        """Executes 'rojo build -o <output> <project_json>'."""
        p_json = str(Path(project_json).resolve())
        out_f = str(Path(output_file).resolve())
        if not self.rojo_path:
            return {"success": False, "executed": False, "message": "Rojo not in PATH, fallback to built-in XML builder"}

        try:
            res = subprocess.run([self.rojo_path, "build", "-o", out_f, p_json], capture_output=True, text=True, timeout=30)
            return {
                "success": res.returncode == 0 and os.path.isfile(out_f),
                "executed": True,
                "output_file": out_f,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as exc:
            return {"success": False, "executed": True, "error": str(exc)}
