"""OpenAI compatible adapter for remote or local proxy endpoints."""

from __future__ import annotations

import os
from .llama_cpp_adapter import LlamaCppAdapter


class OpenAICompatibleAdapter(LlamaCppAdapter):
    """Generic adapter for any OpenAI-compatible API endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str = "gpt-4o-mini",
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        super().__init__(
            base_url=url,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            api_key=key,
        )
