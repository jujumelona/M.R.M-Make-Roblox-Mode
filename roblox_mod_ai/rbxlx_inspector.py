"""Inspect actual Rojo-compiled .rbxlx instead of treating any XML as a game.

This validates source/module/world presence only, not engine execution.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from .spec import RobloxProposal

def _name(item: ET.Element) -> str:
    props=item.find("Properties")
    if props is None: return ""
    for prop in props:
        if prop.get("name")=="Name":
            return prop.text or ""
    return ""

def inspect_compiled_place(proposal: RobloxProposal, compiled: Path) -> dict:
    checks=[]
    def check(code, passed):
        checks.append({"id":code,"passed":bool(passed)})
    try:
        tree=ET.parse(compiled)
        if tree.getroot().tag != "roblox":
            raise ValueError("Invalid Roblox place XML root")
        items=[(_name(e),e.attrib.get("class","")) for e in tree.findall(".//Item")]
        names={n for n,c in items}
        scripts={n for n,c in items if c in ("Script","LocalScript","ModuleScript")}
        check("place.root",True)
        for m in proposal.modules:
            check("module."+m.name,m.name in scripts)
        flags=proposal.game_design.get("features",{})
        if flags.get("is_coin_collect"):
            check("world.coins","Coins" in names and any(name.startswith("Coin") for name in names))
        if flags.get("is_shop"):
            check("world.shop","ShopStalls" in names and "ShopPrompt" in names)
        if flags.get("is_combat"):
            check("world.arena","CombatArena" in names)
        if proposal.game_design.get("storage_backend")=="profilestore":
            check("packages.server","ServerPackages" in names and "ProfileStore" in scripts)
        if proposal.game_design.get("ui_backend")=="fusion":
            check("packages.fusion","Packages" in names and "Fusion" in scripts)
    except (ET.ParseError,OSError,ValueError) as exc:
        check("place.xml",False)
        return {"passed":False,"checks":checks,"error":str(exc)}
    return {"passed":all(c["passed"] for c in checks),"checks":checks,
            "scope":"compiled_structure_only"}
