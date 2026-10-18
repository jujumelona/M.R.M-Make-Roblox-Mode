"""Real MiMo EconomyLedger error patterns must fail before game packaging.

These are actual malformed API *names* observed in previous user logs.
Not a substitute for comprehensive Luau API types, Studio or model inference.
"""
from __future__ import annotations

import pytest

from roblox_mod_ai.luau_api_sanity import invalid_luau_apis
from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
from roblox_mod_ai.quality_gates import acceptance_obligations
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


@pytest.mark.parametrize("invalid", [
    "return type.isnumber(amount)",
    "return type.isinteger(amount)",
    "return type.isstring(name)",
    "local t = os.now()",
    "local services = game:GetServices()",
    "local players = game.GetPlayers()",
    "local players = game:GetPlayers()",
    "local p = game._PlayerService:GetPlayers()",
])
def test_mimo_log_invalid_roblox_api_signatures_are_detected(invalid):
    report = invalid_luau_apis("--!strict\n" + invalid + "\n")
    assert report, invalid


def test_faked_invalid_api_text_in_comments_and_strings_is_not_real_code():
    clean = (
        '--!strict\n-- type.isinteger(x), os.now(), game:GetServices()\n'
        'local docs = "game:GetPlayers() or game._PlayerService"\n'
        "local ok = type(10) == 'number'\n"
        'local now = os.time()\n'
        'print(docs, ok, now)\n'
    )
    assert not invalid_luau_apis(clean)


def test_invalid_api_is_blocked_by_actual_production_gate(tmp_path):
    module = RobloxModuleSpec(
        module_id="dyn_mining", name="MiningServer",
        kind="server_module", roblox_service="ServerScriptService",
        file_path="src/server/MiningServer.luau",
        code="--!strict\nlocal Mine = {}\n"
             "function Mine.start(services)\n"
             "    local fake = os.now()\n"
             "    print(fake)\nend\nreturn Mine\n",
    )
    p = RobloxProposal(
        requested_prompt="mining", game_title="Mine", description="",
        game_design={"dynamic_design": {"source_reuse": "none_unless_validated"}},
        modules=[module],
    )
    path = tmp_path / module.file_path
    path.parent.mkdir(parents=True)
    path.write_text(module.code, encoding="utf-8")
    report = acceptance_obligations(p, tmp_path)
    check = next(x for x in report["checks"]
                 if x["id"] == "dynamic.api.MiningServer")
    assert check["passed"] is False
    assert "os.now" in check["detail"]


def test_model_gets_real_api_failure_diagnostic_for_scoped_retry(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module = RobloxModuleSpec(
        module_id="dyn_mining", name="MiningServer",
        kind="server_script", roblox_service="ServerScriptService",
        file_path="src/server/MiningServer.server.luau",
        description="Server grants earned ore currency on validated mining interactions.",
    )
    p = RobloxProposal(
        requested_prompt="mine nearby ore",
        game_title="Mine", description="",
        game_design={"dynamic_design": {"remotes": {}}},
        modules=[module],
    )
    bad = "--!strict\nlocal Players = game:GetService('Players')\n" + (
        "local stamp = os.now()\nprint(stamp, Players)\n"
    )
    good = "--!strict\nlocal Players = game:GetService('Players')\n" + (
        "local stamp = os.time()\nprint(stamp, Players)\n"
    )
    class Model:
        def __init__(self):
            self.calls = []
        def complete(self, prompt, **kwargs):
            self.calls.append(prompt)
            if len(self.calls) > 1:
                assert "os.now does not exist" in prompt
            return bad if len(self.calls) == 1 else good
    m = Model()
    code = RobloxCodeRepairAgent(m).repair(module, p, attempts=2)
    assert "os.time()" in code
    assert len(m.calls) == 2
