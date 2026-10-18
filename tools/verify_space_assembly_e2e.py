"""CI: assemble seven source-anchored space-game feature plans into one real Rojo place.

The local model is replaced with a deterministic transport. The production
planner validator, server bootstrap, wiring/interface analyzers, and real Luau
compilation paths remain active. This proves *structural integration only*, not
actual MiMo implementation or user-requested gameplay correctness.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from roblox_mod_ai.dynamic_architect import RobloxDynamicArchitect
from roblox_mod_ai.dynamic_wiring import inspect_dynamic_remote_wiring
from roblox_mod_ai.server_interface_audit import inspect_dynamic_server_interfaces
from roblox_mod_ai.server_modules import (
    normalize_dynamic_server_modules, render_dynamic_server_bootstrap,
)
from roblox_mod_ai.project_generator import RobloxProjectGenerator
from roblox_mod_ai.rbxlx_inspector import inspect_compiled_place
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def run_command(*args: str) -> dict:
    result = subprocess.run(args, text=True, capture_output=True,
                            timeout=90, check=False)
    return {"cmd": list(args), "returncode": result.returncode,
            "stdout": result.stdout[-1400:], "stderr": result.stderr[-2000:]}


def main() -> None:
    os.environ["RMM_ENABLE_DYNAMIC_DESIGN"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_space_seven_facets_e2e import (
        FakeLocalModel, _PROMPT, _user_space_ledger,
    )

    root = Path(".rmm-space-assembly").resolve()
    root.mkdir(parents=True, exist_ok=True)
    model = FakeLocalModel()
    ledger = _user_space_ledger()
    network = RobloxModuleSpec(
        module_id="mod_network_bridge", name="NetworkRemotes",
        kind="shared_module", roblox_service="ReplicatedStorage",
        file_path="src/shared/NetworkRemotes.luau",
        code="--!strict\nlocal NetworkRemotes = {}\nreturn NetworkRemotes\n",
    )
    research = {"ledger": ledger, "evidence": []}
    dynamic = RobloxDynamicArchitect(router=model).design(
        _PROMPT, research, [network],
    )
    proposal = RobloxProposal(
        requested_prompt=_PROMPT, game_title="SpaceStructuralFixture",
        description="CI integration fixture, not implemented space gameplay",
        game_design={"genre": "Custom", "project_mode": "new_experience",
                     "features": {}, "dynamic_design": dynamic,
                     "storage_backend": "builtin",
                     "pre_design_research": {"ledger": ledger}},
        modules=[network, *dynamic["modules"]],
    )
    normalize_dynamic_server_modules(proposal)

    for module in proposal.modules:
        if module.module_id == "mod_network_bridge":
            continue
        if module.module_id == "mod_dynamic_server_bootstrap":
            module.code = render_dynamic_server_bootstrap(proposal)
            continue
        assert module.module_id.startswith("dyn_")
        remotes = dynamic["module_remotes"].get(module.module_id, [])
        assert len(remotes) == 1, (module.name, remotes)
        remote = remotes[0]
        if module.file_path.endswith(".client.luau"):
            module.code = (
                "--!strict\n"
                "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                "local ContextActionService = game:GetService('ContextActionService')\n"
                f"local remote = ReplicatedStorage:WaitForChild('Remotes'):WaitForChild('{remote}')\n"
                f"local function action{name_safe(module.name)}(_action, state, _input)\n"
                "    if state ~= Enum.UserInputState.Begin then return Enum.ContextActionResult.Pass end\n"
                "    remote:FireServer()\n"
                "    return Enum.ContextActionResult.Sink\n"
                "end\n"
                f"ContextActionService:BindAction('{module.name}', action{name_safe(module.name)}, true, Enum.KeyCode.E)\n"
            )
        elif module.file_path.startswith("src/server/"):
            identifier = module.name
            module.code = (
                "--!strict\n"
                "local ReplicatedStorage = game:GetService('ReplicatedStorage')\n"
                f"local {identifier} = {{}}\n"
                f"function {identifier}.start(_services)\n"
                f"    local remote = ReplicatedStorage:WaitForChild('Remotes'):WaitForChild('{remote}')\n"
                "    remote.OnServerEvent:Connect(function(player)\n"
                "        if typeof(player) ~= 'Instance' or not player:IsA('Player') then return end\n"
                "        if player.Parent ~= game:GetService('Players') then return end\n"
                "    end)\n"
                "end\n"
                f"return {identifier}\n"
            )
        else:
            raise AssertionError("Unexpected module location " + module.file_path)

    wiring = inspect_dynamic_remote_wiring(proposal)
    interface = inspect_dynamic_server_interfaces(proposal)
    assert wiring["passed"], wiring
    assert interface["passed"], interface
    assert len([m for m in proposal.modules if m.file_path.endswith(".client.luau")]) == 7
    assert len([m for m in proposal.modules if m.file_path.startswith("src/server/")
                and not m.file_path.endswith(".server.luau")]) == 7
    assert len(dynamic["remotes"]) == 7

    project = root / "project"
    RobloxProjectGenerator(root).materialize_project_tree(proposal, project)
    (root / "proposal.json").write_text(json.dumps(
        proposal.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"schema": "rmm/seven-facet-assembly-ci-v1",
              "model_type": "DETERMINISTIC FIXTURE, NOT MIMO",
              "real_roblox_studio_execution": False,
              "source_facets": 7, "authored_modules": 14,
              "connected_remotes": len(dynamic["remotes"]),
              "wiring_checked": wiring["passed"],
              "exports_checked": interface["passed"],
              "compiler_tools": []}

    for command in [
        ("stylua", str(project / "src")),
        ("stylua", "--check", str(project / "src")),
        ("selene", "src"),
        ("rojo", "build", "default.project.json", "-o", "compiled-space.rbxlx"),
    ]:
        # Keep Selene/Rojo paths relative to the actual Rojo project.
        cwd = project if command[0] in {"selene", "rojo"} else None
        check = subprocess.run(command, cwd=cwd, text=True,
                               capture_output=True, timeout=90, check=False)
        result["compiler_tools"].append({
            "command": list(command), "returncode": check.returncode,
            "stderr": check.stderr[-2000:], "stdout": check.stdout[-1000:],
        })
        if check.returncode != 0:
            (root / "receipt.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            raise AssertionError("Real seven-facet compilation failed: " +
                                 repr(command) + "\n" + check.stderr[-2000:])

    place = project / "compiled-space.rbxlx"
    assert place.is_file() and place.stat().st_size > 2000
    audit = inspect_compiled_place(proposal, place, source_root=project)
    result["compiled_place_passed"] = audit["passed"]
    if not audit["passed"]:
        result["compiled_place_errors"] = [c for c in audit["checks"]
                                           if not c.get("passed")]
    (root / "receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert audit["passed"], result
    print("SEVEN-FACET STRUCTURAL ASSEMBLY E2E PASS: 14 model-role modules,"
          " 7 remotes, actual StyLua/Selene/Rojo, NOT MiMo or Studio gameplay")


def name_safe(name: str) -> str:
    return name


if __name__ == "__main__":
    main()
