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
