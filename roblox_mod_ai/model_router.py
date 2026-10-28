"""Model router managing roles, adapters, and local GGUF/llama-server connections."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .model_adapters import (
    GenerationRequest,
    GenerationResponse,
    LlamaCppAdapter,
    ModelAdapter,
    OpenAICompatibleAdapter,
)


class ModelRouter:
    """Routes requests between local llama-server instances and profiles."""

    def __init__(self, profile: str = "t4_local") -> None:
        self.profile = profile
        # Real model backends review semantic coverage for any requested
        # gameplay. Lightweight testing transports remain free to provide
        # their own verifier capability explicitly.
        self.supports_source_fidelity_audit = True
        # Genre-neutral atomic source actions can be planned in bounded calls
        # instead of relying on one large multi-action JSON completion.
        self.supports_atomic_action_decomposition = True
        # Resolve ties between source-owned actions and cross-language names
        # without making retrieval translations the implementation authority.
        self.supports_source_ownership_review = True
        # Host owns a stable typed Remote/UI ABI. Model-authored transport
        # metadata has repeatedly blocked the entire generated experience
        # even when the underlying gameplay action was valid. No second
        # input/effect generation call is required in the production pipeline.
        self.supports_host_standard_transport = True
        # Short Luau action bodies use grammar-constrained JSON from the first
        # request. Plain-text completions in production logs repeatedly
        # leaked tool-call delimiters into the Luau source.
        self.supports_scoped_json_body = True
        # Keep the legacy experimental type-manifest path opt-in for tests
        # and explicit research, never as the production hard gate.
        self.supports_typed_action_contract = False
        # Prefer short, validated execution data over whole-file Luau when feasible.
        self.supports_declarative_effect_program = True
        # Explicit capability: short, source-checked mutation operands.
        # Host transport alone does not imply this optional authoring mode.
        self.supports_atomic_state_mutation_repair = True
        self.adapters: dict[str, ModelAdapter] = {}
        self._init_adapters()

    def _init_adapters(self) -> None:
        # Check environment or use local llama.cpp endpoint
        llama_url = (os.environ.get("ROBLOX_LLAMA_SERVER_URL")
                     or os.environ.get("RMM_MODEL_BASE_URL")
                     or "http://127.0.0.1:8080/v1")
        self.adapters["llama_cpp"] = LlamaCppAdapter(
            base_url=llama_url,
            model_name=os.environ.get("RMM_MODEL_ID", "local-gguf"),
            api_key=os.environ.get("RMM_MODEL_API_KEY", "not-needed"),
            timeout_seconds=float(os.environ.get("RMM_MODEL_TIMEOUT_SECONDS", "420")),
        )
        self.adapters["openai"] = OpenAICompatibleAdapter()

    def get_adapter_for_role(self, role: str) -> ModelAdapter:
        # Default all roles (planner, coder, analyzer) to local llama_cpp GGUF adapter
        if self.profile == "openai":
            return self.adapters["openai"]
        return self.adapters["llama_cpp"]

    def complete(
        self,
        prompt: str,
        system_prompt: str = "You are an expert Roblox experience designer and Luau engineer.",
        role: str = "planner",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: str | dict[str, Any] | None = None,
    ) -> str:
        adapter = self.get_adapter_for_role(role)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        request = GenerationRequest(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            metadata={"generation_role": role},
        )
        started = time.monotonic()
        try:
            response = adapter.generate(request)
        except Exception as exc:
            self.last_generation_report = {
                "role": role, "elapsed_seconds": round(time.monotonic() - started, 2),
                "error": type(exc).__name__ + ": " + str(exc)[:600],
            }
            print("[RMM model] " + str(self.last_generation_report), flush=True)
            raise
        self.last_generation_report = {
            "role": role, "elapsed_seconds": round(time.monotonic() - started, 2),
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "finish_reason": response.finish_reason,
            "visible_chars": len(response.content or ""),
        }
        print("[RMM model] " + str(self.last_generation_report), flush=True)
        return response.content

    def research_for_module(self, module: Any, proposal: Any) -> str:
        """Perform bounded read-only MCP observations for any model-authored module.

        Source contracts are host-observed even if a small model cannot emit
        native tool calls. External tool failures are recorded, not fabricated.
        Generation remains subject to independent static and runtime gates.
        """
        from .agent_tool_runtime import (
            RobloxAgentToolRuntime, CONTRACT_TOOL, _preview,
        )
        runtime = RobloxAgentToolRuntime(module, proposal)
        baseline = runtime.call(CONTRACT_TOOL, {})
        notes = [
            "HOST-VERIFIED MODULE SOURCE CONTRACT (not a Studio test): " +
            baseline.get("observation", baseline.get("error", "unavailable"))
        ]
        trace = {
            "module_id": module.module_id,
            "module": module.name,
            "scope": "read_only_module_research",
            "status": "model_not_called",
            "calls": runtime.records,
        }
        if not hasattr(self, "agent_tool_traces"):
            self.agent_tool_traces = {}
        self.agent_tool_traces[module.module_id] = trace
        if not baseline["ok"]:
            trace["status"] = "source_inspection_failed"
            return "\n".join(notes)
        # Tool research is a separate small turn; never mix tool calls and
        # grammar-constrained Luau JSON in one provider request.
        tools = runtime.definitions()
        names = {item["function"]["name"] for item in tools}
        messages = [
            {"role": "system", "content": (
                "You inspect ONE Roblox module before authoring its Luau. "
                "Use only the offered read-only Roblox tools. Call API search "
                "or official docs when unsure about an engine member; call "
                "the module contract inspector for actual permitted world "
                "parts, remotes and peer methods. Do not invent evidence. "
                "Never deploy, edit Studio, run game builds, or claim a "
                "Studio playtest. Stop after enough factual evidence."
            )},
            {"role": "user", "content": (
                "Inspect only this implementation: " + str(module.description or "")[:800] +
                "\nFile: " + module.file_path +
                "\nVerified source contract: " +
                baseline.get("observation", "")[:1900] +
                "\nUse read-only tools for any required additional evidence; "
                "when there is no need, reply briefly without tool calls."
            )},
        ]
        adapter = self.get_adapter_for_role("coder")
        seen = set()
        total_calls = 0
        for step in range(3):
            try:
                response = adapter.generate(GenerationRequest(
                    messages=messages, temperature=0, max_tokens=500,
                    tools=tools, metadata={"generation_role": "tool_research"},
                ))
            except Exception as exc:
                trace["status"] = "model_tool_protocol_unavailable"
                trace["error"] = type(exc).__name__ + ": " + str(exc)[:250]
                break
            if not response.tool_calls:
                trace["status"] = (
                    "source_inspected_no_extra_tool_calls" if total_calls == 0
                    else "tool_observations_returned"
                )
                break
            if total_calls + len(response.tool_calls) > 6:
                trace["status"] = "tool_budget_exhausted"
                break
            reply_calls = []
            observations = []
            for index, tc in enumerate(response.tool_calls):
                call_id = tc.call_id or f"call_{step}_{index}"
                reply_calls.append({
                    "id": call_id, "type": "function",
                    "function": {"name": tc.name,
                                 "arguments": json.dumps(tc.arguments)},
                })
                signature = (tc.name, json.dumps(tc.arguments, sort_keys=True))
                if signature in seen:
                    result = {"ok": False, "error": "duplicate_tool_call"}
                else:
                    # The runtime rejects unapproved names itself so even a
                    # forged native call is attested in the failure receipt.
                    result = runtime.call(tc.name, tc.arguments)
                    seen.add(signature)
                observations.append({"role": "tool", "tool_call_id": call_id,
                                     "content": _preview(result, 2700)})
                if result.get("ok") and tc.name != CONTRACT_TOOL:
                    notes.append("OBSERVED " + tc.name + " (untrusted source data, "
                                 "NOT Studio verified): " +
                                 result.get("observation", "")[:1350])
                if not result.get("ok"):
                    notes.append("TOOL UNAVAILABLE/REJECTED " + tc.name + ": "
                                 + result.get("error", "")[:180])
            total_calls += len(response.tool_calls)
            messages.append({
                "role": "assistant", "content": response.content or None,
                "tool_calls": reply_calls,
            })
            messages.extend(observations)
            trace["status"] = "tool_budget_reached" if total_calls == 6 else "tools_observed"
        else:
            trace["status"] = "tool_round_limit_reached"
        trace["calls"] = list(runtime.records)
        trace["native_tool_calls"] = total_calls
        return "\n".join(notes)[:8500] + "\n"

    def complete_json(
        self,
        prompt: str,
        system_prompt: str = "You are an expert Roblox experience architect. Output valid JSON only.",
        role: str = "planner",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        structured_format = (
            {"type": "json_schema", "schema": json_schema}
            if json_schema is not None and self.profile != "openai"
            else "json"
        )
        raw = self.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            role=role,
            temperature=temperature,
            response_format=structured_format,
            max_tokens=max_tokens,
        )
        report = getattr(self, "last_generation_report", {})
        if isinstance(report, dict) and report.get("finish_reason") == "length":
            raise ValueError("Model JSON completion truncated (finish_reason=length); "
                             "request a smaller scoped output instead of reparsing it")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as first_error:
            # Retain the REAL malformed output excerpt, not a stale prior
            # successful dict. This diagnosis reaches the plan-failure report.
            import re
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            report = getattr(self, "last_generation_report", None)
            if isinstance(report, dict):
                report["json_parse_error"] = (
                    f"{first_error.msg} at line {first_error.lineno} "
                    f"column {first_error.colno}, char {first_error.pos}")
                report["malformed_output_head"] = raw[:2500]
                report["malformed_output_tail"] = raw[-2500:]
                report["malformed_output_length"] = len(raw)
            raise
