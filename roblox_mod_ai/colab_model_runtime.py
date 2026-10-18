"""Managed llama.cpp bootstrap for RMM Colab.

Unlike a model *profile*, this starts a real model process before the planner.
No simulated responses or silent fallback to an unrelated Roblox game.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import httpx

MODEL_REPO = "bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF"
MODEL_FILE = "MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf"
# Quantizer used release b10964; this version supports MiMo-V2.6 GGUF.
LLAMA_CPP_REF = "b10964"
MODEL_ALIAS = "local-gguf"
DEFAULT_PORT = 8910
_READY_LOCAL_RUNTIME: dict[str, str] = {}



class ModelStartupError(RuntimeError):
    """An actual model could not be initialized; never return fake game plans."""


def _model_probe(url: str, api_key: str = "") -> str | None:
    """Verify chat *inference* works, not just that a HTTP port is open."""
    headers = {"Authorization": "Bearer " + (api_key or "not-needed")}
    base = url.rstrip("/")
    try:
        with httpx.Client(timeout=httpx.Timeout(180, connect=3, pool=3), trust_env=False) as client:
            response = client.get(base + "/models", headers=headers)
            response.raise_for_status()
            models = response.json().get("data", [])
            if not models or not isinstance(models[0].get("id"), str):
                return None
            model_id = models[0]["id"]
            response = client.post(
                base + "/chat/completions",
                headers=headers,
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "Reply with the single word READY."}],
                    "temperature": 0,
                    "max_tokens": 160,
                    "stream": False,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"].get("content", "")
            return model_id if isinstance(content, str) and bool(content.strip()) else None
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None


def _probe_with_progress(url: str, api_key: str = "") -> str | None:
    """Keep notebook output alive during a slow first-model inference."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    started = time.monotonic()
    print("[RMM model] verifying real chat inference at " + url, flush=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(_model_probe, url, api_key)
        while True:
            try:
                result = task.result(timeout=12)
                print("[RMM model] inference check " +
                      ("passed" if result else "failed") +
                      f" ({int(time.monotonic()-started)}s)", flush=True)
                return result
            except FutureTimeout:
                print(f"[RMM model] waiting for first inference response "
                      f"({int(time.monotonic()-started)}s)", flush=True)


def _health_ready(url: str) -> bool:
    """llama.cpp /health becomes ready after model weights are loaded."""
    health = url.rstrip("/").removesuffix("/v1") + "/health"
    try:
        with httpx.Client(timeout=3, trust_env=False) as client:
            response = client.get(health)
            return (response.status_code == 200 and
                    response.json().get("status") == "ok")
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def _tail(path: Path, lines: int = 32) -> str:
    if not path.is_file():
        return "(no model log written)"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _checked_command(command: list[str], log: Path, *,
                     cwd: Path | None = None, timeout: int = 1200) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    phase = " ".join(command[:3])
    print("[RMM model] starting " + phase + " (full log: " + str(log) + ")", flush=True)
    began = time.monotonic()
    with log.open("a", encoding="utf-8") as output:
        output.write("\n$ " + " ".join(command) + "\n")
        output.flush()
        process = None
        try:
            process = subprocess.Popen(
                command, cwd=str(cwd) if cwd else None,
                stdout=output, stderr=subprocess.STDOUT,
            )
            while True:
                try:
                    return_code = process.wait(timeout=10)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = int(time.monotonic() - began)
                    print(f"[RMM model] {phase}: {elapsed}s elapsed; "
                          f"recent output: {_tail(log, 2)[-220:]}", flush=True)
                    if elapsed >= timeout:
                        process.kill()
                        process.wait()
                        raise subprocess.TimeoutExpired(command, timeout)
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, command)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ModelStartupError(
                "Model runtime command failed: " + str(exc) +
                "\nLog: " + str(log) + "\n" + _tail(log)
            ) from exc
    print(f"[RMM model] complete {phase} in {int(time.monotonic()-began)}s", flush=True)


