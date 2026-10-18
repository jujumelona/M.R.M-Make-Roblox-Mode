"""Regression for 2026-10-18: EconomyLedger wasted 24m and produced only '--!strict'.

Verify the *real* model adapter/router/agent transport rather than mocking
the entire pipeline and incorrectly claiming model code generation works.
"""
from __future__ import annotations

import json
import pytest

from roblox_mod_ai.agent_loop import LuauGenerationError, RobloxCodeRepairAgent
from roblox_mod_ai.model_adapters.llama_cpp_adapter import LlamaCppAdapter
from roblox_mod_ai.model_adapters.base import GenerationRequest, GenerationResponse, ModelBackendError
from roblox_mod_ai.model_router import ModelRouter
from roblox_mod_ai.spec import RobloxModuleSpec, RobloxProposal


def _http_adapter(monkeypatch, *, visible="--!strict\nlocal n = 1\nprint(n)\n",
                  finish_reason="stop", completion_tokens=30):
    from roblox_mod_ai.model_adapters import llama_cpp_adapter
    seen = []
    class Response:
        status_code = 200
        def json(self):
            return {"model": "local-gguf", "choices": [
                {"finish_reason": finish_reason, "message": {"content": visible}}
            ], "usage": {"prompt_tokens": 300, "completion_tokens": completion_tokens}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, headers):
            seen.append((url, json))
            return Response()
    monkeypatch.setattr(llama_cpp_adapter.httpx, "Client", Client)
    return LlamaCppAdapter(base_url="http://127.0.0.1:8910/v1"), seen


