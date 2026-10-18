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
        response_format: str | None = None,
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
    ) -> dict[str, Any]:
        raw = self.complete(
            prompt=prompt,
            system_prompt=system_prompt,
            role=role,
            temperature=temperature,
            response_format="json",
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try finding json block inside markdown ```json ... ```
            import re
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise
