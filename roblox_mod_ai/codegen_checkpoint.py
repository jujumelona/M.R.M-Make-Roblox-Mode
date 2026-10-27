"""Checkpoint authority follows the final, validated sources actually packaged.

StyLua and AI repairs can modify files after per-module code-generation
checkpoints were written. The release checkpoint must describe identical
on-disk bytes to avoid stale artifact provenance and misleading cache hits.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable


def sync_release_checkpoints(
    source_root: Path,
    modules: list[Any],
    signature_for: Callable[[Any], str],
) -> dict[str, int]:
    source_root = Path(source_root).resolve()
    path = source_root / "generation_checkpoint.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("schema") != "rmm/codegen-checkpoint-v1":
            old = {}
    except (OSError, ValueError, TypeError, AttributeError):
        old = {}
    previous = old.get("modules")
    if not isinstance(previous, dict):
        previous = {}
    result = {}
    changed = 0
    attested = 0
    for mod in modules:
        relative = mod.file_path
        if (not isinstance(relative, str) or not relative.startswith("src/")
                or not relative.endswith(".luau") or relative in result):
            raise ValueError("RELEASE_CHECKPOINT_INVALID_MODULE_PATH")
        target = (source_root / relative).resolve()
        if not target.is_relative_to(source_root) or not target.is_file():
            raise ValueError("RELEASE_CHECKPOINT_SOURCE_MISSING_OR_UNSAFE: " + relative)
        final_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        sig = signature_for(mod)
        if not isinstance(sig, str) or len(sig) != 64:
            raise ValueError("RELEASE_CHECKPOINT_INVALID_SIGNATURE: " + relative)
        prev = previous.get(relative, {})
        if not isinstance(prev, dict):
            prev = {}
        entry = {"input_sha256": sig, "source_sha256": final_digest}
        if prev.get("source_sha256") != final_digest:
            changed += 1
        # A repaired source is attested only while the exact attested bytes
        # survive. Formatting into different bytes must not inherit this bit.
        if (prev.get("semantic_repair_verified") is True
                and prev.get("source_sha256") == final_digest
                and prev.get("input_sha256") == sig):
            entry["semantic_repair_verified"] = True
            attested += 1
        result[relative] = entry
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "schema": "rmm/codegen-checkpoint-v1",
        "modules": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return {"modules": len(result), "source_digests_updated": changed,
            "semantic_attestations_preserved": attested}
