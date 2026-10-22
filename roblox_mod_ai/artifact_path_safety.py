"""Contain AI-proposed artifact paths in the intended game workspace.

A proposal JSON can be user-supplied or model-generated; neither is permission
to write outside the output tree. This is independent of Luau parsing or
runtime game semantics.
"""
from __future__ import annotations

from pathlib import Path


def safe_segment(value: str, *, field: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value in (".", "..") or "/" in value or "\\" in value
            or "\x00" in value or ":" in value):
        raise ValueError("RMM_INVALID_ARTIFACT_SEGMENT: " + field)
    return value


def safe_project_file(
    root: Path, relative: str, *, prefixes: tuple[str, ...]
) -> Path:
    if (not isinstance(relative, str) or not relative
            or "\\" in relative or "\x00" in relative or ":" in relative):
        raise ValueError("RMM_INVALID_PROJECT_PATH")
    path = Path(relative)
    if (path.is_absolute() or
            any(part in ("", ".", "..") for part in relative.split("/")) or
            not any(relative.startswith(prefix + "/") for prefix in prefixes)):
        raise ValueError("RMM_PROJECT_PATH_OUTSIDE_OWNERSHIP: " + relative)
    anchor = Path(root).resolve()
    candidate = (anchor / path).resolve()
    if not candidate.is_relative_to(anchor):
        raise ValueError("RMM_PROJECT_PATH_ESCAPES_WORKSPACE: " + relative)
    return candidate
