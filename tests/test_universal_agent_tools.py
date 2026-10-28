"""Universal read-only tool-using coder regression tests.

These use fake native LLM responses and a fake MCP endpoint: no network,
Roblox account, Studio, model weights or real deployment is needed.
"""
import json
import httpx
import pytest

from roblox_mod_ai.agent_tool_runtime import (
    RobloxAgentToolRuntime, CONTRACT_TOOL, module_contract_snapshot,
)
from roblox_mod_ai.model_adapters import (
    GenerationRequest, GenerationResponse, ToolCall, ModelBackendError,
)
from roblox_mod_ai.model_adapters.llama_cpp_adapter import LlamaCppAdapter
from roblox_mod_ai.model_router import ModelRouter
from test_log25_verified_typed_effects import _fixture


class FakeMCP:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "roblox_luau_validate":
            return {"passed": True, "diagnostics": []}
        if name == "roblox_api_search":
            return {"count": 1, "results": [{"class_name": "Players",
                                                "member_name": "GetPlayers"}]}
        return {"results": []}


def test_tools_are_actual_allowlisted_mcp_definitions():
    plan, module = _fixture("combat")
    runtime = RobloxAgentToolRuntime(module, plan, FakeMCP())
    names = {item["function"]["name"] for item in runtime.definitions()}
    assert CONTRACT_TOOL in names
    assert "roblox_api_search" in names
    assert "roblox_official_docs_search" in names
    assert "roblox_luau_validate" in names
    for forbidden in ("roblox_project_write", "roblox_studio_action",
                      "roblox_open_cloud_deploy", "roblox_rbxlx_build",
                      "roblox_toolchain_run"):
        assert forbidden not in names


def test_source_contract_only_exposes_approved_part_and_peer_exports():
    plan, module = _fixture("combat")
    report = module_contract_snapshot(module, plan)
    assert report["module_id"] == module.module_id
    assert report["linked_world_objects"] == ["AlienEntities1", "OrbitArrival",
                                               "SpecialMineralDeposit1"] or (
        "AlienEntities1" in report["linked_world_objects"]
        and "SpecialMineralDeposit1" in report["linked_world_objects"])
    assert report["scope"] == "source_plan_only_not_runtime_verified"
    assert report["linked_remotes"]["ActionSomethingRemote"]["service"] == module.name


def test_permission_gate_never_invokes_mutating_mcp_tools():
    plan, module = _fixture("combat")
    server = FakeMCP()
    runtime = RobloxAgentToolRuntime(module, plan, server)
    for name in ("roblox_studio_action", "roblox_project_write",
                 "roblox_open_cloud_deploy", "roblox_toolchain_run",
                 "roblox_rbxlx_build"):
        observed = runtime.call(name, {"allow_write": True})
        assert not observed["ok"]
        assert "TOOL_NOT_APPROVED" in observed["error"]
    assert server.calls == []


def test_invalid_arguments_and_unbounded_source_are_rejected():
    plan, module = _fixture("combat")
    mcp = FakeMCP()
    runtime = RobloxAgentToolRuntime(module, plan, mcp)
    invalid = [
        ("roblox_api_search", {"query": ""}),
        ("roblox_api_search", {"query": "a" * 301}),
        ("roblox_api_search", {"query": "Player", "write": True}),
        ("roblox_luau_validate", {"code": "a" * 16001}),
        ("roblox_luau_validate", {"code": "print(1)",
                                  "file_path": "../script.luau"}),
        (CONTRACT_TOOL, {"module_id": "other"}),
    ]
    for name, args in invalid:
        assert not runtime.call(name, args)["ok"]
    assert mcp.calls == []


def test_connected_studio_can_be_inspected_but_never_controlled_by_coder():
    plan, module = _fixture("combat")
    mcp = FakeMCP()
    runtime = RobloxAgentToolRuntime(module, plan, mcp)
    assert runtime.call("roblox_studio_inspect", {
        "tool": "get_console_output", "arguments": {}
    })["ok"]
    assert mcp.calls == [("roblox_studio_inspect", {
        "tool": "get_console_output", "arguments": {}
    })]
    assert not runtime.call("roblox_studio_inspect", {
        "tool": "execute_luau", "arguments": {"code": "game:Shutdown()"}
    })["ok"]
    assert len(mcp.calls) == 1


