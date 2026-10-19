"""Prepare an optional offline Studio CLI structural check for compiled RMM games.

No publishing, credentials, test Experience or fabricated runtime success.
Only checks Instances in a real, locally opened Roblox Studio edit session.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .spec import RobloxProposal


def make_studio_smoke(proposal: RobloxProposal, project: dict[str, Any]) -> str:
    tree = project["tree"]
    world = tree.get("Workspace", {})
    remotes = tree.get("ReplicatedStorage", {}).get("Remotes", {})
    lines = [
        "--!strict",
        "-- Checks Studio instance structure, NOT multiplayer or gameplay.",
        "local checked = 0",
        "local function checkChild(parent, name, className)",
        "    assert(parent ~= nil, 'Missing parent of ' .. name)",
        "    local child = parent:FindFirstChild(name)",
        "    assert(child ~= nil, 'Missing ' .. name .. ' under ' .. parent:GetFullName())",
        "    if className then",
        "        assert(child:IsA(className), 'Wrong Roblox class: ' .. name)",
        "    end",
        "    checked += 1",
        "    return child",
        "end",
    ]

    def add(parent: str, name: str, class_name: str):
        qname = json.dumps(str(name), ensure_ascii=False)
        qclass = json.dumps(str(class_name))
        lines.append(f"checkChild({parent}, {qname}, {qclass})")

    for module in proposal.modules:
        path = module.file_path
        if path.startswith("src/server/"):
            parent = 'game:GetService("ServerScriptService")'
            kind = "Script" if path.endswith(".server.luau") else "ModuleScript"
        elif path.startswith("src/client/"):
            parent = 'game:GetService("StarterPlayer"):FindFirstChild("StarterPlayerScripts")'
            kind = "LocalScript"
        elif path.startswith("src/shared/"):
            parent = 'game:GetService("ReplicatedStorage"):FindFirstChild("Shared")'
            kind = "ModuleScript"
        else:
            continue
        add(parent, module.name, kind)
    for name, entry in remotes.items():
        if str(name).startswith("$"):
            continue
        kind = entry.get("$className") if isinstance(entry, dict) else None
        if kind in ("RemoteEvent", "RemoteFunction"):
            add('game:GetService("ReplicatedStorage"):FindFirstChild("Remotes")', name, kind)
    for name, entry in world.items():
        if str(name).startswith("$"):
            continue
        kind = entry.get("$className") if isinstance(entry, dict) else None
        if isinstance(kind, str):
            add("workspace", name, kind)
    lines.append('print("RMM_STUDIO_SMOKE_PASS " .. tostring(checked) .. " checks")')
    return "\n".join(lines) + "\n"


_LOCAL_PS = r'''# Windows Roblox Studio CLI. No API key, account publishing or Place IDs.
param([string]$StudioPath = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$place = Join-Path $root "compiled_place.rbxlx"
$script = Join-Path $PSScriptRoot "structural_smoke.luau"
$log = Join-Path $PSScriptRoot "studio_smoke_output.log"
if (-not (Test-Path -LiteralPath $place -PathType Leaf)) {
    throw "Extract the full RMM project ZIP including compiled_place.rbxlx first."
}
if (-not $StudioPath) {
    $versions = Join-Path $env:LOCALAPPDATA "Roblox\Versions"
    $candidate = Get-ChildItem -LiteralPath $versions -Filter RobloxStudioBeta.exe -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $candidate) { throw "Roblox Studio is not installed. Pass -StudioPath if needed." }
    $StudioPath = $candidate.FullName
}
& $StudioPath --task RunScript --localPlaceFile $place --runScriptFile $script --outputFile $log --quitAfterExecution
if (-not (Test-Path -LiteralPath $log -PathType Leaf)) {
    throw "Studio did not produce an output log."
}
$record = Get-Content -LiteralPath $log -Raw
if ($record -notmatch "RMM_STUDIO_SMOKE_PASS") {
    throw "Studio structural smoke failed. Inspect $log"
}
Write-Host "Studio structure check passed (not a gameplay or multiplayer test)."
Write-Host $log
'''

_LOCAL_README = """# Local Roblox Studio checks - no API key

The project ZIP includes compiled_place.rbxlx. Extract the entire archive
onto the Windows PC with Roblox Studio installed.

- Double-click compiled_place.rbxlx to open it in Studio. Press Play to
  manually test gameplay, combat, shop UI, interactions and persistence.
- Optional local edit-mode structural smoke:
  powershell -ExecutionPolicy Bypass -File .\\local_studio\\run_smoke.ps1
  It runs the official Studio CLI against the local file and writes
  local_studio/studio_smoke_output.log. It does not publish anything.
- Optional agent-assisted interactive testing: Enable Studio as MCP server
  inside Roblox Studio Assistant > Manage MCP Servers. Connect your
  trusted LOCAL MCP client using studio_mcp.windows.json (example).
- Optional Rojo live sync: install the Rojo Studio plugin, run
  rojo serve in this folder, then connect Studio to the Rojo server.

Roblox CLI: https://create.roblox.com/docs/studio/command-line-interface
Studio MCP: https://create.roblox.com/docs/studio/mcp
Rojo: https://rojo.space

IMPORTANT: This structural smoke checks instance presence only. It does
not prove multiplayer, actual player input, purchases or DataStore restores.
Colab cannot directly control Studio running on another computer.
"""


def install_local_studio_checks(
    proposal: RobloxProposal, project_root: Path, compiled_place: Path
) -> dict[str, str]:
    """Add an isolated place and local verification kit to the output directory."""
    root, place = Path(project_root), Path(compiled_place)
    if not place.is_file() or place.stat().st_size == 0:
        raise FileNotFoundError("Cannot bundle an empty or missing compiled Place")
    project = json.loads((root / "default.project.json").read_text(encoding="utf-8"))
    bundled = root / "compiled_place.rbxlx"
    if place.resolve() != bundled.resolve():
        shutil.copyfile(place, bundled)
    folder = root / "local_studio"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "structural_smoke.luau").write_text(
        make_studio_smoke(proposal, project), encoding="utf-8"
    )
    (folder / "run_smoke.ps1").write_text(_LOCAL_PS, encoding="utf-8")
    (folder / "README.md").write_text(_LOCAL_README, encoding="utf-8")
    (folder / "studio_mcp.windows.json").write_text(
        json.dumps({"mcpServers": {"Roblox_Studio": {
            "command": "cmd.exe",
            "args": ["/c", r"%LOCALAPPDATA%\Roblox\mcp.bat"],
        }}}, indent=2), encoding="utf-8"
    )
    return {"compiled_place": str(bundled), "local_test_dir": str(folder)}
