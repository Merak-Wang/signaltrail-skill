"""准备 Qwen3 原生程序与模型，以实际设备探测选择 GPU 或 CPU。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import httpx

VERSION = "b11981"
MODEL_NAME = "Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf"
MMPROJ_NAME = "mmproj-Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf"
_RELEASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/"
_MODELS = "https://huggingface.co/ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF/resolve/main/"
# 固定发行版实际提供的资产；macOS 同一程序包支持 CPU 和 Metal。
_PACKAGES = {
    ("Windows", "x86_64"): {"cpu": "win-cpu-x64.zip", "cuda": "win-cuda-12.4-x64.zip",
                              "vulkan": "win-vulkan-x64.zip"},
    ("Windows", "aarch64"): {"cpu": "win-cpu-arm64.zip", "cuda": "win-cuda-13.4-arm64.zip",
                              "vulkan": "win-vulkan-arm64.zip"},
    ("Linux", "x86_64"): {"cpu": "ubuntu-x64.tar.gz", "cuda": "ubuntu-cuda-12.8-x64.tar.gz",
                            "vulkan": "ubuntu-vulkan-x64.tar.gz"},
    ("Linux", "aarch64"): {"cpu": "ubuntu-arm64.tar.gz",
                             "cuda": "ubuntu-cuda-13.4-arm64.tar.gz",
                             "vulkan": "ubuntu-vulkan-arm64.tar.gz"},
    ("Darwin", "x86_64"): {"cpu": "macos-x64.tar.gz", "metal": "macos-x64.tar.gz"},
    ("Darwin", "aarch64"): {"cpu": "macos-arm64.tar.gz", "metal": "macos-arm64.tar.gz"},
}
_CUDA_RUNTIME = {
    ("Windows", "x86_64"): "cudart-llama-bin-win-cuda-12.4-x64.zip",
    ("Windows", "aarch64"): "cudart-llama-bin-win-cuda-13.4-arm64.zip",
    ("Linux", "x86_64"): f"cudart-llama-{VERSION}-bin-ubuntu-cuda-12.8-x64.tar.gz",
    ("Linux", "aarch64"): f"cudart-llama-{VERSION}-bin-ubuntu-cuda-13.4-arm64.tar.gz",
}


def _unpack(url: str, target: Path, proxy: str | None) -> None:
    """处理：下载并展开官方原生包，保留下载缓存供其他设备配置复用。
    输入：发行资产地址、目标目录及可选代理。
    输出：展开的程序或 app-local 运行库，不修改系统路径。
    """
    from .video_runtime import _download

    archive = target.parent / "downloads" / url.rsplit("/", 1)[1]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        with httpx.Client(proxy=proxy, follow_redirects=True, timeout=180) as client:
            _download(client, url, archive)
    target.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            package.extractall(target)
    else:
        with tarfile.open(archive) as package:
            if hasattr(tarfile, "data_filter"):
                package.extractall(target, filter="data")
            else:
                members = [member for member in package.getmembers()
                           if (member.isfile() or member.isdir()) and
                           (target / member.name).resolve().is_relative_to(target.resolve())]
                package.extractall(target, members=members)


def _program(root: Path, system: tuple[str, str], provider: str,
             proxy: str | None) -> Path:
    """处理：按已发布的平台矩阵准备选定后端的 llama-tts。
    输入：运行根、系统架构、设备后端与可选代理。
    输出：本地原生程序路径，相同配置直接复用缓存。
    """
    suffix = _PACKAGES.get(system, {}).get(provider)
    if suffix is None:
        raise RuntimeError(f"No Qwen native package for {system} / {provider}")
    label = suffix.replace(".tar.gz", "").removesuffix(".zip")
    directory = root / ("llama-" + VERSION + "-" + label)
    filename = "llama-tts.exe" if system[0] == "Windows" else "llama-tts"
    found = next(directory.rglob(filename), None) if directory.exists() else None
    if found is None:
        _unpack(_RELEASE + f"llama-{VERSION}-bin-" + suffix, directory, proxy)
        found = next(directory.rglob(filename))
    return found.resolve()


def _probe(executable: Path, libraries: Path | None = None) -> tuple[list[tuple[str, str]], str]:
    """处理：调用原生程序列举真实可用设备，收集加载失败原因。
    输入：程序路径与可选的进程私有运行库目录。
    输出：设备编号及名称列表、原生诊断；不进行语音推理。
    """
    environment = os.environ.copy()
    paths = [str(executable.parent), str(executable.parent.parent / "lib")]
    if libraries and libraries.exists():
        paths += sorted({str(p.parent) for p in libraries.rglob("*") if p.is_file()})
    variable = ("PATH" if os.name == "nt" else
                "DYLD_LIBRARY_PATH" if os.uname().sysname == "Darwin" else "LD_LIBRARY_PATH")
    environment[variable] = os.pathsep.join(paths + [environment.get(variable, "")])
    result = subprocess.run([str(executable), "--list-devices"], capture_output=True,
                            env=environment, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    devices = re.findall(r"^\s*((?:CUDA|Vulkan|Metal)\d*)\s*:\s*(.+)$", log, re.MULTILINE)
    devices = [(key, label) for key, label in devices if not re.search(
        r"llvmpipe|lavapipe|software renderer|SwiftShader", label, re.IGNORECASE)]
    return devices, log


def ensure_qwen_runtime(data_dir: Path, profile: dict, *, device: str | None = None,
                        tts_executable: Path | None = None, model_dir: Path | None = None,
                        proxy: str | None = None) -> dict:
    """处理：准备 Q8 模型并探测设备，自动选择可用 GPU，失败时保留原因回落 CPU。
    输入：数据根、已展开参考音频的音色、设备选择与可选现成程序和模型目录。
    输出：供合成模块使用的模型、原生设备与 CPU 重试参数。
    """
    from .video_runtime import _download, video_platform

    requested = device or os.environ.get("SIGNALTRAIL_TTS_DEVICE", "auto")
    if requested not in {"auto", "cpu", "cuda", "vulkan", "metal"}:
        raise ValueError("TTS device must be auto, cpu, cuda, vulkan or metal")
    system = video_platform()
    root = data_dir / "video-runtime" / "qwen3"
    model = Path(model_dir or os.environ.get("SIGNALTRAIL_TTS_MODEL_DIR") or root / "model")
    model.mkdir(parents=True, exist_ok=True)
    for name in (MODEL_NAME, MMPROJ_NAME):
        if not (model / name).is_file():
            with httpx.Client(proxy=proxy, follow_redirects=True, timeout=180) as client:
                _download(client, _MODELS + name, model / name)
    supplied = tts_executable or os.environ.get("SIGNALTRAIL_TTS_EXECUTABLE")
    if supplied and not Path(supplied).is_file():
        raise FileNotFoundError(supplied)
    choices = [requested]
    if requested == "auto":
        choices = (["metal"] if system[0] == "Darwin" else
                   (["cuda"] if shutil.which("nvidia-smi") else []) + ["vulkan"])
    choices += ["cpu"] if "cpu" not in choices else []
    diagnostics = []
    selected, device_name, libraries = "cpu", "none", None
    for choice in choices:
        if choice not in _PACKAGES.get(system, {}) and not supplied:
            continue
        try:
            executable = (Path(supplied).resolve() if supplied
                          else _program(root, system, choice, proxy))
            if choice == "cpu":
                selected, device_name = "cpu", "none"
                break
            devices, log = _probe(executable)
            matches = [(key, label) for key, label in devices if key.lower().startswith(choice)]
            missing_library = re.search(
                r"failed to load|cannot open shared object|specified module could not be found",
                log, re.IGNORECASE)
            if (not matches and missing_library and not supplied and choice == "cuda"
                    and system in _CUDA_RUNTIME):
                libraries = root / "cuda-libraries"
                marker = next(libraries.rglob("*cublas*"), None) if libraries.exists() else None
                if marker is None:
                    _unpack(_RELEASE + _CUDA_RUNTIME[system], libraries, proxy)
                devices, log = _probe(executable, libraries)
                matches = [(key, label) for key, label in devices if key.lower().startswith(choice)]
            if matches:
                selected, device_name = choice, matches[0][0]
                break
            diagnostics.append(f"{choice}: {log[-1500:]}")
        except (OSError, RuntimeError, httpx.HTTPError, subprocess.TimeoutExpired) as exc:
            diagnostics.append(f"{choice}: {exc}")
    else:
        raise RuntimeError("No runnable Qwen native package: " + "\n".join(diagnostics))
    return {"engine": "qwen3", "model_dir": model.resolve(),
            "model_path": (model / MODEL_NAME).resolve(),
            "mmproj_path": (model / MMPROJ_NAME).resolve(),
            "tts_executable": executable, "provider": selected, "device_name": device_name,
            "requested_device": requested, "voice_profile": profile, "data_dir": data_dir.resolve(),
            "library_dir": libraries if selected == "cuda" else None,
            "fallback_reason": "\n".join(diagnostics),
            "proxy": proxy}


def cpu_qwen_runtime(runtime: dict) -> dict:
    """处理：GPU 合成失败后按需准备 CPU 程序，复用模型与选中参考。
    输入：本次已准备的运行配置，包含数据根和语音资产。
    输出：明确使用 CPU 的新配置，交由合成模块重试整页。
    """
    from .video_runtime import video_platform

    result = dict(runtime)
    root = Path(runtime["data_dir"]) / "video-runtime" / "qwen3"
    result.update(tts_executable=_program(root, video_platform(), "cpu", runtime.get("proxy")),
                  provider="cpu", device_name="none", library_dir=None)
    return result
