"""Changing nested backend code must invalidate generated-source checkpoints."""
from pathlib import Path

from roblox_mod_ai.generation_provenance import generation_source_digests


def test_nested_model_backend_is_part_of_generation_signature(tmp_path):
    root = tmp_path / "roblox_mod_ai"
    root.mkdir()
    (root / "code_generator.py").write_text("VERSION = 1\n", encoding="utf-8")
    package = root / "model_adapters"
    package.mkdir()
    adapter = package / "llama_cpp_adapter.py"
    adapter.write_text("CONTEXT_LIMIT = 32768\n", encoding="utf-8")
    first = generation_source_digests(root)
    assert set(first) == {"code_generator.py", "model_adapters/llama_cpp_adapter.py"}
    adapter.write_text("CONTEXT_LIMIT = 65536\n", encoding="utf-8")
    second = generation_source_digests(root)
    assert first["code_generator.py"] == second["code_generator.py"]
    assert first["model_adapters/llama_cpp_adapter.py"] != second[
        "model_adapters/llama_cpp_adapter.py"]


def test_top_level_cache_keys_are_preserved(tmp_path):
    root = tmp_path / "roblox_mod_ai"
    root.mkdir()
    (root / "code_generator.py").write_text("pass\n", encoding="utf-8")
    result = generation_source_digests(root)
    assert "code_generator.py" in result
