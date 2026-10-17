"""Roblox Experience vs additive-owned-experience extension contracts.

A Roblox "mod" is NOT an unauthorized patch to someone else's live game.
Add-on artifacts are staged sources, not a published or verified Roblox place.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

NEW_EXPERIENCE = "new_experience"
EXISTING_ADDON = "existing_experience_addon"
SUPPORTED_MODES = frozenset({NEW_EXPERIENCE, EXISTING_ADDON})


def validate_mode(mode: str) -> str:
    if mode not in SUPPORTED_MODES:
        raise ValueError("Unsupported Roblox project mode: " + str(mode))
    return mode


def addon_manifest(proposal, project_generator) -> dict:
    """No baseplate/spawn and no replacement of an existing game/Place."""
    if proposal.game_design.get("project_mode") != EXISTING_ADDON:
        raise ValueError("Addon manifest requires existing_experience_addon mode")
    root = project_generator.generate_rojo_project_json(proposal)["tree"]
    world = root["Workspace"]
    overlay = {
        key: value for key, value in world.items()
        if key not in ("$className", "$properties", "Baseplate", "SpawnLocation")
    }
    remotes = {
        key: value for key, value in root["ReplicatedStorage"]["Remotes"].items()
        if not key.startswith("$")
    }
    return {
        "schema": "rmm/owned-experience-addon-v1",
        "project_mode": EXISTING_ADDON,
        "ownership_required": True,
        "auto_publish": False,
        "standalone_place": False,
        "source_modules": [module.file_path for module in proposal.modules],
        "workspace_additions": overlay,
        "remote_additions": remotes,
        "required_review": [
            "Verify Studio Edit/Publish permissions for this Experience",
            "Review PlayerDataManager versus original saved data and leaderstats contracts",
            "Check RemoteEvent/RemoteFunction collisions and client/server authority",
            "Review package licenses, asset ownership and cross-place behavior",
            "Execute multiplayer, persistence and mobile tests in the OWNED Place",
        ],
    }


def write_addon_manifest(proposal, project_generator, output_dir: Path) -> Path:
    root = Path(output_dir)
    result = addon_manifest(proposal, project_generator)
    result["sources_sha256"] = {
        m.file_path: hashlib.sha256((root / m.file_path).read_bytes()).hexdigest()
        for m in proposal.modules
    }
    target = root / "addon.manifest.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
