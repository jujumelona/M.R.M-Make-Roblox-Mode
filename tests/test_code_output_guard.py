"""Regression against actual user's SpaceModeManager 723-line repetition incident."""
import json
import pytest

from roblox_mod_ai.code_output_guard import LiveCodeRepetitionGuard, RepeatedCodeOutput
from roblox_mod_ai.agent_loop import RobloxCodeRepairAgent


def test_actual_723_duplicate_assignments_are_aborted_after_eight_lines():
    exact_source = (
        "--!strict\nlocal SpaceModeManager = {}\n"
        "SpaceModeManager.new = function()\n"
        "    local self = setmetatable({}, SpaceModeManager)\n"
        + "    self.lastColonizeId = nil\n" * 723
    )
    guard = LiveCodeRepetitionGuard()
    count = 0
    with pytest.raises(RepeatedCodeOutput) as error:
        for line in exact_source.splitlines(keepends=True):
            guard.feed(line)
            count += 1
    assert count <= 15, "Should not burn 6000 tokens repeating all 723 lines"
    assert error.value.repeated_line == "self.lastColonizeId = nil"
    assert len(error.value.partial_output) < 1000


def test_streaming_code_with_legitimate_loops_is_not_false_flagged():
    code = """--!strict
local function mine(node, amount)
    if node == nil then
        return false
    end
    for i = 1, amount do
        if i % 3 == 0 then
            node.Value += i
        end
    end
    return true
end
print(mine)
"""
    LiveCodeRepetitionGuard.inspect(code)


def test_actual_streaming_http_closes_early_and_reports_partial_source(monkeypatch):
    from roblox_mod_ai.model_adapters import llama_cpp_adapter
    from roblox_mod_ai.model_adapters.base import GenerationRequest
    source = (
        "--!strict\nlocal manager = {}\n"
        + "self.lastColonizeId = nil\n" * 723
    )
    state = {"yielded": 0, "closed": False, "payload": None}
    class Stream:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): state["closed"] = True
        def iter_lines(self):
            for line in source.splitlines(keepends=True):
                state["yielded"] += 1
                yield "data: " + json.dumps({
                    "choices": [{"delta": {"content": line},
                                 "finish_reason": None}]})
            yield "data: [DONE]"
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stream(self, method, url, json, headers):
            state["payload"] = json
            return Stream()
    monkeypatch.setattr(llama_cpp_adapter.httpx, "Client", Client)
    adapter = llama_cpp_adapter.LlamaCppAdapter(
        base_url="http://127.0.0.1:8910/v1")
    with pytest.raises(RepeatedCodeOutput) as error:
        adapter.generate(GenerationRequest(
            messages=[{"role": "user", "content": "SpaceModeManager"}],
            max_tokens=6000, metadata={"generation_role": "coder"}))
    assert state["yielded"] < 20
    assert state["closed"]
    assert state["payload"]["stream"] is True
    assert state["payload"]["repeat_penalty"] > 1
    assert "lastColonizeId" in error.value.partial_output


def test_coder_aborted_repetition_uses_fresh_plain_source_without_echoing_junk(monkeypatch):
    from roblox_mod_ai.model_adapters.base import ModelBackendError
    from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    bad = "--!strict\n" + ("self.lastColonizeId = nil\n" * 8)
    class Router:
        def __init__(self):
            self.text_calls = 0
            self.json_calls = 0
            self.last_generation_report = {}
        def complete(self, prompt, **kwargs):
            self.text_calls += 1
            if self.text_calls == 1:
                raise RepeatedCodeOutput("self.lastColonizeId = nil", 8, bad)
            assert "Previous invalid Luau source:" not in prompt
            assert "self.lastColonizeId = nil" not in prompt
            return ("--!strict\nlocal function phaseTransition(player, nextPhase)\n"
                    "    if player == nil then return false end\n"
                    "    if nextPhase == 'Space' then return true end\n"
                    "    return false\nend\nprint(phaseTransition)\n")
        def complete_json(self, prompt, **kwargs):
            self.json_calls += 1
            raise AssertionError("Malformed/repeated Luau must not be re-encoded as a giant JSON string")
    mod = RobloxModuleSpec(
        module_id="dyn_space", name="SpaceModeManager",
        kind="server_script", file_path="src/server/SpaceModeManager.server.luau",
        roblox_service="ServerScriptService",
        description="Validate space phase transitions on the server")
    proposal = RobloxProposal(
        requested_prompt="Assemble a ship and go to space",
        game_title="Space", description="", game_design={
            "pre_design_research": {"evidence": []},
            "dynamic_design": {"remotes": {}}}, modules=[mod])
    model = Router()
    result = RobloxCodeRepairAgent(router=model).repair(mod, proposal, attempts=3)
    assert "phaseTransition" in result
    assert model.text_calls == 2
    assert model.json_calls == 0


def test_previous_repeated_source_is_not_priming_next_model_with_bad_lines(monkeypatch):
    from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        def complete(self, prompt, **kwargs):
            assert prompt.count("self.lastColonizeId = nil") == 0
            return ("--!strict\nlocal function canLaunch(credits: number): boolean\n"
                    "    return credits >= 100\nend\nprint(canLaunch)\n")
    mod = RobloxModuleSpec(
        module_id="dyn_space", name="SpaceModeManager",
        kind="server_script", file_path="src/server/SpaceModeManager.server.luau",
        roblox_service="ServerScriptService",
        description="Server-validated spaceship launch")
    plan = RobloxProposal(requested_prompt="Space game",
                          game_title="Space", description="",
                          game_design={"pre_design_research": {"evidence": []}},
                          modules=[mod])
    result = RobloxCodeRepairAgent(router=Router()).repair(
        mod, plan, existing_code="--!strict\n" + "self.lastColonizeId = nil\n" * 723)
    assert "canLaunch" in result
