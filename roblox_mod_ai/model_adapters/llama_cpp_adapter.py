"""Direct OpenAI-compatible llama.cpp adapter for local GGUF models."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .base import (
    GenerationRequest,
    GenerationResponse,
    ModelAdapter,
    ModelBackendError,
    ToolCall,
)


class LlamaCppAdapter(ModelAdapter):
    """Adapter for local llama-server running GGUF models."""

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str = "local-gguf",
        timeout_seconds: float = 120.0,
        api_key: str = "not-needed",
    ) -> None:
        url = (
            base_url
            or os.environ.get("ROBLOX_LLAMA_SERVER_URL")
            or os.environ.get("MMM_LLAMA_SERVER_URL")
            or "http://127.0.0.1:8080/v1"
        )
        self.base_url = url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key

    def _is_server_reachable(self) -> bool:
        try:
            with httpx.Client(timeout=1.5) as client:
                res = client.get(f"{self.base_url}/models")
                return res.status_code == 200
        except Exception:
            return False

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        endpoint = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        # JSON and generated Luau need visible output. On reasoning GGUFs the
        # entire code budget can be spent in hidden <think> tokens, leaving an
        # empty response. The prior code disabled thinking for JSON only.
        is_local_llama = self.base_url.lower().startswith((
            "http://127.0.0.1:", "http://localhost:", "http://[::1]:"))
        no_reasoning = (
            (request.response_format == "json" and
             os.environ.get("RMM_JSON_ENABLE_THINKING", "0") != "1")
            or (request.metadata.get("generation_role") == "coder" and
                os.environ.get("RMM_CODE_ENABLE_THINKING", "0") != "1")
        )
        if is_local_llama and no_reasoning:
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        elif isinstance(request.response_format, dict):
            payload["response_format"] = {
                "type": "json_object",
                "schema": request.response_format,
            }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                if resp.status_code != 200:
                    raise ModelBackendError(
                        f"llama.cpp server returned HTTP {resp.status_code}: {resp.text}"
                    )
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content", "") or ""
                # Fail with real runtime metadata instead of silently turning
                # an empty completion into a '--!strict' fake module.
                if not str(content).strip():
                    usage = data.get("usage", {})
                    reason = choice.get("finish_reason", "unknown")
                    raise ModelBackendError(
                        "llama.cpp produced empty visible content; "
                        f"finish_reason={reason}, "
                        f"prompt_tokens={usage.get('prompt_tokens', '?')}, "
                        f"completion_tokens={usage.get('completion_tokens', '?')}; "
                        "check reasoning tokens, context size and model template"
                    )

                tool_calls: list[ToolCall] = []
                for tc in message.get("tool_calls", []):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    tool_calls.append(ToolCall(name=name, arguments=args, call_id=tc.get("id", "")))

                usage = data.get("usage", {})
                return GenerationResponse(
                    content=content,
                    tool_calls=tool_calls,
                    model=data.get("model", self.model_name),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    finish_reason=choice.get("finish_reason", "stop"),
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            # If local llama-server is not running or unreachable,
            # allow fallback simulator mode for tests and offline usage
            # Production must never fabricate LLM output when no server is running.
            # Simulated responses are restricted to explicit test opt-in.
            allow_fallback = os.environ.get("ROBLOX_MOD_AI_ALLOW_OFFLINE_FALLBACK", "0") == "1"
            if allow_fallback:
                return self._simulate_fallback_response(request)
            raise ModelBackendError(
                f"Could not connect to local llama.cpp server at {self.base_url}: {exc}"
            ) from exc
        except Exception as exc:
            raise ModelBackendError(f"llama.cpp generation failed: {exc}") from exc

    def _simulate_fallback_response(self, request: GenerationRequest) -> GenerationResponse:
        """Deterministic simulation for offline local environments and fast testing."""
        last_message = request.messages[-1].get("content", "") if request.messages else ""
        prompt_text = str(last_message)

        if "plan" in prompt_text.lower() or "design" in prompt_text.lower() or request.response_format == "json":
            # Return structured game plan JSON
            mock_plan = {
                "game_title": "ArenaConquest",
                "genre": "Action & Adventure",
                "summary": "Fast-paced Roblox combat arena with coins, shop, and leaderstats.",
                "core_loop": [
                    "Players spawn in safe lobby zone",
                    "Enter battle arena to fight opponents or neutral mobs",
                    "Earn coins on hits and knockouts",
                    "Spend coins in shop to upgrade swords and armor",
                    "Persistent high score saved to DataStoreService",
                ],
                "subsystems": [
                    {
                        "name": "Leaderstats & DataStore",
                        "script": "src/server/PlayerDataManager.server.luau",
                        "service": "ServerScriptService",
                        "description": "Handles Coins, Level, Kills with session lock and pcall safety.",
                    },
                    {
                        "name": "Arena & Combat Server",
                        "script": "src/server/CombatSystem.server.luau",
                        "service": "ServerScriptService",
                        "description": "Server-authoritative damage validation, cooldowns, and knockout awards.",
                    },
                    {
                        "name": "Network Bridge",
                        "script": "src/shared/NetworkRemotes.luau",
                        "service": "ReplicatedStorage",
                        "description": "RemoteEvents: AttackRequest, ShopPurchase, UpdateHUD.",
                    },
                    {
                        "name": "Client Combat Controller",
                        "script": "src/client/CombatController.client.luau",
                        "service": "StarterPlayer.StarterPlayerScripts",
                        "description": "Handles input clicks, weapon swing animations, and sound effects.",
                    },
                    {
                        "name": "HUD & Shop GUI",
                        "script": "src/client/HUDController.client.luau",
                        "service": "StarterPlayer.StarterPlayerScripts",
                        "description": "Displays health bar, coin counter, and responsive shop interface.",
                    },
                ],
            }
            content = json.dumps(mock_plan, indent=2, ensure_ascii=False)
        else:
            content = (
                f"# Roblox Experience Blueprint\n"
                f"Generated based on request: {prompt_text}\n\n"
                f"1. **Core Gameplay**: Server-authoritative mechanics with Luau.\n"
                f"2. **Networking**: RemoteEvents in ReplicatedStorage with sanity checks.\n"
                f"3. **Persistence**: Safe DataStoreService with retry logic.\n"
                f"4. **UI**: ScreenGui in StarterGui with TweenService polish.\n"
            )

        return GenerationResponse(
            content=content,
            model="simulated-local-gguf",
            prompt_tokens=128,
            completion_tokens=256,
            finish_reason="stop",
        )
