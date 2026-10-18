"""Regression for the uploaded EconomyLedger failure.

A local MiMo response stopped normally (finish_reason='stop') while returning
garbled Luau. The old analyzer only counted Lua keywords and did not give the
repair model a real compiler/parser location. Mock ONLY the external StyLua
binary, leaving MRM's actual analyzer and coding agent in the test.
"""
import os
import subprocess

import pytest

from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent
from roblox_mod_ai.luau_analyzer import LuauStaticAnalyzer
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


BAD_SOURCE = """--!strict
local Ledger = {}
function validateCredit(player): void? do local balance :: number? invalid syntax
state[player.UserId].balance += credit
end
"""


def _fake_stylua(monkeypatch):
    from roblox_mod_ai import luau_analyzer
    real_which = luau_analyzer.shutil.which
    monkeypatch.setattr(luau_analyzer.shutil, "which",
                        lambda name: "/mock/stylua" if name == "stylua"
                        else real_which(name))
    observations = []

    def parser(argv, *, input, text, capture_output, timeout, check):
        observations.append((argv, input))
        assert argv[1:3] == ["--syntax", "luau"]
        assert argv[-1] == "-"
        assert input.startswith("--!strict")
        if "function validateCredit(player): void?" in input:
            return subprocess.CompletedProcess(
                argv, 1, "",
                "error: invalid Luau function declaration at line 3, column 33"
            )
        return subprocess.CompletedProcess(argv, 0, "--!strict\n", "")
    monkeypatch.setattr(luau_analyzer.subprocess, "run", parser)
    return observations


def _plan():
    module = RobloxModuleSpec(
        module_id="dyn_economy", name="EconomyLedger",
        kind="server_script", roblox_service="ServerScriptService",
        file_path="src/server/EconomyLedger.server.luau",
        description="A server authoritative resource and currency ledger "
                    "validating spending and preventing duplicate transactions.",
    )
    proposal = RobloxProposal(
        requested_prompt="Mine resources and trade for money",
        game_title="Space", description="Mining and trading",
        game_design={"pre_design_research": {"evidence": []},
                     "dynamic_design": {"remotes": {"TradeOffer": "RemoteEvent"}}},
        modules=[module],
    )
    return module, proposal


def test_real_parser_reports_exact_error_not_keyword_balance(monkeypatch):
    observed = _fake_stylua(monkeypatch)
    found = LuauStaticAnalyzer().analyze_source(
        BAD_SOURCE, "src/server/EconomyLedger.server.luau")
    problems = [x for x in found if x.severity == "ERROR"]
    assert len(problems) == 1
    assert problems[0].rule == "LUAU_PARSER_SYNTAX"
    assert "line 3, column 33" in problems[0].message
    assert problems[0].line_number == 3
    assert observed and observed[0][1] == BAD_SOURCE


def test_parser_acceptance_ignores_invalid_keyword_count_heuristics(monkeypatch):
    _fake_stylua(monkeypatch)
    code = "--!strict\nlocal message = 'function if for then'\nprint(message)\n"
    errors = [x for x in LuauStaticAnalyzer().analyze_source(code)
              if x.severity == "ERROR"]
    assert errors == []


def test_actual_code_agent_retries_with_real_stylua_observation(monkeypatch):
    _fake_stylua(monkeypatch)
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    queries = []

    class Router:
        def complete(self, prompt, **kwargs):
            queries.append(prompt)
            if len(queries) == 1:
                return BAD_SOURCE
            assert "line 3, column 33" in prompt
            assert "EconomyLedger" in prompt
            return (
                "--!strict\n"
                "local function deposit(balance: number, delta: number): number\n"
                "    return math.max(0, balance + delta)\n"
                "end\nprint(deposit)\n"
            )
    module, proposal = _plan()
    actual = RobloxCodeRepairAgent(router=Router()).repair(
        module, proposal, attempts=3)
    assert "deposit" in actual
    assert len(queries) == 2


def test_missing_real_parser_is_not_silent_success_in_colab(monkeypatch):
    from roblox_mod_ai import luau_analyzer
    monkeypatch.setattr(luau_analyzer.shutil, "which", lambda _: None)
    monkeypatch.setenv("RMM_REQUIRE_REAL_LUAU_PARSER", "1")
    result = LuauStaticAnalyzer().analyze_source("--!strict\nprint('a')\n")
    assert any(x.rule == "LUAU_PARSER_UNAVAILABLE" and x.severity == "ERROR"
               for x in result)



