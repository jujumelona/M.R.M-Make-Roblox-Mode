"""Exercise the uploaded response corpus through the actual coding agent."""
import json
from pathlib import Path

import pytest

from roblox_mod_ai.agent_loop import LuauGenerationError, RobloxCodeRepairAgent
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def _plan():
    module = RobloxModuleSpec(
        module_id="dyn_mode", name="SpaceModeServer", kind="server_module",
        roblox_service="ServerScriptService", file_path="src/server/SpaceModeServer.luau",
        description="Set the server-owned mode active and initialize the launch station attribute.")
    plan = RobloxProposal(
        requested_prompt="우주 모드의 발사 구역을 활성화한다", game_title="Mode", description="",
        game_design={"pre_design_research": {"ledger": {"requirements": [
            {"id": "r-mode", "statement": "발사 구역을 활성화한다"}]}},
                     "dynamic_design": {"module_requirements": {module.module_id: ["r-mode"]},
                         "world_objects": [{"name": "LaunchStation", "class": "Part",
                                            "position": [0, 2, 0], "size": [4, 4, 4]}]}},
        modules=[module])
    return module, plan


@pytest.mark.parametrize("code", [
    "local Service = {}\nfunction Service.start(services) end\nreturn Service",
    "local SpaceModeService = {}\nfunction Service.start(services)\nworkspace:SetAttribute('ModeActive', true)\nend\nreturn SpaceModeService",
    "local Service = {}\nfunction Service.start(self, services)\nself.services = services\nend\nreturn Service",
    "local Service = {}\nfunction Service:start(services)\nself.services = services\nend\nreturn Service",
])
def test_incomplete_or_wrong_bootstrap_contract_does_not_pass(monkeypatch, code):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Model:
        def complete(self, *args, **kwargs): return code
    module, plan = _plan()
    with pytest.raises(LuauGenerationError):
        RobloxCodeRepairAgent(Model()).repair(module, plan, attempts=1)


def test_syntax_retry_keeps_world_behavior_and_start_scaffold(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, plan = _plan()
    queries = []
    class Model:
        def complete(self, prompt, **kwargs):
            queries.append(prompt)
            if len(queries) == 1:
                return "--!strict\nlocal Service = {}\nfunction Service.start(services)\nlocal x = (number)[]\n"
            return ("--!strict\nlocal Service = {}\nfunction Service.start(services)\n"
                    "local station = workspace:WaitForChild('LaunchStation')\n"
                    "station:SetAttribute('ModeActive', true)\nend\nreturn Service\n")
    RobloxCodeRepairAgent(Model()).repair(module, plan, attempts=2)
    assert len(queries) == 2
    for prompt in queries:
        assert "LaunchStation" in prompt
        assert "local Service = {}" in prompt
        assert "return Service" in prompt
        assert "발사 구역을 활성화한다" in prompt


def test_retry_uses_parser_line_and_bounded_original_source_evidence(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, plan = _plan()
    queries = []
    class Model:
        def complete(self, prompt, **kwargs):
            queries.append(prompt)
            if len(queries) == 1:
                return "--!strict\nlocal Service = {}\nfunction Service.start(services)\nlocal x = (number)[]\n"
            return ("--!strict\nlocal Service = {}\nfunction Service.start(services)\n"
                    "workspace:SetAttribute('ModeActive', true)\nend\nreturn Service\n")
    RobloxCodeRepairAgent(Model()).repair(module, plan, attempts=2)
    assert "Failed source excerpt" in queries[1]
    assert "local x = (number)[]" in queries[1]


_CORPUS = json.loads((Path(__file__).parent / "fixtures/space_mode_codegen_failures.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", _CORPUS["initial_generation_attempts"] + _CORPUS["recovery_attempts"])
def test_each_attached_failed_response_remains_rejected(monkeypatch, sample):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Model:
        def complete(self, *args, **kwargs): return sample["candidate"]
    module, plan = _plan()
    with pytest.raises(LuauGenerationError):
        RobloxCodeRepairAgent(Model()).repair(module, plan, attempts=1)


def test_coder_only_receives_world_objects_owned_by_this_module(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    module, plan = _plan()
    design = plan.game_design["dynamic_design"]
    design["world_objects"].append({"name": "UnrelatedAlien", "class": "Part",
                                    "position": [20, 2, 0], "size": [4, 4, 4]})
    design["module_world_objects"] = {module.module_id: ["LaunchStation"]}
    queries = []
    class Model:
        def complete(self, prompt, **kwargs):
            queries.append(prompt)
            return ("local Service = {}\nfunction Service.start(services)\n"
                    "workspace:WaitForChild('LaunchStation'):SetAttribute('ModeActive', true)\n"
                    "end\nreturn Service")
    RobloxCodeRepairAgent(Model()).repair(module, plan, attempts=1)
    assert "LaunchStation" in queries[0]
    assert "UnrelatedAlien" not in queries[0]
