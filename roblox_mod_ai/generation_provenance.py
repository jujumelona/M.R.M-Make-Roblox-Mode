"""Authoritative generation source provenance and host-owned overwrite policy.

Do not keep a manual list of individual adapters. A new adapter or changed
planner validator must invalidate checkpoints before prior Luau is resumed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def generation_source_digests(package_dir: Path) -> dict[str, str]:
    """Hash every installed Python generator/validator module deterministically."""
    root = Path(package_dir)
    # Model adapter code, JSON transport, and subpackage schemas affect
    # generated Luau just as directly as top-level authors. glob("*.py")
    # ignored model_adapters/* and permitted a stale code checkpoint to
    # survive an actual backend fix.
    modules = sorted(
        (path for path in root.rglob("*.py") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not modules or not (root / "code_generator.py").is_file():
        raise ValueError("GENERATION_SOURCE_PROVENANCE_MISSING")
    return {
        path.relative_to(root).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
        for path in modules
    }


def host_source_must_regenerate(module: Any, strategy: str) -> bool:
    """Only the host may author host-owned code, even if input embeds stale code.

    Other model-authored modules can resume on an exactly matching signature.
    Host templates, dynamic host buttons, and bounded *data*-driven generators
    must overwrite anything from imported proposals or old checkpoints.
    """
    if strategy.startswith("host_"):
        return True
    return bool(
        module.module_id in (
            "mod_network_bridge", "mod_game_objective", "mod_arena_round", "mod_arena_round_controller",
            "mod_dynamic_server_bootstrap"
        )
        or (
            module.module_id == "mod_player_data"
            and module.file_path.endswith("/PlayerDataManager.luau")
        )
    )


def trusted_checkpoint_source(path: Path, entry: Any, input_sha256: str,
                              supplied_code: str | None = None) -> str | None:
    """Only resume source attested by the current source+plan signature.

    In particular, a loaded proposal's nonempty `module.code` is not proof:
    it may be code from an old adapter, stale API or another generation run.
    """
    if (not isinstance(entry, dict)
            or entry.get("input_sha256") != input_sha256
            or not isinstance(entry.get("source_sha256"), str)
            or not Path(path).is_file()):
        return None
    try:
        source = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not source or hashlib.sha256(source.encode("utf-8")).hexdigest() != entry["source_sha256"]:
        return None
    if supplied_code and supplied_code != source:
        return None
    return source
