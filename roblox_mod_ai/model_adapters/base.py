"""Base classes and types for model adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ModelBackendError(RuntimeError):
    """Raised when communication with the model runtime fails."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass
class GenerationRequest:
    messages: list[dict[str, Any]]
    temperature: float = 0.2
    max_tokens: int = 4096
    response_format: str | None = None  # None, "json", or schema dict
    tools: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"


class ModelAdapter:
    """Abstract interface for local or remote LLM backends."""

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError
