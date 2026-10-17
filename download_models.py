"""Helper script to download Roblox Luau fine-tuned models from Hugging Face."""

from __future__ import annotations

import argparse
import sys
from roblox_mod_ai.model_registry import ROBLOX_MODEL_CATALOG, RobloxModelRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Roblox Luau fine-tuned models from Hugging Face")
    parser.add_argument("--list", action="store_true", help="List all available Roblox LoRA and GGUF models")
    parser.add_argument("--model", type=str, default="roblox-coder-v2-gguf", help="Model ID to download")
    parser.add_argument("--dest", type=str, default="models", help="Destination folder")

    args = parser.parse_args()

    if args.list:
        print("Available Roblox Luau Fine-Tuned Models on Hugging Face:\n")
        for m in RobloxModelRegistry.list_models():
            print(f"- {m['model_id']} ({m['kind'].upper()})")
            print(f"  HuggingFace: {m['huggingface_repo']}")
            print(f"  VRAM: ~{m['vram_gb']}GB | Runtime: {m['runtime']}")
            print(f"  {m['description']}\n")
        sys.exit(0)

    model_meta = RobloxModelRegistry.get_model(args.model)
    if not model_meta:
        print(f"Error: Unknown model '{args.model}'. Run with --list to view available models.")
        sys.exit(1)

    print(f"Downloading {model_meta.model_id} from {model_meta.huggingface_repo}...")
    try:
        from huggingface_hub import snapshot_download
        path = snapshot_download(repo_id=model_meta.huggingface_repo, local_dir=args.dest)
        print(f"✅ Model downloaded successfully to: {path}")
    except ImportError:
        print("Note: 'huggingface_hub' is required to download directly.")
        print(f"Run: pip install huggingface-hub")
        print(f"Or manual download link: https://huggingface.co/{model_meta.huggingface_repo}")


if __name__ == "__main__":
    main()