def _download_gguf(cache_root: Path) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        _checked_command(
            [sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"],
            cache_root / "installation.log", timeout=300
        )
        from huggingface_hub import hf_hub_download
    try:
        # Uses Hub's content-addressed cache and resumes previously downloaded
        # model blobs. Never download all quantizations or multimodal projectors.
        # Use the shared HF cache so an existing MMM download is reused.
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
        print(f"[RMM model] downloading or reusing {MODEL_REPO}/{MODEL_FILE} "
              "(~5.84GB, Hugging Face cache)", flush=True)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = executor.submit(hf_hub_download, repo_id=MODEL_REPO, filename=MODEL_FILE)
            while True:
                try:
                    path = task.result(timeout=15)
                    print(f"[RMM model] GGUF ready: {path} "
                          f"({int(time.monotonic()-started)}s)", flush=True)
                    return Path(path)
                except FutureTimeout:
                    print(f"[RMM model] GGUF download/cache check in progress: "
                          f"{int(time.monotonic()-started)}s elapsed", flush=True)
    except Exception as exc:
        raise ModelStartupError("GGUF download failed (" + MODEL_REPO + "/" +
                                MODEL_FILE + "): " + str(exc)[:500]) from exc


def _gpu_cuda_ready() -> bool:
    nvcc = shutil.which("nvcc") or (
        "/usr/local/cuda/bin/nvcc"
        if Path("/usr/local/cuda/bin/nvcc").is_file() else None
    )
    return bool(nvcc and
                (shutil.which("nvidia-smi") or Path("/usr/bin/nvidia-smi").is_file()))


def _ensure_llama_server_binary(cache_root: Path) -> Path:
    """Build a pinned, compatible upstream llama-server with CUDA when needed."""
    chosen = os.environ.get("RMM_LLAMA_SERVER_BIN", "").strip()
    if chosen:
        binary = Path(chosen).expanduser().resolve()
        if not binary.is_file():
            raise ModelStartupError("RMM_LLAMA_SERVER_BIN does not exist: " + str(binary))
        return binary
    source = cache_root / "llama.cpp"
    binary = source / "build" / "bin" / "llama-server"
    if binary.is_file():
        return binary
    if not _gpu_cuda_ready():
        raise ModelStartupError(
            "Colab GPU/CUDA compiler unavailable. Select a GPU runtime "
            "(Runtime > Change runtime type > T4 GPU) and run the notebook again."
        )
    cache_root.mkdir(parents=True, exist_ok=True)
    log = cache_root / "llama-build.log"
    if not (source / "CMakeLists.txt").is_file():
        if source.exists():
            raise ModelStartupError("Incomplete llama.cpp source at " + str(source))
        _checked_command([
            "git", "clone", "--depth", "1", "--branch", LLAMA_CPP_REF,
            "https://github.com/ggml-org/llama.cpp.git", str(source),
        ], log, timeout=500)
    build = source / "build"
    cmake = shutil.which("cmake")
    if not cmake:
        raise ModelStartupError("CMake missing in Colab environment.")
    configure = [
        cmake, "-S", str(source), "-B", str(build),
        "-DGGML_CUDA=ON", "-DLLAMA_CURL=OFF",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    if shutil.which("ninja"):
        configure.extend(["-G", "Ninja"])
    if not shutil.which("nvcc") and Path("/usr/local/cuda/bin/nvcc").is_file():
        configure.append("-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc")
    _checked_command(configure, log, timeout=450)
    _checked_command([cmake, "--build", str(build), "--target", "llama-server",
                      "--parallel", "2"], log, timeout=1800)
    if not binary.is_file():
        raise ModelStartupError("llama-server build produced no binary. Log: " + str(log))
    return binary


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _start_managed_server(binary: Path, model: Path, cache_root: Path) -> str:
    if not model.is_file() or model.stat().st_size < 1_000_000_000:
        raise ModelStartupError("Downloaded GGUF missing or unexpectedly small: " + str(model))
    port = next((p for p in range(DEFAULT_PORT, DEFAULT_PORT + 12)
                 if _port_available(p)), None)
    if port is None:
        raise ModelStartupError("No available localhost port for llama.cpp server")
    log = cache_root / "llama-server.log"
    argv = [
        str(binary), "--model", str(model), "--alias", MODEL_ALIAS,
        "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", "16384", "--parallel", "1",
        "--n-gpu-layers", "99", "--batch-size", "512",
        "--ubatch-size", "256",
    ]
    cache_root.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            argv, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True
        )
    url = "http://127.0.0.1:" + str(port) + "/v1"
    print(f"[RMM model] llama-server spawned pid={process.pid} url={url}; "
          f"full server log: {log}", flush=True)
    # Poll cheap /health while loading. Perform a real completion ONCE ready,
    # rather than stacking slow inference requests against an unloaded model.
    for tick in range(150):
        if tick % 5 == 0:
            print(f"[RMM model] waiting for GGUF load: {tick * 3}s; "
                  f"server log: {_tail(log, 2)[-180:]}", flush=True)
        if process.poll() is not None:
            raise ModelStartupError(
                "llama-server terminated (exit " + str(process.returncode) +
                "). Log: " + str(log) + "\n" + _tail(log)
            )
        if _health_ready(url):
            print("[RMM model] weights loaded; testing real chat completion", flush=True)
            if _probe_with_progress(url):
                print("[RMM model] real chat completion verified", flush=True)
                return url
            process.terminate()
            raise ModelStartupError(
                "Server became healthy but failed a real chat completion. Log: " +
                str(log) + "\n" + _tail(log)
            )
        time.sleep(3)
    process.terminate()
    raise ModelStartupError("llama-server never loaded its model. Log: " +
                            str(log) + "\n" + _tail(log))


def ensure_model_runtime(*, profile: str, remote_base_url: str = "",
                         api_key: str = "", cache_root: str | Path = "/content/rmm-model",
                         in_colab: bool = True) -> dict[str, str]:
    """Provide a real, ready-to-infer model endpoint before planning.

    Reuse a verified running model where possible. On Colab and with no
    configured external server, download MiMo Q4_K_M and launch llama.cpp.
    """
    print("[RMM model] starting model runtime bootstrap, profile=" + profile,
          flush=True)
    os.environ["ROBLOX_MOD_AI_ALLOW_OFFLINE_FALLBACK"] = "0"
    if profile == "fast_test":
        return {"status": "test_mode", "url": "", "model_id": ""}
    user_url = remote_base_url.strip()
    # A freshly verified model in THIS Python kernel need not perform a second
    # costly first-token completion when cell 5 constructs the session.
    cached = dict(_READY_LOCAL_RUNTIME)
    if (cached and cached.get("url", "").startswith("http://127.0.0.1:")
            and (not user_url or user_url.rstrip("/") == cached.get("url"))
            and _health_ready(cached["url"])):
        os.environ["ROBLOX_LLAMA_SERVER_URL"] = cached["url"]
        os.environ["RMM_MODEL_BASE_URL"] = cached["url"]
        os.environ["RMM_MODEL_ID"] = cached["model_id"]
        print("[RMM model] reusing healthy, already verified model from setup cell",
              flush=True)
        return cached
    env_url = (os.environ.get("ROBLOX_LLAMA_SERVER_URL")
               or os.environ.get("RMM_MODEL_BASE_URL") or "").strip()
    if user_url:
        model_id = _probe_with_progress(user_url, api_key)
        if not model_id:
            raise ModelStartupError(
                "Configured REMOTE_BASE_URL does not serve working chat inference: " +
                user_url
            )
        url, status = user_url.rstrip("/"), "verified_remote"
    elif env_url and (model_id := _probe_with_progress(env_url, api_key)):
        url, status = env_url.rstrip("/"), "verified_existing"
    else:
        # A valid default local server may already be running in this Colab.
        url = ""
        model_id = ""
        for candidate in ("http://127.0.0.1:8910/v1", "http://127.0.0.1:8080/v1"):
            if model_id := _probe_with_progress(candidate):
                url = candidate
                break
        if url:
            status = "verified_existing"
        else:
            if not in_colab:
                raise ModelStartupError(
                    "No active llama.cpp API server. Set REMOTE_BASE_URL or "
                    "start llama-server locally."
                )
            root = Path(cache_root).expanduser().resolve()
            print("[RMM model] preparing CUDA llama.cpp server", flush=True)
            binary = _ensure_llama_server_binary(root)
            print("[RMM model] checking/downloading GGUF weights", flush=True)
            model = _download_gguf(root)
            url = _start_managed_server(binary, model, root)
            model_id = _probe_with_progress(url) or ""
            if not model_id:
                raise ModelStartupError("Managed model produced no chat response.")
            status = "managed_colab"
    os.environ["ROBLOX_LLAMA_SERVER_URL"] = url
    os.environ["RMM_MODEL_BASE_URL"] = url
    os.environ["RMM_MODEL_ID"] = model_id
    if api_key:
        os.environ["RMM_MODEL_API_KEY"] = api_key
    record = {"status": status, "url": url, "model_id": model_id}
    if url.startswith("http://127.0.0.1:"):
        _READY_LOCAL_RUNTIME.clear()
        _READY_LOCAL_RUNTIME.update(record)
    return record
