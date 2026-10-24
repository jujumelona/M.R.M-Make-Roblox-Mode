"""Type-check materialized Roblox Instances against their actual world specs.

Use the host world manifest as the source of truth. A 9B model may write
WorldObject:IsA("Model") or :GetState() despite the generator creating a Part.
A Luau parser cannot detect that always-failing gameplay branch.
"""
from __future__ import annotations

import re
from typing import Any

_NAME = r"[A-Za-z_]\w*"
_LOOKUP = re.compile(
    r"\blocal\s+(" + _NAME + r")\s*=\s*workspace\s*:\s*"
    r"(?:FindFirstChild|WaitForChild)\s*\(\s*(['\"])([^'\"\n]+)\2"
)
_DIRECT = re.compile(
    r"\blocal\s+(" + _NAME + r")\s*=\s*workspace\s*\.\s*(" + _NAME + r")\b"
)
_CLASS_TEST = re.compile(
    r"\b(" + _NAME + r")\s*:\s*IsA\s*\(\s*(['\"])([A-Za-z_]+)\2"
)
_BAD_METHOD = re.compile(
    r"\b(" + _NAME + r")\s*:\s*SetPrimaryPartC\s*\("
)
_SUPER = {
    "Part": {"Part", "BasePart", "PVInstance", "Instance"},
    "MeshPart": {"MeshPart", "BasePart", "PVInstance", "Instance"},
    "Model": {"Model", "PVInstance", "Instance"},
    "IntValue": {"IntValue", "ValueBase", "Instance"},
}
_INCOMPATIBLE_TYPES = {
    "Part", "MeshPart", "Model", "IntValue", "StringValue",
    "BoolValue", "RemoteEvent", "RemoteFunction", "Player",
    "Folder", "Attachment", "BindableEvent", "NumberValue", "Humanoid",
}


def world_instance_type_errors(code: str, proposal: Any) -> list[str]:
    if not isinstance(code, str) or not code:
        return []
    design = (getattr(proposal, "game_design", {}) or {}).get("dynamic_design") or {}
    classes = {
        obj.get("name"): obj.get("class")
        for obj in design.get("world_objects", [])
        if isinstance(obj, dict) and isinstance(obj.get("name"), str)
        and isinstance(obj.get("class"), str)
    }
    if not classes:
        return []

    from .dynamic_wiring import _without_comments, _mask_strings
    raw = _without_comments(code)
    masked = _mask_strings(raw)
    names: dict[str, tuple[str, str]] = {}
    for matcher in (_LOOKUP, _DIRECT):
        for match in matcher.finditer(raw):
            if not re.search(r"\blocal\b", masked[match.start():match.start()+6]):
                continue
            name = match.group(3) if matcher is _LOOKUP else match.group(2)
            if name in classes:
                names[match.group(1)] = (name, classes[name])
    problems: list[str] = []
    for match in _CLASS_TEST.finditer(raw):
        actual = names.get(match.group(1))
        if not actual:
            continue
        name, cls = actual
        requested = match.group(3)
        if (requested in _INCOMPATIBLE_TYPES and
                requested not in _SUPER.get(cls, {cls, "Instance"})):
            problems.append(
                "WORLD_INSTANCE_TYPE_IMPOSSIBLE: " + name +
                " is materialized as " + cls +
                ", not as " + requested
            )
    # This invented spelling is not a Roblox engine method on ANY Instance.
    # Type lookup is unnecessary to prove that error.
    if re.search(r"\b" + _NAME + r"\s*:\s*SetPrimaryPartC\s*\(", masked):
        problems.append(
            "ROBLOX_ENGINE_METHOD_UNDEFINED: SetPrimaryPartC is not a "
            "Roblox Instance method; use verified Model:PivotTo or BasePart.CFrame"
        )
    return sorted(set(problems))
