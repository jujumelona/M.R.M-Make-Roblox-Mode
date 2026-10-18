"""Colab model bootstrap contracts, tested without downloading the 5.84GB GGUF."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

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
        return "http://127.0.0.1:8910/v1", "local-gguf"

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
    # Only candidate probes before launch; no duplicate post-launch completion.
    assert not [x for x in events[events.index(("start", tmp_path / "llama-server", tmp_path / "model.gguf"))+1:] if x[0] == "probe"]



def test_reasoning_only_probe_retries_without_thinking(monkeypatch):
    import httpx

    requests = []
    def respond(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "MiMo-9B"}]})
        body = json.loads(request.content)
        requests.append(body)
        if "chat_template_kwargs" not in body:
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "length", "message": {
                    "content": "", "reasoning_content": "thinking..."}}]})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "READY"}}]})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond),
                                                  **kwargs))
    assert runtime._model_probe("http://127.0.0.1:8910/v1") == "MiMo-9B"
    assert len(requests) == 2
    assert requests[1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_reasoning_only_probe_never_claims_readiness(monkeypatch):
    import httpx

    def respond(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "MiMo-9B"}]})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "length", "message": {
                "content": "", "reasoning_content": "thinking..."}}]})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond),
                                                  **kwargs))
    assert runtime._model_probe("http://127.0.0.1:8910/v1") is None


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


def test_opt_in_source_compiler_requires_gpu(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.setenv("RMM_BUILD_LLAMA_FROM_SOURCE", "1")
    monkeypatch.setattr(runtime, "_gpu_cuda_ready", lambda: False)
    with pytest.raises(runtime.ModelStartupError, match="GPU/CUDA compiler"):
        runtime._ensure_llama_server_binary(tmp_path)


def test_notebook_generator_bootstraps_before_first_ai_plan(monkeypatch, tmp_path):
    dest = tmp_path / "generated.ipynb"
    monkeypatch.setattr(notebook_generator, "NOTEBOOK_PATH", dest)
    notebook_generator.build_notebook()
    data = json.loads(dest.read_text(encoding="utf-8"))
    source = [str("".join(cell["source"])) for cell in data["cells"]]
    assert "setup_colab_toolchain(" in source[2]
    assert "MODEL_READY = ensure_model_runtime" in source[2]
    assert "ensure_model_runtime(" not in source[4]
    assert "setup_colab_toolchain(" not in source[4]
    assert "CompleteRobloxAISession(" in source[5]
    assert "if RUN_MODE == \"Execute\" and FINAL_PLAN_REPLY is not None" in source[5]
    assert "if FINAL_PLAN_REPLY.ready_to_build:" in source[6]
    assert "PLAN_FAILURE_LOGS_ZIP = session.export_plan_failure()" in source[6]
    assert "failure_logs_zip" in source[6]
    assert "DOWNLOAD_TARGETS.append(Path(failure_path))" in source[7]
    assert source[2].index("setup_colab_toolchain(") < source[2].index("ensure_model_runtime(")
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



def test_default_installs_pinned_cuda_without_colab_compile(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.delenv("RMM_BUILD_LLAMA_FROM_SOURCE", raising=False)
    calls = []
    binary = tmp_path / "prebuilt" / "llama-server"
    monkeypatch.setattr(runtime, "_ensure_pinned_cuda_binary",
                        lambda root: calls.append(root) or binary)
    monkeypatch.setattr(runtime, "_gpu_cuda_ready",
                        lambda: pytest.fail("CUDA compilation must not run by default"))
    assert runtime._ensure_llama_server_binary(tmp_path) == binary
    assert calls == [tmp_path]


def test_mandatory_sha256_rejects_modified_prebuilt(monkeypatch, tmp_path):
    class Download:
        headers = {"Content-Length": "8"}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b"tampered" if not hasattr(self, "done") and setattr(self, "done", True) is None else b""

    monkeypatch.setattr(runtime.urllib.request, "urlopen",
                        lambda *args, **kwargs: Download())
    with pytest.raises(runtime.ModelStartupError, match="SHA256 mismatch"):
        runtime._download_pinned_cuda_bundle(
            "https://example.invalid/llama-cuda.tar.gz", "0" * 64,
            tmp_path / "cuda.tar.gz"
        )


@pytest.mark.skipif(os.name != "posix", reason="Linux bundle uses POSIX shared-library symlinks")
def test_pinned_tar_libs_and_soname_symlink_chain(tmp_path):
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as writer:
        for filename, body in (
            ("cuda-12.8/llama-server", b"binary"),
            ("cuda-12.8/libggml.so.0.9.8", b"library"),
            ("cuda-12.8/VERSION.txt", b"not executable"),
        ):
            data = tarfile.TarInfo(filename)
            data.size = len(body)
            writer.addfile(data, io.BytesIO(body))
        for name, target in [
            ("cuda-12.8/libggml.so", "libggml.so.0"),
            ("cuda-12.8/libggml.so.0", "libggml.so.0.9.8"),
        ]:
            symlink = tarfile.TarInfo(name)
            symlink.type = tarfile.SYMTYPE
            symlink.linkname = target
            writer.addfile(symlink)
    result = runtime._extract_prebuilt_cuda_bundle(archive, tmp_path / "out")
    assert result.is_file()
    assert (tmp_path / "out" / "libggml.so").resolve().is_file()
    assert not (tmp_path / "out" / "VERSION.txt").exists()


def test_pinned_tar_rejects_external_symlink(tmp_path):
    archive = tmp_path / "malicious.tar.gz"
    with tarfile.open(archive, "w:gz") as writer:
        body = b"binary"
        info = tarfile.TarInfo("cuda-12.8/llama-server")
        info.size = len(body)
        writer.addfile(info, io.BytesIO(body))
        info = tarfile.TarInfo("cuda-12.8/libunsafe.so")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        writer.addfile(info)
    with pytest.raises(runtime.ModelStartupError, match="Unsafe or broken"):
        runtime._extract_prebuilt_cuda_bundle(archive, tmp_path / "out")


def test_prebuilt_cache_never_redownloads(monkeypatch, tmp_path):
    _clean_env(monkeypatch)
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(runtime.shutil, "which",
                        lambda executable: "/usr/bin/nvidia-smi"
                        if executable == "nvidia-smi" else None)
    directory = tmp_path / "prebuilt-cuda-0.7.0"
    directory.mkdir(parents=True)
    (directory / "llama-server").write_bytes(b"binary")
    (directory / ".verified-sha256").write_text(runtime.CUDA_RELEASE_SHA256)
    monkeypatch.setattr(runtime, "_download_pinned_cuda_bundle",
                        lambda *a: pytest.fail("Must reuse verified cache"))
    assert runtime._ensure_pinned_cuda_binary(tmp_path) == directory / "llama-server"



def test_cuda_loader_finds_python_nvidia_wheels_without_torch(monkeypatch, tmp_path):
    package_dir = tmp_path / "python" / "site-packages"
    runtime_dir = package_dir / "nvidia" / "cuda_runtime" / "lib"
    blas_dir = package_dir / "nvidia" / "cublas" / "lib"
    runtime_dir.mkdir(parents=True)
    blas_dir.mkdir(parents=True)
    (runtime_dir / "libcudart.so.12").write_bytes(b"test")
    (blas_dir / "libcublas.so.12").write_bytes(b"test")
    monkeypatch.setattr(runtime.site, "getsitepackages", lambda: [str(package_dir)])
    monkeypatch.setattr(runtime.site, "getusersitepackages",
                        lambda: str(tmp_path / "nonexistent"))
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"elf placeholder")
    env = runtime._cuda_env(binary)
    dirs = env["LD_LIBRARY_PATH"].split(os.pathsep)
    assert dirs[0] == str(binary.parent)
    assert str(runtime_dir) in dirs
    assert str(blas_dir) in dirs


def test_cuda_loader_parses_real_ldd_missing_library_output(monkeypatch, tmp_path):
    import subprocess

    binary = tmp_path / "llama-server"
    binary.write_bytes(b"fake")
    backend = tmp_path / "libggml-cuda.so.0"
    backend.write_bytes(b"fake")

    def fake_ldd(args, **kwargs):
        assert args[0] == "ldd"
        if str(args[1]) == str(binary):
            output = "\tlibcudart.so.12 => not found\n\tlibcublas.so.12 => not found\n"
        else:
            output = "\tlibcublasLt.so.12 => not found\n"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(runtime.subprocess, "run", fake_ldd)
    assert runtime._ldd_missing_libraries(binary, {}) == {
        "libcudart.so.12", "libcublas.so.12", "libcublasLt.so.12"
    }


def test_cuda_loader_installs_only_missing_wheels_and_rechecks(monkeypatch, tmp_path):
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"binary")
    seen = []
    steps = iter([
        {"libcudart.so.12", "libcublas.so.12", "libcublasLt.so.12"},
        set()
    ])
    monkeypatch.setattr(runtime, "_cuda_env",
                        lambda b: {"LD_LIBRARY_PATH": str(b.parent)})
    monkeypatch.setattr(runtime, "_ldd_missing_libraries",
                        lambda *a: next(steps))
    monkeypatch.setattr(runtime, "_checked_command",
                        lambda command, log, **kw: seen.append(command[-1]))
    result = runtime._prepare_cuda_linker_environment(binary, tmp_path)
    assert result["LD_LIBRARY_PATH"] == str(tmp_path)
    assert seen == [
        "nvidia-cublas-cu12==12.8.4.1",
        "nvidia-cuda-runtime-cu12==12.8.90",
    ]


def test_cuda_loader_skips_pip_when_existing_runtime_is_available(monkeypatch, tmp_path):
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"binary")
    monkeypatch.setattr(runtime, "_cuda_env", lambda b: {"LD_LIBRARY_PATH": "ok"})
    monkeypatch.setattr(runtime, "_ldd_missing_libraries", lambda *a: set())
    monkeypatch.setattr(runtime, "_checked_command",
                        lambda *a, **kw: pytest.fail("unexpected CUDA wheel install"))
    assert runtime._prepare_cuda_linker_environment(binary, tmp_path) == {
        "LD_LIBRARY_PATH": "ok"
    }


def test_cuda_loader_rejects_unresolved_runtime_instead_of_spawning(monkeypatch, tmp_path):
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"binary")
    monkeypatch.setattr(runtime, "_cuda_env", lambda b: {"LD_LIBRARY_PATH": "ok"})
    monkeypatch.setattr(runtime, "_ldd_missing_libraries",
                        lambda *a: {"libcudart.so.12"})
    monkeypatch.setattr(runtime, "_checked_command", lambda *a, **kw: None)
    with pytest.raises(runtime.ModelStartupError, match="libcudart.so.12"):
        runtime._prepare_cuda_linker_environment(binary, tmp_path)
