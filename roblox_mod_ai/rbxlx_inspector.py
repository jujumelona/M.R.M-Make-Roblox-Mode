"""Verify the actual Rojo-built Place, not merely that an XML file exists.

Structural tests are useful but NOT Roblox Studio or multiplayer behavior tests.
When the owning Rojo source directory is provided, verify exactly one correctly
placed script AND its compiled Source text matches the on-disk Luau bytes.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from .spec import RobloxProposal

_SCRIPT_CLASSES = ("Script", "LocalScript", "ModuleScript")
_EXPECTED_LOCATION = {
    "src/server/": ("ServerScriptService", "Script"),
    "src/client/": ("StarterPlayerScripts", "LocalScript"),
    "src/shared/": ("Shared", "ModuleScript"),
    "src/gui/": ("StarterGui", "LocalScript"),
}

def _name(item: ET.Element) -> str:
    props=item.find("Properties")
    if props is None: return ""
    for prop in props:
        if prop.get("name")=="Name":
            return prop.text or ""
    return ""

def _source(item: ET.Element) -> str | None:
    props=item.find("Properties")
    if props is None: return None
    for prop in props:
        if prop.get("name")=="Source":
            # Rojo XML serializes script Source as ProtectedString or similar.
            return prop.text or ""
    return None

def _normalized(source: str) -> str:
    return source.replace("\r\n","\n").replace("\r","\n").strip()

def inspect_compiled_place(proposal: RobloxProposal, compiled: Path,
                           source_root: Path | None = None) -> dict:
    checks=[]
    def check(code, passed):
        checks.append({"id":code,"passed":bool(passed)})
    try:
        tree=ET.parse(compiled)
        root=tree.getroot()
        if root.tag != "roblox":
            raise ValueError("Invalid Roblox place XML root")
        elems=root.findall(".//Item")
        parents={child:parent for parent in root.iter() for child in parent}
        items=[(_name(e),e.attrib.get("class",""),e) for e in elems]
        names={n for n,_,_ in items}
        dynamic=proposal.game_design.get("dynamic_design") or {}
        check("place.root",True)
        for m in proposal.modules:
            expected=None
            for prefix, location in _EXPECTED_LOCATION.items():
                if m.file_path.startswith(prefix):
                    expected=location
                    break
            if expected is None:
                check("module."+m.name,False)
                continue
            target_parent,target_class=expected
            if (m.file_path.startswith("src/server/")
                    and m.file_path.endswith(".luau")
                    and not m.file_path.endswith(".server.luau")):
                target_class = "ModuleScript"
            # Older authored plans declared dynamic .server.luau Scripts.
            # Production normalizes them and the builtin dynamic profile to
            # requireable ModuleScripts plus a host bootstrap. Audit the REAL compiled and on-disk type;
            # never skip source equality or treat arbitrary Scripts as modules.
            source_file = m.file_path
            migrated_profile = (bool(dynamic) and m.module_id == "mod_player_data"
                                and m.name == "PlayerDataManager"
                                and proposal.game_design.get("storage_backend", "builtin") == "builtin")
            if (source_root is not None and (m.module_id.startswith("dyn_") or migrated_profile)
                    and m.file_path.startswith("src/server/")
                    and m.file_path.endswith(".server.luau")):
                candidate = m.file_path[:-len(".server.luau")] + ".luau"
                if (Path(source_root) / candidate).is_file():
                    source_file = candidate
                    target_class = "ModuleScript"
            matches=[]
            for name,kind,element in items:
                if name!=m.name or kind!=target_class:
                    continue
                parent=parents.get(element)
                lineage=[]
                while parent is not None:
                    lineage.append(_name(parent))
                    parent=parents.get(parent)
                if target_parent in lineage:
                    matches.append(element)
            check("module."+m.name,len(matches)==1)
            if source_root is not None:
                source_path=Path(source_root)/source_file
                try:
                    original=_normalized(source_path.read_text(encoding="utf-8"))
                except (OSError,UnicodeError):
                    original=""
                compiled_source=_source(matches[0]) if len(matches)==1 else None
                check("module.source."+m.name,
                      bool(original) and compiled_source is not None
                      and _normalized(compiled_source)==original)
        if (source_root is not None and dynamic and
                (Path(source_root) / "src/server/RMMServerBootstrap.server.luau").is_file()):
            bootstrap = [e for name, kind, e in items
                         if name == "RMMServerBootstrap" and kind == "Script"
                         and any(_name(x) == "ServerScriptService"
                                 for x in _ancestors(e, parents))]
            check("module.RMMServerBootstrap", len(bootstrap) == 1)
            disk = (Path(source_root) /
                    "src/server/RMMServerBootstrap.server.luau")
            check("module.source.RMMServerBootstrap",
                  len(bootstrap) == 1
                  and _normalized(_source(bootstrap[0]) or "")
                  == _normalized(disk.read_text(encoding="utf-8")))
        for obj in dynamic.get("world_objects", []):
            matches=[e for name,kind,e in items
                     if name==obj["name"] and kind==obj["class"]
                     and any(_name(p)=="Workspace" for p in _ancestors(e,parents))]
            check("dynamic.world."+obj["name"],len(matches)==1)
            # Presence is not enough: a Position-only exported Part can
            # exist in the XML yet fail to materialize at its declared orbit
            # or mining coordinates. Rojo must serialize actual CFrame.
            correct_pose = False
            if len(matches) == 1 and obj.get("class") in (
                    "Part", "MeshPart", "SpawnLocation"):
                props = matches[0].find("Properties")
                cframe = (next(
                    (item for item in props
                     if item.get("name") == "CFrame"), None)
                    if props is not None else None)
                expected_xyz = obj.get("position")
                if (cframe is not None and cframe.tag in (
                        "CoordinateFrame", "CFrame")
                        and isinstance(expected_xyz, (list, tuple))
                        and len(expected_xyz) == 3):
                    try:
                        actual_xyz = [float(cframe.findtext(axis))
                                      for axis in ("X", "Y", "Z")]
                        correct_pose = all(
                            abs(actual - float(expected)) < 0.001
                            for actual, expected in zip(actual_xyz, expected_xyz)
                        )
                    except (TypeError, ValueError):
                        correct_pose = False
            check("dynamic.world_pose."+obj["name"],correct_pose)
        for remote_name, remote_class in dynamic.get("remotes", {}).items():
            matching=[e for n,k,e in items
                      if n==remote_name and k==remote_class and
                      {"Remotes","ReplicatedStorage"}.issubset(
                          {_name(x) for x in _ancestors(e,parents)})]
            check("dynamic.remote."+remote_name,len(matching)==1)
        flags=proposal.game_design.get("features",{})
        if flags.get("is_coin_collect"):
            check("world.coins","Coins" in names and any(name.startswith("Coin") for name in names))
        if flags.get("is_shop"):
            check("world.shop","ShopStalls" in names and "ShopPrompt" in names)
        if flags.get("is_combat"):
            check("world.arena","CombatArena" in names)
        if proposal.game_design.get("storage_backend")=="profilestore":
            check("packages.server","ServerPackages" in names and
                  any(n=="ProfileStore" and c in _SCRIPT_CLASSES for n,c,_ in items))
        if proposal.game_design.get("ui_backend")=="fusion":
            check("packages.fusion","Packages" in names and
                  any(n=="Fusion" and c in _SCRIPT_CLASSES for n,c,_ in items))
    except (ET.ParseError,OSError,ValueError) as exc:
        check("place.xml",False)
        return {"passed":False,"checks":checks,"error":str(exc)}
    return {"passed":all(c["passed"] for c in checks),"checks":checks,
            "scope":"compiled_source_and_structure_not_engine_runtime"
                    if source_root is not None else "compiled_structure_only"}

def _ancestors(element: ET.Element | None, parents: dict) -> list[ET.Element]:
    if element is None:
        return []
    result=[]
    parent=parents.get(element)
    while parent is not None:
        result.append(parent)
        parent=parents.get(parent)
    return result

