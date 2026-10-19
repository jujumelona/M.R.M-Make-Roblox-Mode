from pathlib import Path
import pytest
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


@pytest.mark.parametrize("design,expected", [
    ({"dynamic_design": {"remotes": {}}}, True),
    ({}, False),
    ({"dynamic_design": {"remotes": {}}, "storage_backend": "profilestore"}, False),
])
def test_saved_builtin_profile_plan_audits_actual_migrated_module(tmp_path, design, expected):
    import xml.etree.ElementTree as ET
    compiled, proposal = _compiled_fixture(tmp_path)
    module = proposal.modules[0]
    module.module_id = "mod_player_data"
    module.name = "PlayerDataManager"
    module.file_path = "src/server/PlayerDataManager.server.luau"
    proposal.game_design = design
    actual_source = tmp_path / "src/server/PlayerDataManager.luau"
    (tmp_path / "src/server/MyGameplay.server.luau").rename(actual_source)
    xml = ET.parse(compiled)
    script = xml.getroot().find("./Item/Item")
    script.set("class", "ModuleScript")
    script.find("./Properties/string").text = module.name
    xml.write(compiled, encoding="unicode")
    result = inspect_compiled_place(proposal, compiled, source_root=tmp_path)
    assert result["passed"] is expected, result
    if expected:
        actual_source.write_text("print('changed after build')", encoding="utf-8")
        result = inspect_compiled_place(proposal, compiled, source_root=tmp_path)
        assert not result["passed"], "Migration must not skip compiled-source equality"
        assert any(c["id"] == "module.source.PlayerDataManager" and not c["passed"]
                   for c in result["checks"])
