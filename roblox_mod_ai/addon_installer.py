"""Apply an additive RMM add-on to a locally OWNED Rojo project.

A local file being writable does NOT prove Roblox Edit/Publish permission.
Never deploys or alters a live universe; explicit manual owner review required.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .project_modes import EXISTING_ADDON

SOURCE_MAPPINGS = {
    "src/server/": ("ServerScriptService",),
    "src/client/": ("StarterPlayer", "StarterPlayerScripts"),
    "src/shared/": ("ReplicatedStorage", "Shared"),
    "src/gui/": ("StarterGui",),
}


def _within(path: Path, root: Path) -> Path:
    path = path.resolve()
    root = root.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Refusing project path outside owner-provided Rojo workspace")
    return path


def _read(addon_dir: Path, project_dir: Path) -> tuple[dict, dict, Path]:
    addon_dir = Path(addon_dir).resolve()
    project_dir = Path(project_dir).resolve()
    manifest = json.loads((addon_dir / "addon.manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema") != "rmm/owned-experience-addon-v1"
            or manifest.get("project_mode") != EXISTING_ADDON
            or manifest.get("standalone_place") is not False):
        raise ValueError("Not a valid owned-Experience extension package")
    hashes = manifest.get("sources_sha256")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Addon has no signed-by-content source manifest")
    discovered = {p.relative_to(addon_dir).as_posix() for p in (addon_dir / "src").rglob("*.luau")}
    if discovered != set(hashes):
        raise ValueError("Addon sources and source hashes disagree")
    for name, expected in hashes.items():
        source = _within(addon_dir / name, addon_dir)
        if not source.is_file() or source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Addon source is missing or modified: " + name)
    basefile = _within(project_dir / "default.project.json", project_dir)
    base = json.loads(basefile.read_text(encoding="utf-8"))
    if not isinstance(base.get("tree"), dict):
        raise ValueError("Existing project is missing Rojo tree")
    return manifest, base, basefile


def prepare_owned_addon(addon_dir: Path, project_dir: Path) -> dict:
    """Zero modifications. Reject any collisions before a user can approve apply."""
    addon_dir = Path(addon_dir).resolve()
    project_dir = Path(project_dir).resolve()
    manifest, base, basefile = _read(addon_dir, project_dir)
    tree = base["tree"]
    additions: list[tuple[str, str]] = []
    conflicts: list[str] = []
    for path in sorted((addon_dir / "src").rglob("*.luau")):
        if path.is_symlink():
            conflicts.append("symlink is forbidden: " + str(path))
            continue
        rel = path.relative_to(addon_dir).as_posix()
        for prefix, keys in SOURCE_MAPPINGS.items():
            if not rel.startswith(prefix):
                continue
            node = tree
            for key in keys:
                if not isinstance(node, dict) or key not in node:
                    conflicts.append("Missing original Rojo service mapping: " + ".".join(keys))
                    node = None
                    break
                node = node[key]
            if node is None or not isinstance(node, dict) or not isinstance(node.get("$path"), str):
                conflicts.append("Original project must map its source folder: " + ".".join(keys))
                break
            base_path = node["$path"]
            target = _within(project_dir / base_path / rel[len(prefix):], project_dir)
            if target.is_file() or target.is_symlink():
                conflicts.append("Existing script would be overwritten: " + str(target))
            elif target.suffix not in (".luau", ".lua"):
                conflicts.append("Unrecognized script extension: " + rel)
            else:
                additions.append((rel, str(target)))
            break
        else:
            conflicts.append("Unsupported addon code location: " + rel)

    world = tree.get("Workspace")
    if not isinstance(world, dict):
        conflicts.append("Existing Rojo project does not declare Workspace")
        world = {}
    for name in manifest.get("workspace_additions", {}):
        if name.startswith("$") or name in world:
            conflicts.append("Existing Workspace object collision: " + name)
    rep = tree.get("ReplicatedStorage")
    if not isinstance(rep, dict):
        conflicts.append("Existing project missing ReplicatedStorage service")
        remotes = {}
    else:
        remotes = rep.get("Remotes", {})
        if remotes and not isinstance(remotes, dict):
            conflicts.append("Existing Remotes is not a Rojo dictionary")
            remotes = {}
    for name, spec in manifest.get("remote_additions", {}).items():
        existing = remotes.get(name)
        if existing is not None and existing != spec:
            conflicts.append("Existing Remote has incompatible type: " + name)
    wally = (addon_dir / "wally.toml").read_text(encoding="utf-8")
    if 'ProfileStore = ' in wally and not (project_dir / "ServerPackages/ProfileStore.lua").is_file():
        conflicts.append("Missing ProfileStore in owned project Wally packages")
    if 'Fusion = ' in wally and not (project_dir / "Packages/Fusion.lua").is_file():
        conflicts.append("Missing Fusion in owned project Wally packages")
    if not (addon_dir / "src").is_dir():
        conflicts.append("No source tree")
    if not additions:
        conflicts.append("No non-conflicting Luau sources")
    return {
        "passed": len(conflicts) == 0, "conflicts": conflicts,
        "files_to_add": additions,
        "workspace_additions": list(manifest.get("workspace_additions", {})),
        "remotes_to_add": list(manifest.get("remote_additions", {})),
        "has_new_player_data": any(rel.endswith("/PlayerDataManager.server.luau") for rel,_ in additions),
        "owner_permission_verified": False,
        "requires_existing_place_studio_test": True,
        "base_project_hash": hashlib.sha256(basefile.read_bytes()).hexdigest(),
    }


def apply_owned_addon(addon_dir: Path, project_dir: Path, *,
                      i_own_this_experience: bool = False,
                      reviewed_player_data: bool = False) -> dict:
    """Explicitly-approved local source patch. Never publishes to Roblox."""
    if not i_own_this_experience:
        raise PermissionError("Owner/editor confirmation required; cannot modify third-party Experiences")
    proposal = prepare_owned_addon(addon_dir, project_dir)
    if not proposal["passed"]:
        raise ValueError("Addon has blocking conflicts: " + "; ".join(proposal["conflicts"]))
    if proposal["has_new_player_data"] and not reviewed_player_data:
        raise PermissionError("Manual PlayerData/DataStore/leaderstats compatibility review required")
    addon_dir, project_dir = Path(addon_dir).resolve(), Path(project_dir).resolve()
    manifest, base, basefile = _read(addon_dir, project_dir)
    if hashlib.sha256(basefile.read_bytes()).hexdigest() != proposal["base_project_hash"]:
        raise RuntimeError("Original Rojo file changed during preflight")
    tree = base["tree"]
    world = tree["Workspace"]
    world.update(manifest["workspace_additions"])
    rep = tree["ReplicatedStorage"]
    remotes = rep.setdefault("Remotes", {"$className": "Folder"})
    for name, item in manifest["remote_additions"].items():
        remotes.setdefault(name, item)
    # Stage project JSON and new Luau scripts first. Keep originals untouched.
    temp_paths: list[Path] = []
    installed: list[Path] = []
    json_tmp: Path | None = None
    try:
        for src_name, dest_name in proposal["files_to_add"]:
            dest = Path(dest_name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists(): raise FileExistsError(str(dest))
            with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".rmm-stage-", delete=False) as f:
                f.write((addon_dir / src_name).read_bytes())
                temp_paths.append(Path(f.name))
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=basefile.parent,
                                         prefix=".rmm-project-", suffix=".json", delete=False) as f:
            json.dump(base, f, indent=2, ensure_ascii=False)
            json_tmp = Path(f.name)
        for staged, (_, dest_name) in zip(temp_paths, proposal["files_to_add"]):
            dest = Path(dest_name)
            if dest.exists(): raise FileExistsError(str(dest))
            os.replace(staged, dest)
            installed.append(dest)
        os.replace(json_tmp, basefile)
    except Exception:
        for dest in installed:
            dest.unlink(missing_ok=True)
        raise
    finally:
        for p in temp_paths:
            p.unlink(missing_ok=True)
        if json_tmp is not None: json_tmp.unlink(missing_ok=True)
    return {
        "local_files_applied": len(installed), "project_file_updated": True,
        "published": False, "roblox_permissions_verified": False,
        "studio_test_passed": False,
        "note": "Use Studio in the owner's Experience to verify all systems before any publication",
    }
