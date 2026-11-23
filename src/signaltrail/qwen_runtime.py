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


def _installation_model_dirs(program: Path | None) -> list[Path]:
    """处理：由已指定的原生程序定位近邻模型目录。
    输入：实际存在的常驻 worker 或原生程序路径。
    输出：程序所在目录、相邻 model 目录和所属的标准 Qwen 安装目录。
    """
    if program is None or not program.is_file():
        return []
    directory = program.resolve().parent
    candidates = [directory, directory / "model", directory.parent / "model"]
    candidates.extend(
        parent / "model" for parent in directory.parents
        if parent.name == "qwen3" and parent.parent.name == "video-runtime"
    )
    return candidates


def _has_model_pair(directory: Path) -> bool:
    """处理：检查同一目录中有无两件已完成的 Qwen Q8 模型。
    输入：受限发现范围内的运行缓存或原生安装目录。
    输出：两件固定文件均可读且带 GGUF 文件头时返回真。
    """
    try:
        for name in (MODEL_NAME, MMPROJ_NAME):
            path = directory / name
            if not path.is_file():
                return False
            with path.open("rb") as handle:
                header = handle.read(24)
            if len(header) < 24 or header[:4] != b"GGUF":
                return False
    except OSError:
        return False
    return True


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
    supplied = tts_executable or os.environ.get("SIGNALTRAIL_TTS_EXECUTABLE")
    native = Path(supplied).expanduser() if supplied else None
    if native is not None and not native.is_file():
        raise FileNotFoundError(supplied)
    from .config import resolve_signaltrail_home
    from .runtime import load_bound_data_root

    home = resolve_signaltrail_home()
    bound = load_bound_data_root(home) or home
    root = data_dir / "video-runtime" / "qwen3"
    explicit_worker = os.environ.get("SIGNALTRAIL_TTS_WORKER")
    worker_path = Path(explicit_worker).expanduser() if explicit_worker else None
    explicit_model = model_dir or os.environ.get("SIGNALTRAIL_TTS_MODEL_DIR")
    model = None
    if not explicit_model:
        model_candidates = [
            root / "model",
            *_installation_model_dirs(worker_path),
            *_installation_model_dirs(native),
            bound / "video-runtime" / "qwen3" / "model",
        ]
        model = next((path for path in dict.fromkeys(model_candidates) if _has_model_pair(path)),
                     None)
    if model is None:
        # 自动发现从不补写外部安装。显式路径沿用原先的下载位置。
        model = Path(explicit_model).expanduser() if explicit_model else root / "model"
        missing = [name for name in (MODEL_NAME, MMPROJ_NAME) if not (model / name).is_file()]
        if missing:
            model.mkdir(parents=True, exist_ok=True)
            with httpx.Client(proxy=proxy, follow_redirects=True, timeout=180) as client:
                for name in missing:
                    _download(client, _MODELS + name, model / name)
    filename = "llama-tts-worker.exe" if system[0] == "Windows" else "llama-tts-worker"
    candidates = [root / "worker" / filename, model.parent / "worker" / filename,
                  bound / "video-runtime" / "qwen3" / "worker" / filename]
    if native is not None:
        candidates.insert(1, native.parent / filename)
    if worker_path is not None:
        candidates.insert(0, worker_path)
    worker = next((path.resolve() for path in candidates if path.is_file()), None)
    worker_devices, worker_log = _probe(worker) if worker else ([], "")
    choices = [requested]
    if requested == "auto":
        choices = (["metal"] if system[0] == "Darwin" else
                   (["cuda"] if shutil.which("nvidia-smi") else []) + ["vulkan"])
    if requested == "auto" and worker:
        resident_choices = (["vulkan", "cuda"] if system[0] == "Windows" else choices)
        resident_choices = [choice for choice in resident_choices if any(
            key.lower().startswith(choice) for key, _label in worker_devices)]
        choices = list(dict.fromkeys([*resident_choices, *choices]))
    choices += ["cpu"] if "cpu" not in choices else []
    diagnostics = []
    selected, device_name, libraries = "cpu", "none", None
    resident = False
    for choice in choices:
        if choice not in _PACKAGES.get(system, {}) and native is None:
            continue
        try:
            matches = [(key, label) for key, label in worker_devices
                       if key.lower().startswith(choice)]
            if worker and (matches or choice == "cpu"):
                executable = worker
                selected, device_name = choice, matches[0][0] if matches else "none"
                resident = True
                break
            executable = (native.resolve() if native is not None
                          else _program(root, system, choice, proxy))
            if choice == "cpu":
                selected, device_name = "cpu", "none"
                break
            devices, log = _probe(executable)
            matches = [(key, label) for key, label in devices if key.lower().startswith(choice)]
            missing_library = re.search(
                r"failed to load|cannot open shared object|specified module could not be found",
                log, re.IGNORECASE)
            if (not matches and missing_library and native is None and choice == "cuda"
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
    worker_note = ("Compatible resident worker selected" if resident else
                   "No compatible resident worker; each uncached segment loads the model")
    if worker and not resident:
        worker_note += f". Available worker devices: {worker_devices}. {worker_log[-500:]}"
    return {"tts_worker_executable": worker if resident else None,
            "execution_mode": "resident" if resident else "oneshot", "worker_note": worker_note,
            "engine": "qwen3", "model_dir": model.resolve(),
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
                  provider="cpu", device_name="none", library_dir=None,
                  tts_worker_executable=None, execution_mode="oneshot",
                  worker_note="CPU fallback uses one-shot synthesis")
    return result