def test_read_only_mcp_calls_have_observation_hashes_and_real_status():
    plan, module = _fixture("combat")
    mcp = FakeMCP()
    runtime = RobloxAgentToolRuntime(module, plan, mcp)
    got = runtime.call("roblox_api_search", {"query": "Players"})
    assert got["ok"]
    assert mcp.calls == [("roblox_api_search", {"query": "Players"})]
    assert "GetPlayers" in got["observation"]
    assert len(runtime.records[-1]["observation_sha256"]) == 64
    assert runtime.records[-1]["source"] == "roblox_mcp_tool"
    assert runtime.call(CONTRACT_TOOL, {})["ok"]


class FakeToolAdapter:
    def __init__(self, first_calls):
        self.calls = []
        self.first_calls = first_calls

    def generate(self, request):
        self.calls.append(request)
        if len(self.calls) == 1:
            return GenerationResponse(content="", tool_calls=self.first_calls)
        return GenerationResponse(content="Inspected module contract.")


def test_model_research_exchanges_native_tool_messages_and_keeps_receipts():
    plan, module = _fixture("harvest")
    adapter = FakeToolAdapter([ToolCall(CONTRACT_TOOL, {}, "call_real_1")])
    router = ModelRouter.__new__(ModelRouter)
    router.get_adapter_for_role = lambda role: adapter
    note = router.research_for_module(module, plan)
    assert "HOST-VERIFIED MODULE SOURCE CONTRACT" in note
    assert len(adapter.calls) == 2
    first = adapter.calls[0]
    assert first.tools and first.metadata["generation_role"] == "tool_research"
    second = adapter.calls[1]
    assert second.messages[-1]["role"] == "tool"
    assert second.messages[-1]["tool_call_id"] == "call_real_1"
    assert router.agent_tool_traces[module.module_id]["native_tool_calls"] == 1
    assert router.agent_tool_traces[module.module_id]["status"] == "tool_observations_returned"
    assert len(router.agent_tool_traces[module.module_id]["calls"]) == 2


def test_model_cannot_request_studio_or_project_mutation_even_if_hallucinated():
    plan, module = _fixture("combat")
    adapter = FakeToolAdapter([
        ToolCall("roblox_project_write",
                 {"file_path": "src/server/Hack.luau", "content": "print(1)"}, "call_x")
    ])
    router = ModelRouter.__new__(ModelRouter)
    router.get_adapter_for_role = lambda role: adapter
    note = router.research_for_module(module, plan)
    assert "TOOL_NOT_APPROVED" in note
    assert router.agent_tool_traces[module.module_id]["native_tool_calls"] == 1


def test_native_tool_protocol_includes_functions_and_accepts_tool_only_responses(monkeypatch):
    sent = []
    class Response:
        status_code = 200
        def json(self):
            return {
                "choices": [{
                    "message": {"content": None, "tool_calls": [{
                        "id": "call_doc", "type": "function",
                        "function": {"name": "roblox_api_search",
                                     "arguments": '{"query":"Players"}'},
                    }]},
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 2, "completion_tokens": 8},
            }
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, json, headers):
            sent.append(json)
            return Response()
    monkeypatch.setattr(httpx, "Client", Client)
    request = GenerationRequest(messages=[{"role": "user", "content": "check API"}],
        tools=[{"type": "function", "function": {
            "name": "roblox_api_search", "parameters": {"type": "object",
            "properties": {"query": {"type": "string"}}},
        }}], metadata={"generation_role": "tool_research"})
    response = LlamaCppAdapter().generate(request)
    assert not response.content
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].arguments == {"query": "Players"}
    assert sent[0]["tool_choice"] == "auto"
    assert sent[0]["tools"][0]["function"]["name"] == "roblox_api_search"


def test_empty_native_response_without_tools_is_error(monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": ""},
                                 "finish_reason": "length"}], "usage": {}}
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, json, headers):
            return Response()
    monkeypatch.setattr(httpx, "Client", Client)
    with pytest.raises(ModelBackendError, match="empty visible content"):
        LlamaCppAdapter().generate(
            GenerationRequest(messages=[{"role": "user", "content": "hello"}],
                              tools=[{"type": "function", "function": {
                                  "name": CONTRACT_TOOL,
                                  "parameters": {"type": "object"}}}])
        )
