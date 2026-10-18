"""Ensure MiMo's structured-output phase emits JSON, not only thought tokens."""
import json

import httpx

from roblox_mod_ai.model_adapters.base import GenerationRequest
from roblox_mod_ai.model_adapters.llama_cpp_adapter import LlamaCppAdapter


def _capture(monkeypatch):
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "local-gguf",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs:
                        original(transport=httpx.MockTransport(respond), **kwargs))
    return payloads


def test_local_mimo_structured_output_disables_thinking(monkeypatch):
    monkeypatch.delenv("RMM_JSON_ENABLE_THINKING", raising=False)
    payloads = _capture(monkeypatch)
    adapter = LlamaCppAdapter(base_url="http://127.0.0.1:8910/v1")
    answer = adapter.generate(GenerationRequest(
        messages=[{"role": "user", "content": "Return JSON."}],
        response_format="json",
    ))
    assert answer.content == '{"ok":true}'
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert payloads[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_local_mimo_non_json_preserves_reasoning(monkeypatch):
    payloads = _capture(monkeypatch)
    adapter = LlamaCppAdapter(base_url="http://127.0.0.1:8910/v1")
    adapter.generate(GenerationRequest(
        messages=[{"role": "user", "content": "Write Lua code."}],
    ))
    assert "chat_template_kwargs" not in payloads[0]


def test_remote_json_does_not_send_llama_specific_kwargs(monkeypatch):
    payloads = _capture(monkeypatch)
    adapter = LlamaCppAdapter(base_url="https://models.example.test/v1")
    adapter.generate(GenerationRequest(
        messages=[{"role": "user", "content": "Return JSON."}],
        response_format="json",
    ))
    assert "chat_template_kwargs" not in payloads[0]


def test_local_json_thinking_remains_user_configurable(monkeypatch):
    monkeypatch.setenv("RMM_JSON_ENABLE_THINKING", "1")
    payloads = _capture(monkeypatch)
    adapter = LlamaCppAdapter(base_url="http://127.0.0.1:8910/v1")
    adapter.generate(GenerationRequest(
        messages=[{"role": "user", "content": "Return JSON."}],
        response_format="json",
    ))
    assert "chat_template_kwargs" not in payloads[0]
