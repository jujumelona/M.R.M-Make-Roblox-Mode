"""Catalog and profile resolver for open-source Roblox Luau LoRA and GGUF models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelMetadata:
    model_id: str
    kind: str  # "gguf", "lora", "base_model"
    base_model: str
    huggingface_repo: str
    description: str
    recommended_vram_gb: float
    recommended_runtime: str  # "llama.cpp", "peft/transformers", "ollama"


# Public Hugging Face models fine-tuned specifically for Roblox Luau development
ROBLOX_MODEL_CATALOG: dict[str, ModelMetadata] = {
    "roblox-coder-v2-gguf": ModelMetadata(
        model_id="roblox-coder-v2-gguf",
        kind="gguf",
        base_model="Qwen2.5-Coder-7B",
        huggingface_repo="preferredev/Roblox-Coder-v2_gguf",
        description="Quantized GGUF model optimized for llama.cpp, fine-tuned on Roblox Studio and Luau API.",
        recommended_vram_gb=6.0,
        recommended_runtime="llama.cpp",
    ),
    "roblox-luau-mistral-7b-lora": ModelMetadata(
        model_id="roblox-luau-mistral-7b-lora",
        kind="lora",
        base_model="mistralai/Mistral-7B-Instruct-v0.3",
        huggingface_repo="squaredcuber/roblox-luau-mistral-7b-2",
        description="PEFT LoRA adapter for Mistral-7B fine-tuned on Roblox Luau syntax and idioms.",
        recommended_vram_gb=8.0,
        recommended_runtime="peft/transformers",
    ),
    "luau-qwen-coder-30b-lora": ModelMetadata(
        model_id="luau-qwen-coder-30b-lora",
        kind="lora",
        base_model="Qwen/Qwen2.5-Coder-32B-Instruct",
        huggingface_repo="bostonstrong567/Luau-Qwen3-Coder-30B-A3B",
        description="High-capacity LoRA adapter trained on tens of thousands of real-world Roblox Luau codebases via Unsloth.",
        recommended_vram_gb=18.0,
        recommended_runtime="peft/transformers",
    ),
    "deepseek-roblox-1.3b-lora": ModelMetadata(
        model_id="deepseek-roblox-1.3b-lora",
        kind="lora",
        base_model="deepseek-ai/deepseek-coder-1.3b-instruct",
        huggingface_repo="thameurabderrahim/deepseek-coder-1.3b-roblox-lora",
        description="Ultra-lightweight 1.3B parameter Luau LoRA adapter for low-resource systems (under 4GB VRAM).",
        recommended_vram_gb=3.5,
        recommended_runtime="peft/transformers",
    ),
}


class RobloxModelRegistry:
    """Resolves and inspects open-source Roblox fine-tuned models."""

    @staticmethod
    def list_models() -> list[dict[str, Any]]:
        return [
            {
                "model_id": m.model_id,
                "kind": m.kind,
                "base_model": m.base_model,
                "huggingface_repo": m.huggingface_repo,
                "description": m.description,
                "vram_gb": m.recommended_vram_gb,
                "runtime": m.recommended_runtime,
            }
            for m in ROBLOX_MODEL_CATALOG.values()
        ]

    @staticmethod
    def get_model(model_id: str) -> ModelMetadata | None:
        return ROBLOX_MODEL_CATALOG.get(model_id)
