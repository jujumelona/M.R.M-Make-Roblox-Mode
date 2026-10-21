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
    modules = sorted(root.glob("*.py"), key=lambda path: path.name)
    if not modules or not (root / "code_generator.py").is_file():
        raise ValueError("GENERATION_SOURCE_PROVENANCE_MISSING")
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in modules
        if path.is_file()
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
            "mod_game_objective", "mod_arena_round", "mod_arena_round_controller",
            "mod_dynamic_server_bootstrap"
        )
        or (
            module.module_id == "mod_player_data"
            and module.file_path.endswith("/PlayerDataManager.luau")
        )
    )
