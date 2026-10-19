"""Credential-free Roblox game production and local Studio handoff tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from roblox_mod_ai.local_studio import install_local_studio_checks, make_studio_smoke


def _fixture():
    modules = [
        SimpleNamespace(name="PlayerDataManager", file_path="src/server/PlayerDataManager.server.luau"),
        SimpleNamespace(name="ShopService", file_path="src/server/ShopService.server.luau"),
        SimpleNamespace(name="ShopController", file_path="src/client/ShopController.client.luau"),
        SimpleNamespace(name="NetworkRemotes", file_path="src/shared/NetworkRemotes.luau"),
    ]
    project = {
        "tree": {
            "Workspace": {
                "$className": "Workspace",
                "Coins": {"$className": "Folder"},
                "ShopStalls": {"$className": "Folder"},
                "CombatArena": {"$className": "Model"},
            },
            "ReplicatedStorage": {
                "Remotes": {
                    "$className": "Folder",
                    "ShopPurchase": {"$className": "RemoteFunction"},
                    "AttackRequest": {"$className": "RemoteEvent"},
                }
            },
        }
    }
    return SimpleNamespace(modules=modules), project


def test_local_smoke_checks_real_module_roles_world_and_remote_types():
    proposal, project = _fixture()
    code = make_studio_smoke(proposal, project)
    assert 'checkChild(game:GetService("ServerScriptService"), "ShopService", "Script")' in code
    assert 'checkChild(game:GetService("StarterPlayer"):WaitForChild("StarterPlayerScripts"), "ShopController", "LocalScript")' in code
    assert 'checkChild(game:GetService("ReplicatedStorage"):WaitForChild("Shared"), "NetworkRemotes", "ModuleScript")' in code
    assert '"ShopPurchase", "RemoteFunction"' in code
    assert '"AttackRequest", "RemoteEvent"' in code
    assert '"CombatArena", "Model"' in code
    assert "RMM_STUDIO_SMOKE_PASS" in code
    assert "DataStore:SetAsync" not in code


def test_offline_local_studio_bundle_includes_compiled_place_and_mcp_config(tmp_path):
    proposal, project = _fixture()
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")
    place = tmp_path / "built-place.rbxlx"
    content = b'<?xml version="1.0"?><roblox/>'
    place.write_bytes(content)
    kit = install_local_studio_checks(proposal, tmp_path, place)
    bundled = tmp_path / "compiled_place.rbxlx"
    assert bundled.read_bytes() == content
    assert kit["compiled_place"] == str(bundled)
    folder = tmp_path / "local_studio"
    assert (folder / "structural_smoke.luau").is_file()
    command = (folder / "run_smoke.ps1").read_text(encoding="utf-8")
    assert "--task RunScript" in command
    assert "--localPlaceFile" in command
    assert "--quitAfterExecution" in command
    assert "RMM_STUDIO_SMOKE_PASS" in command
    assert "publish_place" not in command
    config = json.loads((folder / "studio_mcp.windows.json").read_text(encoding="utf-8"))
    assert config["mcpServers"]["Roblox_Studio"]["args"][1].endswith(r"\Roblox\mcp.bat")
    assert (folder / "README.md").is_file()
    assert hashlib.sha256(bundled.read_bytes()).hexdigest() == hashlib.sha256(content).hexdigest()


def test_distribution_zip_contains_an_openable_place_and_local_studio_tools(tmp_path):
    from roblox_mod_ai.project_generator import RobloxProjectGenerator

    proposal, project = _fixture()
    (tmp_path / "default.project.json").write_text(json.dumps(project), encoding="utf-8")
    place = tmp_path.parent / "demo-place.rbxlx"
    place.write_bytes(b"real studio place bytes")
    install_local_studio_checks(proposal, tmp_path, place)
    out = tmp_path.parent / "project.zip"
    RobloxProjectGenerator(tmp_path).pack_project_zip(tmp_path, out)
    with ZipFile(out) as archive:
        names = set(archive.namelist())
        assert "compiled_place.rbxlx" in names
        assert "local_studio/run_smoke.ps1" in names
        assert "local_studio/structural_smoke.luau" in names
        assert archive.read("compiled_place.rbxlx") == b"real studio place bytes"
