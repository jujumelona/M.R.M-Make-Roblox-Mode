"""Direct execution and management connector for the official Roblox Open-Source Toolchain.

Supports:
- Rojo (rojo build, rojo serve)
- Wally (wally install)
- Selene (selene lint)
- StyLua (stylua format)
- Roblox Studio MCP is a built-in LOCAL Studio feature, not an npm bridge.
  Studio MCP is configured on the Windows machine in the bundled project kit.
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
    """Detects and executes installed Roblox development command-line tools.

    The built-in Roblox Studio MCP server cannot be considered connected merely
    because npx exists in Colab or the local shell.
    """

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

    @staticmethod
    def _authored_luau_files(target_dir: str | Path) -> list[Path]:
        """Only source owned by this generated game; never vendored dependencies.

        StyLua / luau-analyze called with the project directory previously
        descended into Wally's Packages/DevPackages/_Index, where third-party
        Luau versions and generated artifacts are outside MRM's control.
        """
        root = Path(target_dir).resolve()
        files: list[Path] = []
        for owned in ("src", "tests"):
            base = root / owned
            if not base.is_dir():
                continue
            for source in base.rglob("*"):
                if (source.is_file() and source.suffix in (".lua", ".luau")
                        and not source.is_symlink()
                        and not any(part in ("Packages", "DevPackages", "_Index",
                                             "node_modules", ".git")
                                    for part in source.relative_to(base).parts)):
                    files.append(source)
        return sorted(files)

    def run_stylua(self, target_dir: str | Path) -> dict[str, Any]:
        """Format only MRM-authored scripts, not installed Wally/Jest packages."""
        files = self._authored_luau_files(target_dir)
        if not files:
            return {"success": False, "executed": False,
                    "message": "No authored Lua/Luau sources in src/ or tests/"}
        if not self.stylua_path:
            return {"success": True, "executed": False,
                    "message": "StyLua not in PATH, skipped"}
        try:
            # Files are explicit operands, so third-party Packages/DevPackages
            # cannot cause parser failures or be rewritten by our formatter.
            res = subprocess.run([self.stylua_path, *(str(file) for file in files)],
                                 cwd=str(Path(target_dir).resolve()),
                                 capture_output=True, text=True, timeout=60)
            return {
                "success": res.returncode == 0,
                "executed": True,
                "checked_authored_files": len(files),
                "scope": "src/ and tests/ only",
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
        except Exception as exc:
            return {"success": False, "executed": True,
                    "checked_authored_files": len(files), "error": str(exc)}

    def run_selene(self, target_dir: str | Path) -> dict[str, Any]:
        """Runs Selene linter on all Luau code in target_dir."""
        path = str(Path(target_dir).resolve())
        if not self.selene_path:
            return {"success": False, "executed": False, "message": "Selene not in PATH"}
        try:
            res = subprocess.run([self.selene_path, "src"], cwd=path, capture_output=True, text=True, timeout=45)
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

    def run_luau_analyze(self, target_dir: str | Path) -> dict[str, Any]:
        """Analyze MRM-owned production Luau, not Wally/Jest dependencies."""
        tool = shutil.which("luau-analyze")
        if not tool:
            return {"success": False, "executed": False, "message": "luau-analyze missing"}
        paths = [str(p) for p in self._authored_luau_files(target_dir)
                 if "src" in p.relative_to(Path(target_dir).resolve()).parts]
        if not paths:
            return {"success": False, "executed": False, "message": "no authored source scripts"}
        try:
            res = subprocess.run([tool, *paths], capture_output=True, text=True, timeout=60)
            return {"success": res.returncode == 0, "executed": True,
                    "checked_authored_files": len(paths),
                    "scope": "src/ only", "stdout": res.stdout, "stderr": res.stderr}
        except Exception as exc:
            return {"success": False, "executed": True,
                    "checked_authored_files": len(paths), "error": str(exc)}

    @staticmethod
    def stage_lune_economy_test(project_dir: str | Path) -> Path | None:
        """Create an executable *pure Luau* test only for games with economy rules.

        This test does not start Roblox Studio or validate in-game remotes.
        It tests the actual EconomyRules.luau shipped in this project.
        """
        root = Path(project_dir).resolve()
        rules = root / "src" / "shared" / "EconomyRules.luau"
        if not rules.is_file():
            return None
        path = root / "tests" / "economy_contract.luau"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("""--!strict
-- Executable offline contract for the SAME rules shipped with this Place.
local Rules = require("../src/shared/EconomyRules")
assert(Rules.canAfford(50, 50) == true)
assert(Rules.canAfford(49, 50) == false)
assert(Rules.canAfford(-10, 5) == false)
assert(Rules.canAfford(100, -25) == false)
assert(Rules.canAfford(1, 0) == false)
assert(Rules.canAfford(100, math.huge) == false)
assert(Rules.canAfford(100, 0 / 0) == false)
assert(Rules.canAfford(10.5, 5) == false)
assert(Rules.charge(75, 50) == 25)
assert(Rules.charge(0, 50) == nil)
print("RMM_LUNE_ECONOMY_PASS")
""", encoding="utf-8")
        return path

    def run_lune_economy_test(self, project_dir: str | Path) -> dict[str, Any]:
        """Execute only a safe engine-independent unit suite if Lune exists."""
        root = Path(project_dir).resolve()
        case = root / "tests" / "economy_contract.luau"
        if not case.is_file():
            return {"success": False, "executed": False, "status": "not_applicable",
                    "reason": "No generated offline EconomyRules test for this game"}
        binary = shutil.which("lune")
        if not binary:
            return {"success": False, "executed": False, "status": "not_run",
                    "reason": "Lune is not installed; pure Luau test skipped"}
        try:
            result = subprocess.run([binary, "run", str(case)], cwd=str(root),
                                    capture_output=True, text=True, timeout=45)
            passed = result.returncode == 0 and "RMM_LUNE_ECONOMY_PASS" in result.stdout
            return {"success": passed, "executed": True,
                    "status": "passed" if passed else "failed",
                    "scope": "generated EconomyRules only; no Roblox engine",
                    "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "executed": True, "status": "failed",
                    "error": str(exc)}

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
