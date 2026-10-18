"""E2E source contract regression: parsing a file does not validate its imports.

Tests exercise real production interface audit and its quality-gate wiring,
not a model-graded claim of "gameplay implemented".
"""
from __future__ import annotations

from roblox_mod_ai.server_interface_audit import inspect_dynamic_server_interfaces
from roblox_mod_ai.dynamic_repair import repair_static_failures
from types import SimpleNamespace
from roblox_mod_ai.quality_gates import acceptance_obligations
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def _module(module_id: str, name: str, source: str, kind="server_module"):
    return RobloxModuleSpec(
        module_id=module_id, name=name, kind=kind,
        roblox_service="ServerScriptService",
        file_path="src/server/" + name + ".luau",
        description="Provides the real server action API to the rest of this game.",
        code=source,
    )


def _plan():
    economy = _module("dyn_credits", "EconomyLedger",
        "--!strict\nlocal EconomyLedger = {}\n"
        "function EconomyLedger.Grant(player, amount)\n"
        "    return amount > 0\nend\n"
        "function EconomyLedger.GetBalance(player)\n"
        "    return 10\nend\nreturn EconomyLedger\n",
        kind="shared_module")
    mining = _module("dyn_mining", "MiningSystem",
        "--!strict\nlocal MiningSystem = {}\n"
        "function MiningSystem.start(services)\n"
        "    services.EconomyLedger.Grant(nil, 10)\n"
        "end\nreturn MiningSystem\n")
    return RobloxProposal(
        requested_prompt="Mine ore for currency",
        game_title="MiningGame", description="",
        game_design={"dynamic_design": {
            "remotes": {}, "module_remotes": {}, "world_objects": [],
            "source_reuse": "none_unless_validated", "acceptance": {},
        }},
        modules=[economy, mining],
    )


def test_cross_file_e2e_accepts_real_exported_methods():
    proposal = _plan()
    result = inspect_dynamic_server_interfaces(proposal)
    assert result["passed"], result
    assert any(check["id"] == "service.call.MiningSystem.EconomyLedger.Grant"
               and check["passed"] for check in result["checks"])


def test_real_invalid_module_method_is_detected_in_acceptance(tmp_path):
    proposal = _plan()
    mining = proposal.modules[1]
    mining.code = mining.code.replace("EconomyLedger.Grant(", "EconomyLedger.FakeGrant(")
    report = inspect_dynamic_server_interfaces(proposal)
    assert not report["passed"]
    assert any(check["id"] == "service.call.MiningSystem.EconomyLedger.FakeGrant"
               and not check["passed"] for check in report["checks"])
    # The same check MUST run in the actual production acceptance path,
    # not only in a standalone helper omitted from E2E.
    production = acceptance_obligations(proposal, tmp_path)
    assert not production["passed"]
    assert any(check["id"] == "service.call.MiningSystem.EconomyLedger.FakeGrant"
               and not check["passed"] for check in production["checks"])


def test_missing_or_nonexported_service_is_not_silently_accepted():
    p = _plan()
    p.modules[1].code = p.modules[1].code.replace(
        "services.EconomyLedger.Grant(", "services.FantasyLedger.Grant(")
    assert not inspect_dynamic_server_interfaces(p)["passed"]
    p = _plan()
    p.modules[0].code = p.modules[0].code.replace(
        "return EconomyLedger", "return WrongLedger")
    issues = inspect_dynamic_server_interfaces(p)
    assert not issues["passed"]
    assert any(c["id"] == "service.export.EconomyLedger"
               and not c["passed"] for c in issues["checks"])


def test_dynamically_normalized_script_still_enforces_bootstrap_api():
    p = _plan()
    p.modules[1].code = "--!strict\nlocal MiningSystem = {}\nreturn MiningSystem\n"
    report = inspect_dynamic_server_interfaces(p)
    assert any(c["id"] == "service.start.MiningSystem" and not c["passed"]
               for c in report["checks"])


def test_broken_cross_service_call_repairs_owning_caller_in_real_loop(
        monkeypatch, tmp_path):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    p = _plan()
    mining = p.modules[1]
    mining.code = mining.code.replace("EconomyLedger.Grant(", "EconomyLedger.FakeGrant(")
    for m in p.modules:
        path = tmp_path / m.file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(m.code, encoding="utf-8")
    audit = inspect_dynamic_server_interfaces(p)
    assert not audit["passed"]
    model_calls = []

    class RepairRouter:
        def complete(self, prompt, **kwargs):
            model_calls.append(prompt)
            assert "service.call.MiningSystem.EconomyLedger.FakeGrant" in prompt
            assert "EconomyLedger.FakeGrant" in prompt
            return ("--!strict\\n"
                    "local MiningSystem = {}\\n"
                    "function MiningSystem.start(services)\\n"
                    "    services.EconomyLedger.Grant(nil, 10)\\n"
                    "end\\nreturn MiningSystem\\n")

    analysis = SimpleNamespace(passed=True, diagnostics=[])
    def recheck():
        actual = inspect_dynamic_server_interfaces(p)
        return analysis, actual

    final_analysis, final_acceptance, recovered = repair_static_failures(
        p, tmp_path, analysis, audit, RepairRouter(), recheck=recheck,
        max_rounds=2,
    )
    assert recovered and final_analysis.passed
    assert final_acceptance["passed"]
    assert len(model_calls) == 1
    assert "FakeGrant" not in (tmp_path / mining.file_path).read_text(encoding="utf-8")
    assert "EconomyLedger.Grant" in mining.code
