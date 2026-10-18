"""Negative acceptance tests for stale formatted code and realm-incompatible APIs.

These mutations must be rejected on the very file the compiler will read;
otherwise in-memory source scans can falsely certify a stale program.
"""
from pathlib import Path

from roblox_mod_ai.quality_gates import acceptance_obligations
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def plan_with_source(root: Path, *, server_source=None, client_source=None):
    server_source = server_source or (
        "--!strict\nlocal Mining = {}\n"
        "function Mining.start(services)\n"
        "    local count = 3\n"
        "    assert(count > 0)\n"
        "end\nreturn Mining\n"
    )
    client_source = client_source or (
        "--!strict\nlocal UserInputService = game:GetService('UserInputService')\n"
        "print(UserInputService.KeyboardEnabled)\n"
    )
    modules = [
        RobloxModuleSpec(
            module_id="dyn_mining", name="Mining",
            kind="server_module", roblox_service="ServerScriptService",
            file_path="src/server/Mining.luau",
            code=server_source,
        ),
        RobloxModuleSpec(
            module_id="dyn_input", name="MiningInput",
            kind="client_script",
            roblox_service="StarterPlayer.StarterPlayerScripts",
            file_path="src/client/MiningInput.client.luau",
            code=client_source,
        ),
    ]
    for module in modules:
        target = root / module.file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(module.code, encoding="utf-8")
    return RobloxProposal(
        game_title="Mining", requested_prompt="Mine ore",
        description="", modules=modules,
        game_design={"dynamic_design": {
            "remotes": {}, "module_remotes": {},
            "source_reuse": "none_unless_validated",
        }},
    )


def _checks(plan, root):
    return {x["id"]: x["passed"] for x in
            acceptance_obligations(plan, root)["checks"]}


def test_positive_exact_on_disk_code_snapshot(tmp_path):
    plan = plan_with_source(tmp_path)
    checks = _checks(plan, tmp_path)
    assert checks["dynamic.source.Mining"]
    assert checks["dynamic.source.MiningInput"]
    assert checks["dynamic.realm.Mining"]
    assert checks["dynamic.realm.MiningInput"]


def test_audited_memory_cannot_hide_different_disk_source(tmp_path):
    plan = plan_with_source(tmp_path)
    target = tmp_path / "src/server/Mining.luau"
    target.write_text(target.read_text(encoding="utf-8") +
                      "local Players = game:GetService('Players')\n"
                      "print(Players.LocalPlayer)\n", encoding="utf-8")
    checks = _checks(plan, tmp_path)
    assert checks["dynamic.source.Mining"] is False
    assert checks["dynamic.realm.Mining"] is False


def test_wrong_realm_in_source_is_rejected_even_if_snapshot_matches(tmp_path):
    plan = plan_with_source(tmp_path)
    plan.modules[0].code += "print(game.Players.LocalPlayer)\n"
    (tmp_path / plan.modules[0].file_path).write_text(
        plan.modules[0].code, encoding="utf-8")
    plan.modules[1].code += "local d = game:GetService('DataStoreService')\n"
    (tmp_path / plan.modules[1].file_path).write_text(
        plan.modules[1].code, encoding="utf-8")
    checks = _checks(plan, tmp_path)
    assert checks["dynamic.source.Mining"]
    assert checks["dynamic.source.MiningInput"]
    assert not checks["dynamic.realm.Mining"]
    assert not checks["dynamic.realm.MiningInput"]


def test_comments_and_quoted_wrong_realm_symbols_do_not_fail(tmp_path):
    plan = plan_with_source(tmp_path)
    plan.modules[0].code += (
        '-- game.Players.LocalPlayer\nprint("InvokeServer")\n'
    )
    plan.modules[1].code += (
        '-- game:GetService("DataStoreService")\n'
        'print("OnServerEvent")\n'
    )
    for module in plan.modules:
        (tmp_path / module.file_path).write_text(module.code, encoding="utf-8")
    checks = _checks(plan, tmp_path)
    assert checks["dynamic.realm.Mining"]
    assert checks["dynamic.realm.MiningInput"]
