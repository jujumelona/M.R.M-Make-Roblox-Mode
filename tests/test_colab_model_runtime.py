"""Colab model bootstrap contracts, tested without downloading the 5.84GB GGUF."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from roblox_mod_ai import colab_model_runtime as runtime
from tools import generate_colab_notebook as notebook_generator


def _clean_env(monkeypatch):
    for key in ("RMM_MODEL_BASE_URL", "ROBLOX_LLAMA_SERVER_URL",
                "RMM_MODEL_API_KEY", "RMM_MODEL_ID", "RMM_LLAMA_SERVER_BIN",
                "ROBLOX_MOD_AI_ALLOW_OFFLINE_FALLBACK"):
        # Record a reversible change even if the key was initially absent;
        # ensure_model_runtime sets os.environ directly during the test.
        monkeypatch.setenv(key, "")


def test_managed_colab_model_is_started_before_plan(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    events = []
    started = {"value": False}

    def probe(url, key=""):
        events.append(("probe", url))
        return "local-gguf" if started["value"] else None

    def binary(root):
        events.append(("build", root))
        return tmp_path / "llama-server"

    def model(root):
        events.append(("download", root))
        return tmp_path / "model.gguf"

    def start(b, m, root):
        events.append(("start", b, m))
        started["value"] = True
        return "http://127.0.0.1:8910/v1"

    monkeypatch.setattr(runtime, "_model_probe", probe)
    monkeypatch.setattr(runtime, "_ensure_llama_server_binary", binary)
    monkeypatch.setattr(runtime, "_download_gguf", model)
    monkeypatch.setattr(runtime, "_start_managed_server", start)

    result = runtime.ensure_model_runtime(
        profile="t4_local", cache_root=tmp_path, in_colab=True
    )
    assert result == {
        "status": "managed_colab",
        "url": "http://127.0.0.1:8910/v1",
        "model_id": "local-gguf"
    }
    assert runtime.os.environ["ROBLOX_LLAMA_SERVER_URL"] == result["url"]
    assert runtime.os.environ["RMM_MODEL_ID"] == result["model_id"]
    assert runtime.os.environ["ROBLOX_MOD_AI_ALLOW_OFFLINE_FALLBACK"] == "0"
    assert [x[0] for x in events if x[0] != "probe"] == [
        "build", "download", "start"
    ]


def test_existing_real_model_is_reused_without_model_download(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.setattr(runtime, "_model_probe", lambda url, key="": "MiMo-9B")
    monkeypatch.setattr(runtime, "_download_gguf", lambda root: pytest.fail("unneeded"))
    result = runtime.ensure_model_runtime(profile="t4_local", in_colab=True,
                                          cache_root=tmp_path)
    assert result["status"] == "verified_existing"
    assert result["model_id"] == "MiMo-9B"


def test_explicit_remote_must_complete_chat_or_fail(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setattr(runtime, "_model_probe", lambda url, key="": None)
    with pytest.raises(runtime.ModelStartupError, match="working chat inference"):
        runtime.ensure_model_runtime(
            profile="t4_local", remote_base_url="https://example.test/v1",
            api_key="test_key", in_colab=True
        )


def test_missing_local_server_is_not_treated_as_a_valid_custom_game(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setattr(runtime, "_model_probe", lambda url, key="": None)
    with pytest.raises(runtime.ModelStartupError, match="No active llama.cpp"):
        runtime.ensure_model_runtime(profile="t4_local", in_colab=False)


def test_model_compiler_must_support_gpu_and_never_fake(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.setattr(runtime, "_gpu_cuda_ready", lambda: False)
    with pytest.raises(runtime.ModelStartupError, match="GPU/CUDA compiler"):
        runtime._ensure_llama_server_binary(tmp_path)


def test_notebook_generator_bootstraps_before_first_ai_plan(monkeypatch, tmp_path):
    dest = tmp_path / "generated.ipynb"
    monkeypatch.setattr(notebook_generator, "NOTEBOOK_PATH", dest)
    notebook_generator.build_notebook()
    data = json.loads(dest.read_text(encoding="utf-8"))
    source = [str("".join(cell["source"])) for cell in data["cells"]]
    assert "ensure_model_runtime(" in source[4]
    assert "MODEL_READY = ensure_model_runtime" in source[4]
    assert "CompleteRobloxAISession(" in source[5]
    assert "if RUN_MODE == \"Execute\" and FINAL_PLAN_REPLY is not None" in source[5]
    assert "if not FINAL_PLAN_REPLY.ready_to_build:" in source[6]
    assert source[4].index("ensure_model_runtime(") < len(source[4])
    assert "sample_models" not in source[4]


def test_session_boots_real_model_for_older_colab_notebook(monkeypatch, tmp_path):
    from roblox_mod_ai.api import CompleteRobloxAISession

    called = []
    monkeypatch.setattr(CompleteRobloxAISession, "_is_colab_runtime",
                        staticmethod(lambda: True))

    def bootstrap(**kwargs):
        called.append(kwargs)
        return {"status": "verified_existing",
                "url": "http://127.0.0.1:8910/v1", "model_id": "local-gguf"}

    monkeypatch.setattr(runtime, "ensure_model_runtime", bootstrap)
    session = CompleteRobloxAISession(output_root=tmp_path, model_profile="t4_local")
    assert len(called) == 1
    assert called[0]["in_colab"] is True
    assert session.model_runtime["status"] == "verified_existing"


def test_fast_test_session_never_downloads_model(monkeypatch, tmp_path):
    from roblox_mod_ai.api import CompleteRobloxAISession

    monkeypatch.setattr(CompleteRobloxAISession, "_is_colab_runtime",
                        staticmethod(lambda: True))
    monkeypatch.setattr(runtime, "ensure_model_runtime",
                        lambda **kwargs: pytest.fail("test profile started production GGUF"))
    session = CompleteRobloxAISession(output_root=tmp_path,
                                      model_profile="fast_test", fast_mode=True)
    assert session.model_runtime is None
