"""Real Open Cloud contract and fail-closed release tests (no network calls)."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from roblox_mod_ai.cloud_engine_suite import (
    engine_contract_checks, make_engine_suite_script,
)
from roblox_mod_ai.runtime_verification import make_smoke_script
from roblox_mod_ai.verified_release import run_verified_release


def plan():
    from roblox_mod_ai.spec import RobloxProposal, RobloxModuleSpec, ModuleKind, RobloxService
    game = {
        "dynamic_design": {
            "remotes": {"CarryRequest": "RemoteFunction", "MineRequest": "RemoteEvent"},
            "world_objects": [
                {"name": "MinableDeposit", "class": "Part", "position": [8, 3, 4], "size": [5, 4, 5]},
                {"name": "DestinationPad", "class": "Part", "position": [10, 900, 4], "size": [20, 2, 20]},
            ],
        },
        "pre_design_research": {"ledger": {"requirements": [
            {"id": "req-001", "statement": "Gather and transport objects"},
        ]}},
    }
    modules = [
        RobloxModuleSpec(module_id="dyn_a", name="TransferServer",
                         kind=ModuleKind.SERVER_MODULE, file_path="src/server/TransferServer.luau",
                         roblox_service=RobloxService.SERVER_SCRIPT_SERVICE),
        RobloxModuleSpec(module_id="dyn_b", name="TransferClient",
                         kind=ModuleKind.CLIENT_SCRIPT, file_path="src/client/TransferClient.client.luau",
                         roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS),
    ]
    return RobloxProposal(requested_prompt="Gather and transport objects",
                          game_title="AnyWorld", description="", game_design=game,
                          modules=modules)


def test_server_engine_checks_cover_all_actual_modules_remotes_and_world():
    p = plan()
    checks = engine_contract_checks(p)
    assert len(checks) == 6
    assert {key for key, _ in checks} == {
        "module:src/server/TransferServer.luau",
        "module:src/client/TransferClient.client.luau",
        "remote:CarryRequest", "remote:MineRequest",
        "world:MinableDeposit", "world:DestinationPad",
    }
    script = make_engine_suite_script(p)
    for obj in ["TransferServer", "TransferClient", "CarryRequest",
                "MineRequest", "MinableDeposit", "DestinationPad"]:
        assert obj in script
    assert 'o:IsA("Part")' in script
    assert "RMM_ENGINE_ASSERTIONS_FAILED" in script
    assert "return true" == script.strip().splitlines()[-1]
    assert "StudioTestService" not in script


def test_actual_smoke_combines_runtime_contract_and_separate_datastore_test():
    s = make_smoke_script(plan())
    assert s.count("--!strict") == 1
    assert s.count("return true") == 1
    assert "RMM_ENGINE_ASSERTIONS_FAILED" in s
    assert "RMM_VerificationOnly" in s
    assert "store:SetAsync(key, {value=17})" in s
    assert s.rstrip().endswith("return true")
    assert "do\n" in s


@pytest.mark.parametrize("bad", [
    "", "x" * 130, "Bad\\nName", "Bad\\x00Name",
])
def test_control_character_instance_identifiers_rejected(bad):
    p = plan()
    p.game_design["dynamic_design"]["world_objects"][0]["name"] = bad
    with pytest.raises(ValueError):
        make_engine_suite_script(p)


class FakeSession:
    def __init__(self, folder: Path, proposal):
        self.folder = folder
        self.builds = 0
        self.revisions = 0
        self.reply = SimpleNamespace(ready_to_build=True,
            authored_plan=SimpleNamespace(proposal=proposal))
        (folder / "place.rbxlx").write_text("<roblox/>", encoding="utf-8")

    def build(self, _plan, *, run_name):
        self.builds += 1
        return SimpleNamespace(success=True, project_dir=str(self.folder),
            rbxlx_path=str(self.folder / "place.rbxlx"),
            project_zip_path=str(self.folder / "generated.zip"),
            metadata={})

    def revise(self, feedback):
        self.revisions += 1
        return self.reply


def test_unconfigured_cloud_is_not_falsely_treated_as_build_failure(tmp_path):
    p = plan()
    s = FakeSession(tmp_path, p)
    oracle = SimpleNamespace(run=lambda _p, _place: {
        "passed": False, "executed": False,
        "status": "verification_setup_required",
        "reason": "Missing TEST universe or API key",
    })
    out = run_verified_release(s, s.reply, run_name="sample",
                               max_rebuilds=2, verifier=oracle)
    assert out["verified"] is False
    assert out["final_zip"] == ""
    assert s.builds == 1
    assert s.revisions == 0
    assert Path(out["failure_report"]).is_file()
    with zipfile.ZipFile(out["failure_report"]) as z:
        assert json.loads(z.read("cloud_verification_failure.json"))["verified"] is False


def test_real_engine_failure_no_finish_and_no_unchanged_game_retry(tmp_path):
    p = plan()
    s = FakeSession(tmp_path, p)
    oracle = SimpleNamespace(run=lambda _p, _place: {
        "passed": False, "executed": True,
        "state": "FAILED", "results": None,
        "reason": "Missing Remote CarryRequest",
    })
    out = run_verified_release(s, s.reply, run_name="sample",
                               max_rebuilds=3, verifier=oracle)
    assert out["verified"] is False
    assert out["final_zip"] == ""
    assert s.builds == 2
    assert s.revisions == 1
    assert any(x["status"] == "unchanged_failed_place" for x in out["attempts"])


def test_fake_completion_or_wrong_place_digest_cannot_release(tmp_path):
    p = plan()
    s = FakeSession(tmp_path, p)
    oracle = SimpleNamespace(run=lambda _p, _place: {
        "passed": True, "executed": True, "state": "COMPLETE",
        "results": [True], "place_sha256": "0" * 64,
        "task_path": "universes/1/places/2/versions/3/luau-execution-sessions/x/tasks/y",
    })
    out = run_verified_release(s, s.reply, run_name="sample",
                               max_rebuilds=0, verifier=oracle)
    assert out["verified"] is False
    assert out["final_zip"] == ""


def test_legal_unicode_spaces_and_punctuation_are_quoted_as_data_not_luau_code():
    p = plan()
    name = '광물 채굴" ); game:Destroy(); --'
    p.game_design["dynamic_design"]["world_objects"][0]["name"] = name
    script = make_engine_suite_script(p)
    assert json.dumps(name, ensure_ascii=False) in script
    assert 'workspace:FindFirstChild("광물 채굴\\" ); game:Destroy(); --")' in script
