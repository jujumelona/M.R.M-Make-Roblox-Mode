from pathlib import Path
from roblox_mod_ai.rbxlx_inspector import inspect_compiled_place
from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec

def test_fake_empty_xml_cannot_pass_as_generated_game(tmp_path:Path):
    path=tmp_path/"fake.rbxlx"
    path.write_text("<roblox version='4'><Item class='Workspace'><Properties><string name='Name'>Workspace</string></Properties></Item></roblox>")
    proposal=RobloxProposal(requested_prompt="coin",game_title="C",description="",
        game_design={"features":{"is_coin_collect":True}},modules=[
            RobloxModuleSpec(module_id="x",name="CoinCollector",kind="server_script",
                             file_path="src/server/CoinCollector.server.luau",
                             roblox_service="ServerScriptService")
        ])
    result=inspect_compiled_place(proposal,path)
    assert not result["passed"]
    assert any(x["id"]=="module.CoinCollector" for x in result["checks"] if not x["passed"])

def test_unreadable_place_fail_closed(tmp_path:Path):
    p=tmp_path/"x.rbxlx"
    p.write_text("BROKEN")
    proposal=RobloxProposal(requested_prompt="",game_title="X",description="",game_design={},modules=[])
    assert not inspect_compiled_place(proposal,p)["passed"]


def _compiled_fixture(tmp_path: Path, *, compiled_source: str = "print('real')",
                      script_service: str = "ServerScriptService"):
    import xml.etree.ElementTree as ET
    root = ET.Element("roblox", {"version":"4"})
    service = ET.SubElement(root,"Item",{"class":script_service})
    p=ET.SubElement(service,"Properties")
    ET.SubElement(p,"string",{"name":"Name"}).text=script_service
    script=ET.SubElement(service,"Item",{"class":"Script"})
    props=ET.SubElement(script,"Properties")
    ET.SubElement(props,"string",{"name":"Name"}).text="MyGameplay"
    ET.SubElement(props,"ProtectedString",{"name":"Source"}).text=compiled_source
    xml=tmp_path/"compiled.rbxlx"
    ET.ElementTree(root).write(xml,encoding="unicode")
    source=tmp_path/"src/server/MyGameplay.server.luau"
    source.parent.mkdir(parents=True)
    source.write_text("print('real')",encoding="utf-8")
    proposal=RobloxProposal(requested_prompt="game",game_title="Game",description="",
        game_design={},modules=[RobloxModuleSpec(
            module_id="my_game", name="MyGameplay",kind="server_script",
            file_path="src/server/MyGameplay.server.luau",
            roblox_service="ServerScriptService", code="print('real')")])
    return xml,proposal


def test_actual_compiled_script_source_matches_materialized_luau(tmp_path:Path):
    compiled,proposal=_compiled_fixture(tmp_path)
    result=inspect_compiled_place(proposal,compiled,source_root=tmp_path)
    assert result["passed"],result
    assert any(c["id"]=="module.source.MyGameplay" and c["passed"]
               for c in result["checks"])


def test_compiled_script_with_same_name_but_different_code_rejected(tmp_path:Path):
    compiled,proposal=_compiled_fixture(tmp_path,compiled_source="print('dummy')")
    result=inspect_compiled_place(proposal,compiled,source_root=tmp_path)
    assert not result["passed"]
    assert any(c["id"]=="module.source.MyGameplay" and not c["passed"]
               for c in result["checks"])


def test_compiled_script_in_wrong_service_rejected(tmp_path:Path):
    compiled,proposal=_compiled_fixture(tmp_path,script_service="Workspace")
    result=inspect_compiled_place(proposal,compiled,source_root=tmp_path)
    assert not result["passed"]
    assert any(c["id"]=="module.MyGameplay" and not c["passed"]
               for c in result["checks"])