def test_parser_failure_switches_to_structured_output_and_discards_bad_source(monkeypatch):
    """The uploaded failure stopped normally with 752 tokens but invalid Luau."""
    _fake_stylua(monkeypatch)
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    call_modes = []

    class Router:
        last_generation_report = {"finish_reason": "stop"}
        def complete(self, prompt, **kwargs):
            call_modes.append("plain")
            return BAD_SOURCE
        def complete_json(self, prompt, **kwargs):
            call_modes.append("json")
            assert "line 3, column 33" in prompt
            assert "Previous invalid Luau source:" not in prompt
            assert "function validateCredit(player): void?" not in prompt
            return {"luau": "--!strict\n"
                            "local function debit(balance: number, amount: number): number\n"
                            "    return math.max(0, balance - amount)\n"
                            "end\nprint(debit)\n"}
    module, plan = _plan()
    result = RobloxCodeRepairAgent(router=Router()).repair(module, plan)
    assert call_modes == ["plain", "json"]
    assert "function debit" in result



def test_generator_exception_keeps_every_model_attempt_with_source_and_parser_error(monkeypatch):
    from roblox_mod_ai.agent_loop import LuauGenerationError
    _fake_stylua(monkeypatch)
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")

    class Router:
        last_generation_report = {"finish_reason": "stop", "completion_tokens": 752}
        def complete(self, prompt, **kwargs):
            return BAD_SOURCE

    module, proposal = _plan()
    with pytest.raises(LuauGenerationError) as failure:
        RobloxCodeRepairAgent(router=Router()).repair(module, proposal, attempts=2)
    history = failure.value.history
    assert len(history) == 2
    assert [x["attempt"] for x in history] == [1, 2]
    assert all("function validateCredit(player)" in x["candidate"] for x in history)
    assert all(any("line 3, column 33" in d for d in x["diagnostics"])
               for x in history)
    assert history[0]["model_runtime"]["completion_tokens"] == 752


def test_failure_zip_contains_both_original_and_recovery_model_attempts(tmp_path, monkeypatch):
    import json
    import zipfile

    from roblox_mod_ai import orchestrator as pipeline
    from roblox_mod_ai.agent_loop import LuauGenerationError
    from roblox_mod_ai.orchestrator import RobloxProductionOrchestrator

    module, proposal = _plan()
    workspace = RobloxProductionOrchestrator(tmp_path)
    initial = [{"attempt": 1, "mode": "plain_luau",
                "candidate": BAD_SOURCE,
                "diagnostics": ["LUAU_PARSER_SYNTAX at line 3"]}]
    recovery = [{"attempt": 1, "mode": "structured_json",
                 "candidate": BAD_SOURCE + "-- second attempt",
                 "diagnostics": ["LUAU_PARSER_SYNTAX at line 5"]}]

    def fail_generator(*args):
        raise LuauGenerationError(
            "EconomyLedger", BAD_SOURCE, ["parser rejected line 3"], history=initial)

    class StubRepair:
        def __init__(self, router):
            pass
        def repair(self, *args, **kwargs):
            raise LuauGenerationError(
                "EconomyLedger", BAD_SOURCE,
                ["parser rejected line 5"], history=recovery)

    monkeypatch.setattr(workspace.code_generator,
                        "generate_with_self_correction", fail_generator)
    monkeypatch.setattr(pipeline, "RobloxCodeRepairAgent", StubRepair)
    result = workspace.execute(proposal, "failed-recovery", source_only=True)
    assert not result.success
    path = result.project_dir + "/failed_candidates/" + module.file_path + ".attempts.json"
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["initial_generation_attempts"] == initial
    assert data["recovery_attempts"] == recovery
    with zipfile.ZipFile(result.metadata["failure_logs_zip"]) as bundle:
        in_zip = "failed_candidates/" + module.file_path + ".attempts.json"
        assert in_zip in bundle.namelist()
        assert json.loads(bundle.read(in_zip))["recovery_attempts"] == recovery



def test_actual_stylua_range_reports_line_not_column(monkeypatch):
    """Actual binary uses a source range (4:3 to 4:16); old regex returned 3."""
    from roblox_mod_ai import luau_analyzer
    monkeypatch.setattr(luau_analyzer.shutil, "which",
                        lambda name: "/usr/bin/stylua" if name == "stylua" else None)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0], 1, "",
            "error parsing:\n - unexpected token :: (4:3 to 4:16), "
            "expected end to close do block"
        )

    monkeypatch.setattr(luau_analyzer.subprocess, "run", fake_run)
    errors = [x for x in LuauStaticAnalyzer().analyze_source(
        "--!strict\nlocal a = {}\nfunction foo() do\nbad :: statement\n",
        "example.luau") if x.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].rule == "LUAU_PARSER_SYNTAX"
    assert errors[0].line_number == 4
