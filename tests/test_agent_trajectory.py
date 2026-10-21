"""Regression: a failed MRM run must return actionable artifacts, not die silently."""
from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from roblox_mod_ai.agent_trajectory import AgentTrajectory
from roblox_mod_ai.api import CompleteRobloxAISession
from roblox_mod_ai.orchestrator import RobloxProductionOrchestrator
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal, RobloxService, ModuleKind


def make_module(module_id, name, path, code=""):
    return RobloxModuleSpec(
        module_id=module_id, name=name, kind=ModuleKind.SERVER_SCRIPT,
        file_path=path, roblox_service=RobloxService.SERVER_SCRIPT_SERVICE,
        code=code,
    )


def test_partial_source_and_trace_survive_generation_failure(tmp_path, monkeypatch):
    orchestrator = RobloxProductionOrchestrator(tmp_path)
    proposal = RobloxProposal(
        requested_prompt="Generate a custom game with trade and mining",
        game_title="SpaceTrial", description="test", game_design={},
        modules=[
            # First module is explicitly authored/test-owned, NOT unsigned
            # dynamic model code imported from an old proposal checkpoint.
            make_module("mod_trade", "TradeService", "src/server/TradeService.server.luau",
                        "--!strict\nprint('Trade service exists')\n"),
            make_module("dyn_mining", "MiningService", "src/server/MiningService.server.luau"),
        ],
    )

    def fail_second(module, plan):
        assert module.name == "MiningService"
        raise ValueError("Model tool reported a syntax error on MiningService")
    monkeypatch.setattr(orchestrator.code_generator, "generate_with_self_correction",
                        fail_second)
    result = orchestrator.execute(proposal, run_name="failed")
    assert not result.success
    root = Path(result.project_dir)
    assert (root / "src/server/TradeService.server.luau").is_file()
    assert not (root / "src/server/MiningService.server.luau").exists()
    partial = json.loads((root / "proposal_partial.json").read_text(encoding="utf-8"))
    assert partial["modules"][0]["code"].startswith("--!strict")
    trace = json.loads((root / "agent_trajectory.json").read_text(encoding="utf-8"))
    assert any(x["phase"] == "generation" and not x["passed"]
               and "MiningService" in str(x["observation"]) for x in trace["steps"])
    failure_zip = Path(result.metadata["failure_logs_zip"])
    assert failure_zip.is_file()
    with zipfile.ZipFile(failure_zip) as bundle:
        names = bundle.namelist()
        assert "agent_failure_report.json" in names
        assert "agent_trajectory.json" in names
        assert "src/server/TradeService.server.luau" in names
        assert "proposal_partial.json" in names
        report = json.loads(bundle.read("agent_failure_report.json"))
        assert not report["success"]
        assert "MiningService" in report["error"]


