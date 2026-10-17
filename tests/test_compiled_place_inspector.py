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
