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
    features = proposal.game_design.get("features", {})
    wanted = set()
    if features.get("is_combat"): wanted.update(("AttackRequest", "DamageEvent"))
    if features.get("is_shop"): wanted.add("ShopPurchase")
    if features.get("is_leaderboard") or features.get("is_coin_collect"):
        wanted.add("UpdateStats")
    if features.get("is_obby"): wanted.update(("StageChanged", "ResetToStage"))
    if features.get("is_tycoon"): wanted.add("ButtonPurchased")
    if features.get("is_simulator"): wanted.add("ClickRequest")
    remotes = {
        key: value for key, value in root["ReplicatedStorage"]["Remotes"].items()
        if key in wanted
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
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src").rglob("*.luau")) if path.is_file() and not path.is_symlink()
    }
    target = root / "addon.manifest.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
