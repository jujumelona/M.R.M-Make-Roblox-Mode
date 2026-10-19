"""CI real Rojo compilations for NON-space Roblox prompts and arbitrary feature counts.

Deterministic semantic router (NOT MiMo) feeds the production architect. The
host then creates every module name, placement, Remote and safe server gateway.
The fixture source is deliberately minimal; this proves generalized *format*
and compiled structure, not real game behavior or Roblox Studio success.
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
from roblox_mod_ai.code_generator import LuauCodeGenerator


def check_tool(command: tuple[str, ...], cwd: Path | None = None) -> dict:
    check = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, timeout=90,
        check=False)
    detail = {
        "command": list(command), "returncode": check.returncode,
        "stdout_tail": check.stdout[-1800:],
        "stderr_tail": check.stderr[-1800:],
    }
    if check.returncode:
        raise AssertionError(
            "A different Roblox prompt failed compiler/static tooling: " +
            repr(detail))
    return detail


def _ledger(rows):
    return {
        "original_prompt": " | ".join(x[3] for x in rows),
        "requirements": [
            {"id": rid, "statement": clause, "source": "user_prompt"}
            for fid, rid, label, clause, mode in rows
        ],
        "facets": [
            {"id": fid, "requirements": [rid], "source_span": clause}
            for fid, rid, label, clause, mode in rows
        ],
    }


def _module_sources(proposal: RobloxProposal) -> None:
    dynamic = proposal.game_design["dynamic_design"]
    for module in proposal.modules:
        if module.module_id == "mod_network_bridge":
            continue
        if module.module_id == "mod_dynamic_server_bootstrap":
            module.code = render_dynamic_server_bootstrap(proposal)
            continue
        if not module.module_id.startswith("dyn_"):
            raise AssertionError("Unexpected module: " + module.module_id)
        remote_names = dynamic["module_remotes"].get(module.module_id, [])
        assert len(remote_names) <= 1
        if (module.file_path.endswith(".client.luau")
                and module.name in dynamic.get("host_client_actions", {})):
            class NoCoder:
                def complete(self, *args, **kwargs):
                    raise AssertionError("Built-in client UI must not call the model")
            module.code = LuauCodeGenerator(router=NoCoder()).generate_module_code(
                module, proposal)
        elif module.file_path.endswith(".client.luau"):
            assert len(remote_names) == 1
            remote = remote_names[0]
            kind = dynamic["remotes"][remote]
            method = "FireServer" if kind == "RemoteEvent" else "InvokeServer"
            name = module.name
            module.code = (
                "--!strict\n"
                'local ReplicatedStorage = game:GetService("ReplicatedStorage")\n'
                'local ContextActionService = game:GetService("ContextActionService")\n'
                f'local remote = ReplicatedStorage:WaitForChild("Remotes"):WaitForChild("{remote}")\n'
                "local function act(_name, state, _input)\n"
                "    if state ~= Enum.UserInputState.Begin then return Enum.ContextActionResult.Pass end\n"
                f"    remote:{method}()\n"
                "    return Enum.ContextActionResult.Sink\n"
                "end\n"
                f'ContextActionService:BindAction("{name}", act, true, Enum.KeyCode.E)\n'
            )
        elif module.file_path.startswith("src/server/"):
            name = module.name
            host_world_targets = {
                world for world, binding
                in (dynamic.get("host_world_actions") or {}).items()
                if binding["service"] == name
            }
            code = (
                "--!strict\n"
                f"local {name} = {{}}\n"
                f"function {name}.start(_services)\n"
                f'    workspace:SetAttribute("{name}Started", true)\n'
                "end\n"
            )
            if remote_names or host_world_targets:
                code += (
                    f"function {name}.handleAction(player, _services)\n"
                    '    if player.Parent ~= game:GetService("Players") then return false end\n'
                    "    return true\n"
                    "end\n"
                )
            module.code = code + f"return {name}\n"
        else:
            raise AssertionError("Unsupported role and path: " + module.file_path)


def run_case(name: str, rows, root: Path, router_cls, *, expected_remotes: int | None = None) -> dict:
    ledger = _ledger(rows)
    router = router_cls(rows)
    network = RobloxModuleSpec(
        module_id="mod_network_bridge", name="NetworkRemotes",
        kind="shared_module", roblox_service="ReplicatedStorage",
        file_path="src/shared/NetworkRemotes.luau",
        code="--!strict\nlocal NetworkRemotes = {}\nreturn NetworkRemotes\n",
    )
    research = {"ledger": ledger, "evidence": []}
    design = RobloxDynamicArchitect(router).design(
        ledger["original_prompt"], research, [network])
    meta = {key: value for key, value in design.items()
            if key != "modules"}
    proposal = RobloxProposal(
        requested_prompt=ledger["original_prompt"],
        game_title="GenericPromptCase" + name,
        description="CI fixture; not completed Roblox gameplay",
        game_design={
            "genre": "Custom", "features": {}, "project_mode": "new_experience",
            "dynamic_design": meta, "storage_backend": "builtin",
            "pre_design_research": {"ledger": ledger},
        },
        modules=[network, *design["modules"]],
    )
    normalize_dynamic_server_modules(proposal)
    _module_sources(proposal)
    wiring = inspect_dynamic_remote_wiring(proposal)
    contracts = inspect_dynamic_server_interfaces(proposal)
    assert wiring["passed"], (name, wiring)
    assert contracts["passed"], (name, contracts)
    if expected_remotes is None:
        expected_remotes = sum(row[4] != "none" for row in rows)
    assert len(design["remotes"]) == expected_remotes
    assert len(design.get("host_actions", {})) == expected_remotes
    assert len(design["modules"]) == len(rows) + expected_remotes
    assert all(row["validated"] for row in research["architecture_subplans"])
    project = root / name
    RobloxProjectGenerator(root).materialize_project_tree(proposal, project)
    project_json = json.loads(
        (project / "default.project.json").read_text(encoding="utf-8"))
    remotes = project_json["tree"]["ReplicatedStorage"]["Remotes"]
    assert set(remotes) - {"$className"} == set(design["remotes"]), (
        name, "Unexpected template remotes", remotes)
    receipt = {
        "name": name, "source_facet_count": len(rows),
        "generated_module_count": len(design["modules"]),
        "generated_remote_count": len(design["remotes"]),
        "host_action_count": len(design.get("host_actions", {})),
        "host_client_count": len(design.get("host_client_actions", {})),
        "host_world_prompt_count": len(design.get("host_world_actions", {})),
        "model": "DETERMINISTIC SEMANTIC MOCK - NOT REAL MIMO",
        "studio_gameplay_tested": False,
        "tools": [],
    }
    try:
        for cmd, cwd in [
            (("stylua", str(project / "src")), None),
            (("stylua", "--check", str(project / "src")), None),
            (("selene", "src"), project),
            (("rojo", "build", "default.project.json",
              "-o", "compiled-generic.rbxlx"), project),
        ]:
            receipt["tools"].append(check_tool(cmd, cwd))
        audit = inspect_compiled_place(
            proposal, project / "compiled-generic.rbxlx", source_root=project)
        receipt["compiled_place_passed"] = audit["passed"]
        if not audit["passed"]:
            receipt["compiled_errors"] = [c for c in audit["checks"]
                                          if not c.get("passed")]
        assert audit["passed"], (name, audit)
    finally:
        (root / (name + "-receipt.json")).write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return receipt


def main() -> None:
    os.environ["RMM_ENABLE_DYNAMIC_DESIGN"] = "1"
    os.environ.pop("RMM_LEGACY_ARCHITECTURE_PROTOCOL", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_generalized_host_prompt_matrix import ArbitraryPromptSemanticTransport, _sample

    server_only = [
        ("nighttime", "req-weather", "WeatherCycle",
         "Simulate time and rainfall on the server without player actions", "none"),
    ]
    mixed = [
        ("mix-1", "req-001", "PetFeeding",
         "Use a pet feeding button and server-owned pet inventory", "event"),
        ("mix-2", "req-002", "PuzzleAnswers",
         "Send puzzle answers and synchronously receive result", "request_response"),
        ("mix-3", "req-003", "WorldWeather",
         "Synchronize a global storm cycle without client commands", "none"),
    ]
    class ButtonsOnlyRouter(ArbitraryPromptSemanticTransport):
        def complete_json(self, prompt, **kwargs):
            reply = super().complete_json(prompt, **kwargs)
            reply["systems"][0]["input_mode"] = "host_button"
            reply["systems"][0]["world_entities"] = []
            return reply

    button_rows = [
        ("host-clock", "req-clock", "ToggleClock",
         "Toggle global world clock without selecting any target", "event"),
        ("host-status", "req-status", "ServerStatus",
         "Refresh server status without any target or parameters", "request_response"),
    ]
    class NativeWorldPromptRouter(ArbitraryPromptSemanticTransport):
        def complete_json(self, prompt, **kwargs):
            reply = super().complete_json(prompt, **kwargs)
            reply["systems"][0]["input_mode"] = "world_prompt"
            reply["systems"][0]["interaction"] = "event"
            reply["systems"][0]["world_entities"] = ["DoorPart"]
            return reply

    prompt_rows = [
        ("host-vault", "req-vault", "VaultDoor",
         "Use Roblox native world interaction to unlock a server-controlled vault", "event"),
    ]
    long_rows, _ = _sample(47, 9)
    cases = {
        "ServerOnly": server_only,
        "MixedThree": mixed,
        "NineUnrelated": long_rows,
    }
    root = Path(".rmm-general-assembly").resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipts = []
    cases["HostButtonsTwo"] = button_rows
    cases["NativeWorldPrompt"] = prompt_rows
    for name, rows in cases.items():
        receipt = run_case(
            name, rows, root,
            ButtonsOnlyRouter if name == "HostButtonsTwo"
            else NativeWorldPromptRouter if name == "NativeWorldPrompt"
            else ArbitraryPromptSemanticTransport,
            expected_remotes=0 if name == "NativeWorldPrompt" else None)
        receipts.append(receipt)
        print("GENERIC ROBLOX HOST COMPILE PASS", name,
              receipt["source_facet_count"], "features",
              receipt["generated_module_count"], "modules",
              receipt["generated_remote_count"], "remotes")
    assert receipts[0]["generated_remote_count"] == 0
    assert receipts[1]["generated_remote_count"] == 2
    assert receipts[-2]["host_client_count"] == 2
    assert receipts[-2]["generated_remote_count"] == 2
    assert receipts[-1]["host_world_prompt_count"] == 1
    assert receipts[-1]["generated_remote_count"] == 0
    assert receipts[-1]["generated_module_count"] == 1
    summary = {
        "schema": "rmm/generic-host-assembly-v1",
        "cases_passed": len(receipts),
        "case_sizes": [r["source_facet_count"] for r in receipts],
        "actual_mimo_model_executed": False,
        "real_studio_playtested": False,
    }
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
