"""Real log 30 packaging and Studio MCP execution regressions.

29->30 switched from code generation failures to a duplicate HUD writer.
Generation was 26/26 before package; the legacy hard-coded first-party
dock collided with the newer source-observed generic dock.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from roblox_mod_ai.host_hud import HUD_FILE, install_host_hud
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.roblox_value_contract import roblox_value_contract_errors
from roblox_mod_ai.studio_bridge import StudioMCPClient
from test_46_host_ui_dock import make_game


def test_30_single_winner_generates_hud_no_duplicate_package_writer(tmp_path):
    root = tmp_path / "case30"
    project = RobloxProjectGenerator(tmp_path)
    files = project.materialize_project_tree(make_game(), root)
    target = root / "src/client" / HUD_FILE
    assert files["RMMHUDLayout"] == target
    assert 'gui.Name="RMMUnifiedHUD"' in target.read_text()
    assert "RMMActionDock" not in target.read_text()
    receipt = json.loads((root / ".rmm_hud_source_receipt.json").read_text())
    assert receipt["source_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    # Calling the installer twice must not conflict, corrupt the source or
    # create another dock with a different name.
    before = target.read_bytes()
    assert install_host_hud(root)
    assert target.read_bytes() == before
    assert len(list((root / "src/client").glob("RMMHUDLayout.client.luau"))) == 1


def test_30_exact_shipped_legacy_dock_is_migrated_but_user_source_is_not(tmp_path):
    client = tmp_path / "src/client"
    client.mkdir(parents=True)
    for i, name in enumerate(("PlanetMiningPanel", "TradePanel")):
        (client / f"Scene{i}.client.luau").write_text(
            'local gui=Instance.new("ScreenGui")\n'
            f'gui.Name="{name}"\n'
            'game.ReplicatedStorage.Remotes.Action:InvokeServer({})\n'
        )
    shipped = Path(__file__).resolve().parents[1] / (
        "roblox_mod_ai/rmm_action_dock.client.luau")
    target = client / HUD_FILE
    target.write_bytes(shipped.read_bytes())
    assert install_host_hud(tmp_path)
    assert "RMMUnifiedHUD" in target.read_text()
    assert "RMMActionDock" not in target.read_text()
    # Now overwrite the sealed source to simulate an authored edit. It must
    # not be silently destroyed by the next generate.
    target.write_text(target.read_text() + "\n-- hand edited")
    with pytest.raises(ValueError, match="HUD source conflicts"):
        install_host_hud(tmp_path)


def test_30_model_written_attribute_instance_rejected_at_codegen_gate():
    code = '''
local planet = workspace:FindFirstChild("SpecialMineralDeposit77D3DB31")
local owner = planet:GetAttribute("Owner")
if owner ~= player then return false end
planet:SetAttribute("Colonized", true)
planet:SetAttribute("Colonizer", player)
'''
    errors = roblox_value_contract_errors(code)
    assert any("ATTRIBUTE_NOT_INSTANCE" in e for e in errors), errors
    assert any("ATTRIBUTE_INSTANCE_UNSUPPORTED" in e for e in errors), errors
    assert roblox_value_contract_errors(
        'part:SetAttribute("ColonizerUserId", player.UserId)') == []


def test_30_studio_mcp_sync_facade_from_active_async_event_loop(monkeypatch):
    # This reproduces the actual 30th tool-receipt message:
    # 'asyncio.run() cannot be called from a running event loop'
    import roblox_mod_ai.studio_bridge as bridge

    monkeypatch.setattr(bridge, "studio_command",
                        lambda: ("fake-studio-mcp", []))
    class MockStudio(StudioMCPClient):
        async def call(self, tool_name, arguments=None, allow_write=False):
            await asyncio.sleep(0)
            return {"executed": True, "passed": True, "tool": tool_name}

    async def caller():
        return MockStudio().run("get_studio_state")

    result = asyncio.run(caller())
    assert result["passed"] and result["executed"]


def test_30_studio_unavailable_does_not_pretend_software_was_tested(monkeypatch):
    import roblox_mod_ai.studio_bridge as bridge

    def unavailable():
        raise RuntimeError("Native Roblox Studio MCP requires local Studio")
    monkeypatch.setattr(bridge, "studio_command", unavailable)
    result = StudioMCPClient().run("get_studio_state")
    assert not result["passed"]
    assert result["executed"] is False
    assert "requires local Studio" in result["reason"]