def test_incomplete_plan_exports_diagnostics_and_original_request(tmp_path, monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_DECOMPOSITION", "0")
    monkeypatch.setenv("RMM_ENABLE_MODEL_QUERY_EXPANSION", "0")
    monkeypatch.setenv("RMM_ENABLE_DYNAMIC_DESIGN", "0")
    session = CompleteRobloxAISession(output_root=tmp_path)
    prompt = "광물 채굴하고 거래해서 우주선을 만들어 다른 행성으로 간다"
    reply = session.plan(prompt)
    assert not reply.ready_to_build
    bundle = tmp_path / "plan_failure_logs.zip"
    assert bundle.is_file()
    with zipfile.ZipFile(bundle) as reader:
        report = json.loads(reader.read("plan_failure_report.json"))
        assert report["requested_prompt"] == prompt
        assert report["unimplemented_facets"]
        assert "proposal.json" in reader.namelist()


def test_trajectory_keeps_all_observations_and_failure_zip(tmp_path):
    log = AgentTrajectory(tmp_path / "run")
    log.record("lint", "selene", {"stderr": "line 3: unexpected token"},
               passed=False, attempt=1)
    log.record("repair", "rewrite src/server/Service.server.luau", {"changed": True},
               passed=True, attempt=1)
    failure = log.failure_bundle("real verifier unavailable", tool_results={
        "selene": {"executed": True, "success": False, "stderr": "line 3"}
    })
    assert failure.exists()
    saved = json.loads(log.path.read_text(encoding="utf-8"))
    assert [step["passed"] for step in saved["steps"]] == [False, True]



def test_static_repair_routes_exact_error_to_model_and_revalidates(tmp_path, monkeypatch):
    """Actual failed acceptance check is supplied to the agent, not discarded."""
    from types import SimpleNamespace
    from roblox_mod_ai import dynamic_repair

    module = make_module(
        "dyn_mining", "MiningService", "src/server/MiningService.server.luau",
        "--!strict\nprint('not mining')\n")
    proposal = RobloxProposal(
        requested_prompt="Mine planetary ore", game_title="Test",
        description="test", game_design={"dynamic_design": {"remotes": {}}},
        modules=[module])
    dest = tmp_path / module.file_path
    dest.parent.mkdir(parents=True)
    dest.write_text(module.code, encoding="utf-8")
    diagnostics = SimpleNamespace(passed=True, diagnostics=[], error_count=0)
    failed = {"passed": False, "checks": [
        {"id": "dynamic.code.MiningService", "passed": False,
         "detail": "Missing validated ore depletion and reward logic"}
    ]}
    seen = []

    class FakeRepairAgent:
        def __init__(self, router):
            self.router = router
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            seen.append((module.name, diagnostics, existing_code))
            return "--!strict\nlocal mineral = 1\nprint('mining rewards', mineral)\n"

    monkeypatch.setattr(dynamic_repair, "RobloxCodeRepairAgent", FakeRepairAgent)

    def recheck():
        output = dest.read_text(encoding="utf-8")
        passed = "mining rewards" in output
        return diagnostics, {"passed": passed, "checks": [
            {"id": "dynamic.code.MiningService", "passed": passed,
             "detail": "Validation of mining logic"}
        ]}

    journal = AgentTrajectory(tmp_path / "journal")
    analysis, acceptance, passed = dynamic_repair.repair_static_failures(
        proposal, tmp_path, diagnostics, failed, object(), recheck,
        trajectory=journal)
    assert passed and acceptance["passed"]
    assert module.code == dest.read_text(encoding="utf-8")
    assert seen and "Missing validated ore" in seen[0][1]
    assert any(x["action"] == "revalidate source and acceptance" and x["passed"]
               for x in journal.events)


def test_static_repair_rolls_back_when_acceptance_regresses(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from roblox_mod_ai import dynamic_repair

    original = "--!strict\nprint('existing valid mechanic')\n"
    module = make_module("dyn_module", "SpaceService",
                         "src/server/SpaceService.server.luau", original)
    proposal = RobloxProposal(
        requested_prompt="Build a spaceship", game_title="Test", description="",
        game_design={"dynamic_design": {}}, modules=[module])
    dest = tmp_path / module.file_path
    dest.parent.mkdir(parents=True)
    dest.write_text(original, encoding="utf-8")
    analyzer = SimpleNamespace(passed=True, diagnostics=[], error_count=0)
    failed = {"passed": False, "checks": [
        {"id": "dynamic.code.SpaceService", "passed": False, "detail": "Missing new behavior"},
        {"id": "existing.passed", "passed": True, "detail": "Do not regress"}
    ]}

    class DestructiveAgent:
        def __init__(self, router): pass
        def repair(self, *args, **kwargs):
            return "--!strict\nprint('regressive replacement')\n"

    monkeypatch.setattr(dynamic_repair, "RobloxCodeRepairAgent", DestructiveAgent)

    def recheck():
        if "regressive" in dest.read_text(encoding="utf-8"):
            return analyzer, {"passed": False, "checks": [
                {"id": "dynamic.code.SpaceService", "passed": True, "detail": "Resolved"},
                {"id": "existing.passed", "passed": False, "detail": "Regressed"}
            ]}
        return analyzer, failed

    _, _, success = dynamic_repair.repair_static_failures(
        proposal, tmp_path, analyzer, failed, object(), recheck)
    assert not success
    assert module.code == original
    assert dest.read_text(encoding="utf-8") == original



def test_generation_failure_is_fed_to_model_and_work_continues(tmp_path, monkeypatch):
    """A failed Luau generation is an observation, not an immediate run abort."""
    from roblox_mod_ai import orchestrator as pipeline
    workspace = RobloxProductionOrchestrator(tmp_path)
    proposal = RobloxProposal(
        requested_prompt="Build a space ship", game_title="RepairGeneration",
        description="test", game_design={},
        modules=[make_module("dyn_ship", "ShipAssembly",
                             "src/server/ShipAssembly.server.luau")],
    )
    monkeypatch.setattr(workspace.code_generator, "generate_with_self_correction",
                        lambda *args: (_ for _ in ()).throw(
                            ValueError("Luau syntax error: expected end on line 17")))
    received = []
    class FakeModelRepair:
        def __init__(self, router): pass
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            received.append((module.file_path, diagnostics, existing_code))
            return "--!strict\nlocal function assemble(player)\n    return player ~= nil\nend\nprint(assemble)\n"
    monkeypatch.setattr(pipeline, "RobloxCodeRepairAgent", FakeModelRepair)
    result = workspace.execute(proposal, "fixed", source_only=True)
    assert not result.success  # Source-only still cannot claim engine verification.
    assert received and "expected end on line 17" in received[0][1]
    actual = Path(result.project_dir) / proposal.modules[0].file_path
    assert actual.is_file()
    trace = json.loads((Path(result.project_dir) / "agent_trajectory.json").read_text())
    assert any(step["action"].startswith("recover") and step["passed"]
               for step in trace["steps"])
    assert all(stage["stage"] != "generate_code" or stage["success"]
               for stage in result.work_receipt.to_dict()["stages"]
               if isinstance(stage, dict))


def test_unlocated_tool_error_uses_model_selected_real_file(tmp_path, monkeypatch):
    from roblox_mod_ai import dynamic_repair
    module = make_module("dyn_mining", "MiningController",
                         "src/server/MiningController.server.luau",
                         "--!strict\nprint('draft')\n")
    proposal = RobloxProposal(
        requested_prompt="Mine ores", game_title="Space", description="test",
        game_design={}, modules=[module],
    )
    dest = tmp_path / module.file_path
    dest.parent.mkdir(parents=True)
    dest.write_text(module.code)
    calls = []
    class FakeRouter:
        def complete_json(self, prompt, **kwargs):
            calls.append(prompt)
            return {"files": [module.file_path]}
    class FakeAgent:
        def __init__(self, router): pass
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            assert "unexpected token" in diagnostics
            return "--!strict\nlocal miningEnabled = true\nprint(miningEnabled)\n"
    monkeypatch.setattr(dynamic_repair, "RobloxCodeRepairAgent", FakeAgent)
    def retry_tool():
        return {"success": "miningEnabled" in dest.read_text(),
                "executed": True, "stdout": "", "stderr": ""}
    recovered = dynamic_repair.repair_tool_diagnostics(
        proposal, tmp_path, "selene",
        {"success": False, "executed": True,
         "stderr": "stdin:1: unexpected token"},
        retry_tool, None, FakeRouter(),
    )
    assert recovered["passed"] and recovered["repaired"] == [module.file_path]
    assert "model diagnostic triage" in str(recovered["history"])
    assert calls
    assert retry_tool()["success"]


def test_model_triage_rejects_invented_file_and_wrong_type():
    from roblox_mod_ai.dynamic_repair import model_triage_modules
    module = make_module("dyn_mining", "MiningServer",
                         "src/server/MiningServer.server.luau", "--!strict\nprint(1)\n")
    proposal = RobloxProposal(
        requested_prompt="Mine ore", game_title="Test", description="",
        game_design={}, modules=[module],
    )
    class Model:
        def __init__(self, files): self.files = files
        def complete_json(self, *args, **kwargs): return {"files": self.files}
    assert model_triage_modules(proposal, "missing receiver", Model(["../../outside"])) == []
    assert model_triage_modules(proposal, "missing receiver",
                               Model([module.file_path] * 2)) == []
    assert model_triage_modules(proposal, "missing receiver",
                               Model([module.file_path])) == [module]



def test_exhausted_codegen_keeps_exact_failed_code_and_analyzer_feedback(tmp_path, monkeypatch):
    from roblox_mod_ai import orchestrator as pipeline
    from roblox_mod_ai.agent_loop import LuauGenerationError
    workspace = RobloxProductionOrchestrator(tmp_path)
    proposal = RobloxProposal(
        requested_prompt="Spaceship with weapons", game_title="ExactError",
        description="test", game_design={},
        modules=[make_module("dyn_weapons", "WeaponsServer",
                             "src/server/WeaponsServer.server.luau")],
    )
    failed_code = "--!strict\nlocal weapon = nil -- TODO fix actual weapon damage code\n"
    monkeypatch.setattr(workspace.code_generator, "generate_with_self_correction",
                        lambda *a: (_ for _ in ()).throw(LuauGenerationError(
                            "WeaponsServer", failed_code,
                            ["line 2: unexpected token near weapon", "No validated damage handler"])))
    seen = []
    class Repair:
        def __init__(self, router): pass
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            seen.append((existing_code, diagnostics))
            return "--!strict\nlocal function validDamage(player)\n    return player ~= nil\nend\nprint(validDamage)\n"
    monkeypatch.setattr(pipeline, "RobloxCodeRepairAgent", Repair)
    result = workspace.execute(proposal, "repair", source_only=True)
    project = Path(result.project_dir)
    broken = project / "failed_candidates/src/server/WeaponsServer.server.luau"
    assert broken.read_text(encoding="utf-8") == failed_code
    assert seen and seen[0][0] == failed_code
    assert "unexpected token near weapon" in seen[0][1]
    assert "No validated damage handler" in seen[0][1]
    assert "validDamage" in (project / proposal.modules[0].file_path).read_text()
    with zipfile.ZipFile(result.metadata["failure_logs_zip"]) as zipped:
        assert "failed_candidates/src/server/WeaponsServer.server.luau" in zipped.namelist()


def test_codegen_agent_retains_last_model_source_on_exhaustion(monkeypatch):
    from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent, LuauGenerationError
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Stub:
        def complete(self, *args, **kwargs):
            return "--!strict\n-- TODO: ship damage handler\n"
    module = make_module("dyn_damage", "ShipDamage",
                         "src/server/ShipDamage.server.luau")
    proposal = RobloxProposal(
        requested_prompt="Ship damage", game_title="Test", description="",
        game_design={"pre_design_research": {"evidence": []}},
        modules=[module],
    )
    with pytest.raises(LuauGenerationError) as issue:
        RobloxCodeRepairAgent(router=Stub()).repair(module, proposal, attempts=2)
    assert "TODO" in issue.value.candidate
    assert "Placeholder code is prohibited" in issue.value.diagnostics



def test_missing_client_sender_is_repaired_not_just_existing_server(tmp_path, monkeypatch):
    """Concrete previous defect: a server references Remote but client has no sender."""
    from types import SimpleNamespace
    from roblox_mod_ai import dynamic_repair
    server = make_module(
        "dyn_ship_server", "ShipServer", "src/server/ShipServer.server.luau",
        '--!strict\nlocal remote = game.ReplicatedStorage.Remotes:WaitForChild("LaunchShip")\n'
        'remote.OnServerEvent:Connect(function(player) print(player) end)\n',
    )
    client = RobloxModuleSpec(
        module_id="dyn_ship_client", name="ShipController",
        kind=ModuleKind.CLIENT_SCRIPT,
        roblox_service=RobloxService.STARTER_PLAYER_SCRIPTS,
        file_path="src/client/ShipController.client.luau",
        code="--!strict\nprint('launch UI created')\n",
    )
    proposal = RobloxProposal(
        requested_prompt="Launch assembled spaceship", game_title="WiringRepair",
        description="test",
        game_design={"dynamic_design": {"remotes": {"LaunchShip": "RemoteEvent"}}},
        modules=[server, client],
    )
    for m in proposal.modules:
        p = tmp_path / m.file_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(m.code, encoding="utf-8")
    diagnostic = SimpleNamespace(passed=True, diagnostics=[], error_count=0)
    def recheck():
        from roblox_mod_ai.dynamic_wiring import inspect_dynamic_remote_wiring
        checks = inspect_dynamic_remote_wiring(proposal)["checks"]
        return diagnostic, {"passed": all(x["passed"] for x in checks),
                            "checks": checks}
    before_analysis, failed = recheck()
    assert not failed["passed"]
    repair_calls = []
    class Router:
        def complete_json(self, prompt, **kwargs):
            assert "LaunchShip" in prompt
            return {"files": [client.file_path]}
    class Repair:
        def __init__(self, router): pass
        def repair(self, module, proposal, existing_code, diagnostics, attempts):
            repair_calls.append(module.name)
            assert module == client
            assert "wiring.LaunchShip" in diagnostics
            return ('--!strict\nlocal remote = game.ReplicatedStorage.Remotes:'
                    'WaitForChild("LaunchShip")\nremote:FireServer()\n')
    monkeypatch.setattr(dynamic_repair, "RobloxCodeRepairAgent", Repair)
    analysis, acceptance, recovered = dynamic_repair.repair_static_failures(
        proposal, tmp_path, before_analysis, failed,
        Router(), recheck, max_rounds=2)
    assert recovered and acceptance["passed"]
    assert repair_calls == ["ShipController"]
    assert server.code == (tmp_path / server.file_path).read_text(encoding="utf-8")
    assert "FireServer" in client.code



def test_failed_33_module_run_resumes_completed_sources_without_regenerating(tmp_path, monkeypatch):
    """Previous user's 24-minute failed run generated two valid files then stopped."""
    import copy
    orchestrator = RobloxProductionOrchestrator(tmp_path)
    proposal = RobloxProposal(
        requested_prompt="Mine, trade and assemble a spaceship",
        game_title="Recovery", description="test", game_design={},
        modules=[
            make_module("dyn_money", "EconomyLedger",
                        "src/server/EconomyLedger.server.luau"),
            make_module("dyn_trade", "TradeServer",
                        "src/server/TradeServer.server.luau"),
            make_module("dyn_assembly", "AssemblyServer",
                        "src/server/AssemblyServer.server.luau"),
        ],
    )
    clean_plan = copy.deepcopy(proposal.to_dict())
    calls = []
    phase = [1]
    def generator(module, plan):
        calls.append((phase[0], module.name))
        if phase[0] == 1 and module.name == "AssemblyServer":
            raise RuntimeError("simulated model generated no visible code")
        return ("--!strict\nlocal function perform(): number\n"
                "    return 42\nend\nprint(perform())\n")
    monkeypatch.setattr(orchestrator.code_generator,
                        "generate_with_self_correction", generator)
    first = orchestrator.execute(proposal, "resume", source_only=True)
    root = Path(first.project_dir)
    assert not first.success
    checkpoint = json.loads((root / "generation_checkpoint.json").read_text())
    assert set(checkpoint["modules"]) == {
        "src/server/EconomyLedger.server.luau",
        "src/server/TradeServer.server.luau",
    }
    phase[0] = 2
    # Rebuild from the ORIGINAL empty-code proposal, not the mutated first.
    second = orchestrator.execute(
        RobloxProposal.from_dict(clean_plan), "resume", source_only=True)
    assert not second.success  # still source-only, not Roblox engine verified
    assert calls.count((1, "EconomyLedger")) == 1
    assert calls.count((1, "TradeServer")) == 1
    assert (2, "EconomyLedger") not in calls
    assert (2, "TradeServer") not in calls
    assert (2, "AssemblyServer") in calls
    trail = json.loads((root / "agent_trajectory.json").read_text())
    assert sum(x["action"].startswith("resume ") for x in trail["steps"]) == 2


def test_codegen_resume_rejects_changed_contract_and_corrupted_file(tmp_path, monkeypatch):
    from copy import deepcopy
    orchestrator = RobloxProductionOrchestrator(tmp_path)
    proposal = RobloxProposal(
        requested_prompt="Harvest one space ore node",
        game_title="CheckpointGuard", description="test", game_design={},
        modules=[make_module("dyn_ore", "OreHarvest",
                             "src/server/OreHarvest.server.luau")],
    )
    clean = deepcopy(proposal.to_dict())
    calls = []
    def generate(module, proposal):
        calls.append(module.description)
        return "--!strict\nlocal result = 12\nprint(result)\n"
    monkeypatch.setattr(orchestrator.code_generator,
                        "generate_with_self_correction", generate)
    first = orchestrator.execute(proposal, "integrity", source_only=True)
    root = Path(first.project_dir)
    second = orchestrator.execute(RobloxProposal.from_dict(clean), "integrity",
                                  source_only=True)
    assert len(calls) == 1, "Unchanged verified source must be resumed"
    source_path = root / clean["modules"][0]["file_path"]
    source_path.write_text("--!strict\nprint('tampered')\n")
    third = orchestrator.execute(RobloxProposal.from_dict(clean), "integrity",
                                 source_only=True)
    assert len(calls) == 2, "Changed source hash must never be resumed"
    altered = RobloxProposal.from_dict(clean)
    altered.modules[0].description = "Mine a newly added toxic mineral with player protection"
    fourth = orchestrator.execute(altered, "integrity", source_only=True)
    assert len(calls) == 3, "Changed authored behavior invalidates checkpoint"
