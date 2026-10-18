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
                source_path=Path(source_root)/m.file_path
                try:
                    original=_normalized(source_path.read_text(encoding="utf-8"))
                except (OSError,UnicodeError):
                    original=""
                compiled_source=_source(matches[0]) if len(matches)==1 else None
                check("module.source."+m.name,
                      bool(original) and compiled_source is not None
                      and _normalized(compiled_source)==original)
        dynamic=proposal.game_design.get("dynamic_design") or {}
        for obj in dynamic.get("world_objects", []):
            check("dynamic.world."+obj["name"],
                  (obj["name"],obj["class"]) in
                  [(name,kind) for name,kind,_ in items
                   if any(_name(p)=="Workspace" for p in _ancestors(_find_element(items,name,kind),parents))])
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

def _find_element(items: list[tuple], name: str, kind: str) -> ET.Element | None:
    return next((e for n,k,e in items if n==name and k==kind),None)
