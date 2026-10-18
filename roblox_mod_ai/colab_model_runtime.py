"""Managed llama.cpp bootstrap for RMM Colab.

Unlike a model *profile*, this starts a real model process before the planner.
No simulated responses or silent fallback to an unrelated Roblox game.
"""
from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import urllib.request
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
# Third-party CUDA release built from upstream llama.cpp v0.7.0;
# pinned byte-for-byte using GitHub's published release asset SHA256.
CUDA_RELEASE_URL = (
    "https://github.com/ai-dock/llama.cpp-cuda/releases/download/v0.7.0/"
    "llama.cpp-v0.7.0-cuda-12.8-amd64.tar.gz"
)
CUDA_RELEASE_SHA256 = "64ed0880c8c4dc4de93526402b550f8ea4d8e26bb54740c219ad2aa69ef87635"
CUDA_RELEASE_SOURCE = "ggml-org/llama.cpp@620d2225cc436ab0b001e3200e590e3b286ef9ab"

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


def _download_pinned_cuda_bundle(url: str, expected_sha256: str, destination: Path) -> None:
    """Download a versioned third-party release with mandatory SHA256 validation."""
    print("[RMM model] downloading precompiled CUDA llama-server (pinned SHA256); "
          "no Colab CUDA compilation", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "RMM-Colab/1.0"})
    actual = hashlib.sha256()
    total = 0
    last = time.monotonic()
    max_bytes = 400 * 1024 * 1024
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ModelStartupError("Prebuilt CUDA bundle larger than expected.")
                actual.update(chunk)
                output.write(chunk)
                if time.monotonic() - last >= 8:
                    print(f"[RMM model] prebuilt CUDA download {total / 1048576:.1f} MiB",
                          flush=True)
                    last = time.monotonic()
    except (OSError, ValueError) as exc:
        raise ModelStartupError("Prebuilt CUDA bundle download failed: " + str(exc)) from exc
    if actual.hexdigest() != expected_sha256:
        raise ModelStartupError(
            "Prebuilt CUDA bundle SHA256 mismatch; archive rejected. "
            "Expected " + expected_sha256 + ", got " + actual.hexdigest())
    print(f"[RMM model] verified {total / 1048576:.1f} MiB CUDA bundle SHA256", flush=True)


def _extract_prebuilt_cuda_bundle(archive: Path, destination: Path) -> Path:
    """Extract only server and shared libraries, without following tar links."""
    destination.mkdir(parents=True, exist_ok=True)
    symlinks: list[tuple[str, str]] = []
    seen: set[str] = set()
    server_found = False
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            name = Path(member.name).name
            allowed = (name == "llama-server" or
                       name.startswith("lib") and ".so" in name)
            if not allowed or name in seen:
                continue
            if member.isreg():
                if member.size > 250 * 1024 * 1024:
                    raise ModelStartupError("Invalid prebuilt library size: " + name)
                handle = source.extractfile(member)
                if handle is None:
                    raise ModelStartupError("Prebuilt archive file missing: " + name)
                with handle, (destination / (name + ".partial")).open("wb") as out:
                    shutil.copyfileobj(handle, out)
                os.replace(destination / (name + ".partial"), destination / name)
                (destination / name).chmod(0o755 if name == "llama-server" else 0o644)
                seen.add(name)
                server_found |= name == "llama-server"
            elif member.issym():
                if ("/" in member.linkname or "\\" in member.linkname or
                        member.linkname in (".", "..")):
                    raise ModelStartupError("Unsafe or broken shared-library symlinks: " + name)
                symlinks.append((name, member.linkname))
        # Resolve common SONAME link chains (libfoo.so -> libfoo.so.0 ->
        # libfoo.so.0.9.8). Never follow links outside the extracted directory.
        unresolved = list(symlinks)
        for _ in range(len(unresolved)):
            following: list[tuple[str, str]] = []
            progressed = False
            for name, target in unresolved:
                if name in seen or name == "llama-server":
                    continue
                if target in seen:
                    (destination / name).symlink_to(target)
                    seen.add(name)
                    progressed = True
                else:
                    following.append((name, target))
            unresolved = following
            if not progressed:
                break
        if unresolved:
            raise ModelStartupError("Unsafe or broken shared-library symlinks: " +
                                    ", ".join(name for name, _ in unresolved[:8]))
    if not server_found:
        raise ModelStartupError("Pinned CUDA archive has no llama-server executable.")
    return destination / "llama-server"


def _ensure_pinned_cuda_binary(cache_root: Path) -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise ModelStartupError("Precompiled CUDA binary is for Linux x86_64 only.")
    if not (shutil.which("nvidia-smi") or Path("/usr/bin/nvidia-smi").is_file()):
        raise ModelStartupError("An NVIDIA GPU is required for Colab CUDA model inference.")
    prebuilt = cache_root / "prebuilt-cuda-0.7.0"
    binary = prebuilt / "llama-server"
    marker = prebuilt / ".verified-sha256"
    if binary.is_file() and marker.is_file() and marker.read_text().strip() == CUDA_RELEASE_SHA256:
        print("[RMM model] reusing pinned precompiled CUDA llama-server", flush=True)
        return binary
    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rmm-cuda-") as scratch:
        tarball = Path(scratch) / "llama-cuda.tar.gz"
        staging = Path(scratch) / "libs"
        _download_pinned_cuda_bundle(CUDA_RELEASE_URL, CUDA_RELEASE_SHA256, tarball)
        binary_tmp = _extract_prebuilt_cuda_bundle(tarball, staging)
        prebuilt.mkdir(parents=True, exist_ok=True)
        for entry in staging.iterdir():
            destination = prebuilt / entry.name
            if destination.is_symlink() or destination.exists():
                destination.unlink()
            if entry.is_symlink():
                destination.symlink_to(os.readlink(entry))
            elif entry.is_file():
                os.replace(entry, destination)
        if not binary.is_file():
            raise ModelStartupError("Precompiled CUDA llama-server was not extracted.")
        marker.write_text(CUDA_RELEASE_SHA256, encoding="utf-8")
    print("[RMM model] ready: prebuilt CUDA server from " + CUDA_RELEASE_SOURCE, flush=True)
    return binary


def _ensure_llama_server_binary(cache_root: Path) -> Path:
    """Build a pinned, compatible upstream llama-server with CUDA when needed."""
    chosen = os.environ.get("RMM_LLAMA_SERVER_BIN", "").strip()
    if chosen:
        binary = Path(chosen).expanduser().resolve()
        if not binary.is_file():
            raise ModelStartupError("RMM_LLAMA_SERVER_BIN does not exist: " + str(binary))
        return binary
    # Fast default: do not compile ~100+ CUDA source files in Colab T4.
    # A manually requested source build is still available for unsupported
    # CUDA runtimes or users who do not trust third-party prebuilt releases.
    if os.environ.get("RMM_BUILD_LLAMA_FROM_SOURCE", "").strip() != "1":
        return _ensure_pinned_cuda_binary(cache_root)
    print("[RMM model] explicit source compilation requested", flush=True)
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
        "-DGGML_CUDA_FA=OFF", "-DCMAKE_CUDA_ARCHITECTURES=75",
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
    # Packaged llama.cpp shared libraries live next to the server executable.
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = (str(binary.parent) + os.pathsep +
                              env.get("LD_LIBRARY_PATH", ""))
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            argv, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
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