def test_real_adapter_disables_hidden_thinking_for_coder(monkeypatch):
    monkeypatch.delenv("RMM_CODE_ENABLE_THINKING", raising=False)
    adapter, seen = _http_adapter(monkeypatch)
    response = adapter.generate(GenerationRequest(
        messages=[{"role": "user", "content": "write Luau"}],
        max_tokens=6000, metadata={"generation_role": "coder"},
    ))
    assert response.content.startswith("--!strict")
    assert seen[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[0][1]["max_tokens"] == 6000


def test_remote_endpoint_does_not_receive_llama_specific_thinking_kwarg(monkeypatch):
    monkeypatch.delenv("RMM_CODE_ENABLE_THINKING", raising=False)
    adapter, seen = _http_adapter(monkeypatch)
    adapter.base_url = "https://some-remote-model.example/v1"
    adapter.generate(GenerationRequest(
        messages=[{"role": "user", "content": "write Luau"}],
        metadata={"generation_role": "coder"},
    ))
    assert "chat_template_kwargs" not in seen[0][1]


def test_empty_model_completion_reports_reason_and_token_usage(monkeypatch):
    adapter, _ = _http_adapter(
        monkeypatch, visible="", finish_reason="length", completion_tokens=6000
    )
    with pytest.raises(ModelBackendError, match="empty visible content") as exc:
        adapter.generate(GenerationRequest(messages=[{"role": "user", "content": "code"}]))
    assert "finish_reason=length" in str(exc.value)
    assert "completion_tokens=6000" in str(exc.value)


def test_router_passes_coder_role_and_preserves_completion_telemetry():
    class FakeAdapter:
        def generate(self, request):
            assert request.metadata == {"generation_role": "coder"}
            return GenerationResponse(content="--!strict\nprint('ok')\n",
                                      prompt_tokens=181, completion_tokens=38,
                                      finish_reason="stop")
    router = ModelRouter()
    router.adapters["llama_cpp"] = FakeAdapter()
    result = router.complete("write valid source", role="coder")
    assert "print" in result
    assert router.last_generation_report["completion_tokens"] == 38
    assert router.last_generation_report["finish_reason"] == "stop"


def _module():
    mod = RobloxModuleSpec(module_id="dyn_currency", name="EconomyLedger",
                           kind="server_script", file_path="src/server/EconomyLedger.server.luau",
                           roblox_service="ServerScriptService",
                           description="A server authoritative credit ledger with atomic deposits and purchases")
    plan = RobloxProposal(
        requested_prompt="Earn money by mining and trading; buy spaceship parts",
        game_title="SpaceEconomy", description="test",
        game_design={"pre_design_research": {"evidence": []},
                     "dynamic_design": {"remotes": {"TradeRequest": "RemoteEvent"},
                                        "world_objects": [], "module_facets": {mod.module_id: ["req-money"]}}},
        modules=[mod])
    return mod, plan


def test_empty_initial_codegen_is_retried_with_smaller_clean_prompt(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        def __init__(self): self.prompts = []
        def complete(self, prompt, **kwargs):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return ""
            return ("--!strict\nlocal ledger: {[number]: number} = {}\n"
                    "local function deposit(id: number, amount: number): number\n"
                    "    ledger[id] = (ledger[id] or 0) + amount\n"
                    "    return ledger[id]\nend\nprint(deposit)\n")
    router = Router()
    mod, plan = _module()
    result = RobloxCodeRepairAgent(router=router).repair(mod, plan, attempts=2)
    assert "ledger[id]" in result
    assert len(router.prompts) == 2
    assert "Previous attempt produced no functional code" in router.prompts[1]
    assert len(router.prompts[1]) < len(router.prompts[0]) + 1500


def test_no_visible_completion_stays_empty_not_fake_strict_module(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        def complete(self, prompt, **kwargs): return ""
    mod, plan = _module()
    with pytest.raises(LuauGenerationError) as e:
        RobloxCodeRepairAgent(router=Router()).repair(mod, plan, attempts=2)
    assert e.value.candidate == ""
    assert "Model returned no visible Luau implementation" in e.value.diagnostics


def test_codegen_backend_error_is_observed_not_converted_to_stub(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        last_generation_report = {"finish_reason": "length", "completion_tokens": 6000}
        def complete(self, prompt, **kwargs):
            raise ModelBackendError("empty visible content; finish_reason=length")
    mod, plan = _module()
    with pytest.raises(LuauGenerationError) as e:
        RobloxCodeRepairAgent(router=Router()).repair(mod, plan, attempts=2)
    assert not e.value.candidate
    assert any("finish_reason=length" in d for d in e.value.diagnostics)



def test_repeated_empty_plaintext_uses_structured_luau_recovery(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        def __init__(self): self.plain_calls=0; self.json_calls=0
        def complete(self, prompt, **kwargs):
            self.plain_calls += 1
            return ""
        def complete_json(self, prompt, **kwargs):
            self.json_calls += 1
            assert kwargs["role"] == "coder"
            assert kwargs["max_tokens"] == 6000
            assert "'luau'" in prompt
            return {"luau": "--!strict\n"
                            "local economy: {[number]: number} = {}\n"
                            "local function credit(userId: number, amount: number): number\n"
                            "    economy[userId] = (economy[userId] or 0) + amount\n"
                            "    return economy[userId]\n"
                            "end\nprint(credit)\n"}
    mod, plan = _module()
    model = Router()
    result = RobloxCodeRepairAgent(router=model).repair(mod, plan, attempts=3)
    assert "economy[userId]" in result
    assert model.plain_calls == 2
    assert model.json_calls == 1


def test_structured_luau_response_is_still_checked_for_placeholders(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        def complete(self, *args, **kwargs): return ""
        def complete_json(self, *args, **kwargs):
            return {"luau": "--!strict\n-- TODO: implement currency\n"}
    mod, plan = _module()
    with pytest.raises(LuauGenerationError) as err:
        RobloxCodeRepairAgent(router=Router()).repair(mod, plan, attempts=3)
    assert "Placeholder code is prohibited" in err.value.diagnostics



def test_exhausted_hidden_reasoning_switches_to_json_on_next_call(monkeypatch):
    monkeypatch.setenv("RMM_ENABLE_MODEL_GENERATION", "1")
    class Router:
        last_generation_report = {}
        def __init__(self): self.plain=0; self.json=0
        def complete(self, prompt, **kwargs):
            self.plain += 1
            self.last_generation_report = {
                "error": "ModelBackendError: empty visible content; "
                         "finish_reason=length, completion_tokens=6000",
            }
            raise ModelBackendError("empty visible content; finish_reason=length")
        def complete_json(self, prompt, **kwargs):
            self.json += 1
            return {"luau": "--!strict\n"
                            "local function buy(playerId: number): number\n"
                            "    local credits = 50\n"
                            "    return credits + playerId\n"
                            "end\nprint(buy)\n"}
    mod, plan = _module()
    router = Router()
    result = RobloxCodeRepairAgent(router=router).repair(mod, plan, attempts=3)
    assert "function buy" in result
    assert router.plain == 1
    assert router.json == 1
