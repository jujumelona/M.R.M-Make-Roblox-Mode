"""Compile actual generated host profile and its callable gameplay consumer.

This verifies the production host's Luau and Rojo layout. The tiny consumer is
a deterministic fixture, not a completed user game or Studio playtest.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.rbxlx_inspector import inspect_compiled_place
from roblox_mod_ai.server_modules import render_dynamic_server_bootstrap


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_callable_host_data import _plan
    proposal, _, feature = _plan()
    feature.code = '''--!strict
local Service = {}
function Service.start(services)
    services.PlayerDataManager.OnReady(function(player)
        local state = services.PlayerDataManager.GetState(player, "ShipService")
        if not state then return end
        state.visits = (state.visits or 0) + 1
        player:SetAttribute("HostProfileReady", true)
    end)
end
return Service
'''
    boot = next(m for m in proposal.modules if m.module_id == "mod_dynamic_server_bootstrap")
    boot.code = render_dynamic_server_bootstrap(proposal)
    root = Path(".rmm-host-profile").resolve()
    RobloxProjectGenerator(root).materialize_project_tree(proposal, root)
    results = []
    for argv in (["stylua", "src"], ["stylua", "--check", "src"],
                 ["selene", "src"], ["rojo", "build", "default.project.json", "-o", "profile.rbxlx"]):
        result = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=90)
        results.append({"command": argv, "exit_code": result.returncode,
                        "stdout": result.stdout[-2000:], "stderr": result.stderr[-3000:]})
        (root / "tool_receipt.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        if result.returncode:
            raise RuntimeError(json.dumps(results[-1]))
    for module in proposal.modules:
        module.code = (root / module.file_path).read_text(encoding="utf-8")
    inspection = inspect_compiled_place(proposal, root / "profile.rbxlx", source_root=root)
    (root / "compiled_place_receipt.json").write_text(json.dumps(inspection, indent=2), encoding="utf-8")
    assert inspection["passed"], inspection
    print("HOST PROFILE COMPILE PASS: actual host ModuleScript and injected consumer; Studio not executed")


if __name__ == "__main__":
    main()
