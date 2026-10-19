"""Host persistence is callable from gameplay services and tested as real Luau."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from roblox_mod_ai.code_generator import LuauCodeGenerator
from roblox_mod_ai.server_modules import normalize_dynamic_server_modules, render_dynamic_server_bootstrap
from roblox_mod_ai.server_interface_audit import inspect_dynamic_server_interfaces
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def _plan():
    network = RobloxModuleSpec(module_id="mod_network_bridge", name="NetworkRemotes", kind="shared_module",
                               file_path="src/shared/NetworkRemotes.luau", roblox_service="ReplicatedStorage")
    data = RobloxModuleSpec(module_id="mod_player_data", name="PlayerDataManager", kind="data_store",
                            file_path="src/server/PlayerDataManager.server.luau", roblox_service="ServerScriptService")
    feature = RobloxModuleSpec(module_id="dyn_ship", name="ShipService", kind="server_script",
                               file_path="src/server/ShipService.server.luau", roblox_service="ServerScriptService",
                               description="Maintain player-owned ship construction and persist its assembled parts.")
    p = RobloxProposal(requested_prompt="조립한 우주선 부품 저장", game_title="DataHost", description="",
                       game_design={"dynamic_design": {"remotes": {}}}, modules=[network, data, feature])
    normalize_dynamic_server_modules(p)
    generator = LuauCodeGenerator()
    network.code = generator.generate_module_code(network, p)
    data.code = generator.generate_module_code(data, p)
    return p, data, feature


def test_callable_profile_uses_single_renewal_snapshot_path():
    _, data, _ = _plan()
    # The callable form uses savePlayerData(player, false), which collects the
    # current live stats, persists inventory and renews the session lease.
    # Redundant standalone pre-renewal locals caused five Selene warnings.
    assert "if not savePlayerData(player, false) then" in data.code
    assert "local coinsSnapshot" not in data.code
    assert "local inventorySnapshot" not in data.code


def test_generated_gameplay_uses_callable_host_profile_service():
    p, data, feature = _plan()
    assert data.file_path == "src/server/PlayerDataManager.luau"
    assert data.kind == "server_module"
    boot = render_dynamic_server_bootstrap(p)
    assert '"PlayerDataManager"' in boot
    assert boot.index('"PlayerDataManager"') < boot.index('"ShipService"')
    feature.code = ("local Service = {}\nfunction Service.start(services)\n"
                    "services.PlayerDataManager.OnReady(function(player)\n"
                    "local state = services.PlayerDataManager.GetState(player, 'ShipService')\n"
                    "state.parts = state.parts or {}\nend)\nend\nreturn Service")
    report = inspect_dynamic_server_interfaces(p)
    assert report["passed"], report


@pytest.mark.skipif(not shutil.which("lune"), reason="Actual Lune runtime required")
def test_actual_generated_player_state_survives_save_and_reload(tmp_path):
    _, data, _ = _plan()
    source = tmp_path / "PlayerDataManager.luau"
    source.write_text(data.code, encoding="utf-8")
    script = Path(__file__).with_name("host_player_data_e2e.luau")
    result = subprocess.run(["lune", "run", str(script)], text=True, capture_output=True,
                            env={**os.environ, "RMM_PLAYER_DATA_SOURCE": str(source)}, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PLAYER DATA E2E PASS" in result.stdout


def test_obsolete_autorunning_profile_is_retired_before_rojo_packaging(tmp_path):
    from roblox_mod_ai.project_generator import RobloxProjectGenerator
    p, data, _ = _plan()
    stale = tmp_path / "src/server/PlayerDataManager.server.luau"
    stale.parent.mkdir(parents=True)
    stale.write_text("print('obsolete host script')", encoding="utf-8")
    RobloxProjectGenerator(tmp_path).materialize_project_tree(p, tmp_path)
    assert not stale.exists(), "Rojo would still run the obsolete .server.luau alongside the new service"
    retired = list((tmp_path / "retired_sources").rglob("*.luau"))
    assert retired and retired[0].read_text(encoding="utf-8") == "print('obsolete host script')"
    assert (tmp_path / data.file_path).is_file()
