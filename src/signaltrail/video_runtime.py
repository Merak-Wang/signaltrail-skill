"""托管跨平台的 CPU 配音模型与视频运行工具。"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import httpx

from .config import project_root

# 名称来自 sherpa-onnx v2.0.1 的正式发行资产，均包含 TTS 可执行文件。
_SHERPA_PACKAGES = {
    ("Windows", "x86_64"): "sherpa-onnx-v2.0.1-win-x64-shared-MT-Release",
    ("Windows", "aarch64"): "sherpa-onnx-v2.0.1-win-arm64-shared-MT-Release",
    ("Linux", "x86_64"): "sherpa-onnx-v2.0.1-linux-x64-shared",
    ("Linux", "aarch64"): "sherpa-onnx-v2.0.1-linux-aarch64-shared-cpu",
    ("Darwin", "x86_64"): "sherpa-onnx-v2.0.1-osx-x64-shared",
    ("Darwin", "aarch64"): "sherpa-onnx-v2.0.1-osx-arm64-shared",
}
_FFMPEG_BINARIES = {
    ("Windows", "x86_64"): "ffmpeg-win-x86_64-v7.1.exe",
    ("Linux", "x86_64"): "ffmpeg-linux-x86_64-v7.0.2",
    ("Linux", "aarch64"): "ffmpeg-linux-aarch64-v7.0.2",
    ("Darwin", "x86_64"): "ffmpeg-macos-x86_64-v7.1",
    ("Darwin", "aarch64"): "ffmpeg-macos-aarch64-v7.1",
}
_SHERPA_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/"
_MODEL_NAME = "vits-melo-tts-zh_en"
_MODEL_RELEASE = "https://huggingface.co/csukuangfj/vits-melo-tts-zh_en/resolve/main/"
_MODEL_FILES = ("LICENSE", "model.int8.onnx", "tokens.txt", "lexicon.txt", "date.fst", "number.fst",
                "phone.fst", "new_heteronym.fst")
_FFMPEG_RELEASE = "https://raw.githubusercontent.com/imageio/imageio-binaries/master/ffmpeg/"



def register_voice(profile_path: Path, data_dir: Path, *, make_default: bool = False) -> Path:
    """处理：导入音色说明及参考录音，保存可整体复制的相对路径音色包。
    输入：本地音色说明、数据根及默认选择；参考录音相对于说明文件定位。
    输出：托管音色说明路径，参考录音复制到同目录并使用相对路径。
    """
    profile_path = profile_path.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    name = profile["name"]
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("Voice name must be a directory name")
    target = data_dir / "video-runtime" / "voices" / name
    target.mkdir(parents=True, exist_ok=True)
    for reference in profile["references"]:
        source = (profile_path.parent / reference["audio"]).resolve()
        destination = target / (reference["id"] + source.suffix)
        if source != destination.resolve():
            shutil.copy2(source, destination)
        reference["audio"] = destination.name
    saved = target / "profile.json"
    saved.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if make_default:
        (target.parent / "default.json").write_text(
            json.dumps({"name": name}, ensure_ascii=False) + "\n", encoding="utf-8")
    return saved


def load_voice(data_dir: Path, voice: str | Path | None = None,
               reference_id: str | None = None) -> dict:
    """处理：解析名称、环境变量或默认音色，在内存中展开参考音频路径。
    输入：数据根、可选音色名称或路径和参考编号。
    输出：参考音频路径已展开的音色配置；未注册时可使用本机已有参考音色。
    """
    voices = data_dir / "video-runtime" / "voices"
    selected = voice or os.environ.get("SIGNALTRAIL_VOICE")
    if not selected and (voices / "default.json").is_file():
        selected = json.loads((voices / "default.json").read_text(encoding="utf-8"))["name"]
    if not selected:
        selected = project_root() / "assets" / "tts" / "reference" / "profile.json"
        if not selected.is_file():
            raise ValueError(
                "No default voice is configured; create a profile using "
                "assets/tts/profile.example.json, then run "
                "signaltrail slides voice-setup --profile PROFILE.json --default"
            )
    path = Path(selected)
    if not path.is_file():
        path = voices / str(selected) / "profile.json"
        if not path.is_file() and str(selected) == "reference":
            path = project_root() / "assets" / "tts" / "reference" / "profile.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    for reference in profile["references"]:
        reference["audio"] = str((path.parent / reference["audio"]).resolve())
    profile["reference_id"] = reference_id or profile.get(
        "reference_id", profile["references"][0]["id"])
    if profile["reference_id"] not in {r["id"] for r in profile["references"]}:
        raise ValueError("Unknown voice reference_id: " + profile["reference_id"])
    return profile



def prepare_zipvoice_english_lexicon(model_dir: Path) -> Path:
    """处理：将公共英文词典转换成 ZipVoice 的单字符音标词典。
    输入：模型目录中的官方英文词典与 ZipVoice token 表，保留来源文件不变。
    输出：仅含单词条目的专用词典；未知音标明确报错，避免原生前端静默漏音。
    """
    source = model_dir / "lexicon-en-us.txt"
    target = model_dir / "lexicon-en-us-zipvoice.txt"
    tokens_path = model_dir / "tokens.txt"
    if target.is_file() and target.stat().st_mtime_ns >= max(
        source.stat().st_mtime_ns, tokens_path.stat().st_mtime_ns
    ):
        return target
    tokens = {line.rsplit(maxsplit=1)[0] for line in tokens_path.read_text(
        encoding="utf-8").splitlines() if line.strip()}
    entries = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if "||" not in line or line.lstrip().startswith("#"):
            continue
        word, pronunciation = line.split("||", 1)
        word = word.strip()
        if len(word.split()) != 1:
            continue
        phones = [char for char in pronunciation if not char.isspace()]
        unknown = set(phones) - tokens
        if unknown:
            raise ValueError(f"Unknown ZipVoice phonemes for {word}: {sorted(unknown)}")
        entries.append(word + " " + " ".join(phones))
    target.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return target


def video_platform() -> tuple[str, str]:
    """处理：把系统提供的架构别名归一到已发行的桌面平台。
    输入：当前操作系统和 CPU 架构；不探测或更改系统配置。
    输出：供官方预编译工具清单索引使用的系统、架构二元组。
    """
    machine = platform.machine().lower()
    architecture = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    return platform.system(), architecture


def ensure_video_runtime(
    data_dir: Path, *, proxy: str | None = None, tts_executable: Path | None = None,
    model_dir: Path | None = None, ffmpeg: str | Path | None = None,
    device: str | None = None, voice: str | Path | None = None,
    reference_id: str | None = None, prepare_browser: bool = True,
) -> dict:
    """处理：按选中音色准备 Qwen 或旧引擎，统一提供视频运行工具。
    输入：数据根、已注册或本机已有音色与可选设备配置。
    输出：真实设备探测结果、语音模型、参考音色和本地编码工具。
    """
    profile = load_voice(data_dir, voice, reference_id)
    if profile["engine"] != "qwen3":
        legacy_device = device or os.environ.get("SIGNALTRAIL_TTS_DEVICE", "cpu")
        result = _ensure_legacy_runtime(
            data_dir, proxy=proxy, tts_executable=tts_executable, model_dir=model_dir,
            ffmpeg=ffmpeg, device="cpu" if legacy_device == "auto" else legacy_device,
            voice=voice, reference_id=reference_id, prepare_browser=prepare_browser)
        return {**result, "engine": profile["engine"], "requested_device": legacy_device,
                "device_name": result["provider"]}
    from .qwen_runtime import ensure_qwen_runtime

    result = ensure_qwen_runtime(data_dir, profile, device=device,
                                 tts_executable=tts_executable, model_dir=model_dir, proxy=proxy)
    root = data_dir / "video-runtime"
    ffmpeg_value = ffmpeg or os.environ.get("SIGNALTRAIL_FFMPEG") or shutil.which("ffmpeg")
    name = _FFMPEG_BINARIES.get(video_platform())
    executable = Path(ffmpeg_value) if ffmpeg_value else root / "ffmpeg" / str(name)
    if not executable.is_file():
        if ffmpeg_value:
            raise FileNotFoundError(executable)
        if name is None:
            raise RuntimeError(f"No managed FFmpeg binary for {video_platform()}")
        executable.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(proxy=proxy, follow_redirects=True, timeout=120) as client:
            _download(client, _FFMPEG_RELEASE + name, executable)
        executable.chmod(executable.stat().st_mode | 0o111)
    if prepare_browser:
        _ensure_browser(proxy)
    return {**result, "ffmpeg": executable.resolve()}


def cpu_video_runtime(runtime: dict) -> dict:
    """处理：为失败的 Qwen GPU 合成准备 CPU 重试程序，保留当前音色与模型。
    输入：已经准备的原生运行配置。
    输出：可直接重试整页的 CPU 配置，不修改全局设备设置。
    """
    from .qwen_runtime import cpu_qwen_runtime

    return cpu_qwen_runtime(runtime)


def _ensure_legacy_runtime(
    data_dir: Path, *, proxy: str | None = None, tts_executable: Path | None = None,
    model_dir: Path | None = None, ffmpeg: str | Path | None = None,
    device: str | None = None, voice: str | Path | None = None,
    reference_id: str | None = None, prepare_browser: bool = True,
) -> dict[str, Path | str]:
    """处理：首次准备便携工具、CPU 中英模型与浏览器，后续直接复用。
    输入：SignalTrail 数据根和可选下载代理；环境变量可指定已有工具与模型路径。
    输出：本地 TTS 可执行文件、模型目录和 FFmpeg 路径，供视频合成直接调用。
    """
    provider = device or os.environ.get("SIGNALTRAIL_TTS_DEVICE", "cpu")
    if provider not in {"cpu", "cuda"}:
        raise ValueError("TTS device must be cpu or cuda")
    profile = load_voice(data_dir, voice, reference_id)
    zipvoice = profile is not None and profile["engine"] == "zipvoice"
    root = data_dir / "video-runtime"
    system_key = video_platform()
    package_name = _SHERPA_PACKAGES.get(system_key)
    executable = "sherpa-onnx-offline-tts" + (".exe" if system_key[0] == "Windows" else "")
    tts_value = tts_executable or os.environ.get("SIGNALTRAIL_TTS_EXECUTABLE")
    model_value = model_dir or os.environ.get("SIGNALTRAIL_TTS_MODEL_DIR")
    if provider == "cuda" and not tts_value:
        raise RuntimeError(
            "CUDA TTS requires a compatible native executable supplied by the harness through "
            "--tts-executable or SIGNALTRAIL_TTS_EXECUTABLE. The harness can choose --device cpu "
            "to use the managed CPU runtime."
        )
    ffmpeg_value = ffmpeg or os.environ.get("SIGNALTRAIL_FFMPEG") or shutil.which("ffmpeg")
    tts = Path(tts_value) if tts_value else root / "sherpa" / str(package_name) / "bin" / executable
    model_name = "zipvoice-distill-fp32" if zipvoice else _MODEL_NAME
    model = Path(model_value) if model_value else root / "model" / model_name
    ffmpeg_name = _FFMPEG_BINARIES.get(system_key)
    ffmpeg = Path(ffmpeg_value) if ffmpeg_value else root / "ffmpeg" / str(ffmpeg_name)
    for value, path in ((tts_value, tts), (model_value, model), (ffmpeg_value, ffmpeg)):
        if value and not path.exists():
            raise FileNotFoundError(path)
    if not tts.is_file() and package_name is None:
        raise RuntimeError(
            f"No managed TTS binary for {system_key}. Set SIGNALTRAIL_TTS_EXECUTABLE "
            "to an existing native sherpa-onnx-offline-tts executable."
        )
    if not ffmpeg.is_file() and ffmpeg_name is None:
        raise RuntimeError(
            f"No managed FFmpeg binary for {system_key}. Set SIGNALTRAIL_FFMPEG "
            "to an existing native FFmpeg executable or put it on PATH."
        )
    model_files = tuple("model.onnx" if name == "model.int8.onnx" and provider == "cuda"
                        else name for name in _MODEL_FILES)
    if zipvoice:
        model_files = ("encoder.onnx", "decoder.onnx", "vocos_24khz.onnx", "tokens.txt",
                       "lexicon.txt", "lexicon-en-us.txt")
    model_ready = (model.is_dir() if model_value
                   else all((model / name).is_file() for name in model_files))
    if not (tts.is_file() and model_ready and ffmpeg.is_file()):
        root.mkdir(parents=True, exist_ok=True)
        with httpx.Client(proxy=proxy, follow_redirects=True, timeout=120) as client:
            if not tts.is_file():
                _install_archive(client, _SHERPA_RELEASE + package_name + ".tar.bz2",
                                 root / "sherpa" / package_name, root / "downloads")
            if not model_ready:
                model.mkdir(parents=True, exist_ok=True)
                if zipvoice:
                    archive_name = "sherpa-onnx-zipvoice-distill-fp32-zh-en-emilia"
                    extracted = root / "model" / archive_name
                    if not extracted.is_dir():
                        _install_archive(client,
                            "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
                            + archive_name + ".tar.bz2", extracted, root / "downloads")
                    for name in ("encoder.onnx", "decoder.onnx", "tokens.txt", "lexicon.txt"):
                        shutil.copy2(extracted / name, model / name)
                    shutil.copytree(extracted / "espeak-ng-data", model / "espeak-ng-data",
                                    dirs_exist_ok=True)
                    for name, release in (("vocos_24khz.onnx", "vocoder-models"),
                                          ("lexicon-en-us.txt", "tts-models")):
                        _download(client, "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                                  + release + "/" + name, model / name)
                else:
                    for name in model_files:
                        if not (model / name).is_file():
                            _download(client, _MODEL_RELEASE + name, model / name)
            if not ffmpeg.is_file():
                ffmpeg.parent.mkdir(exist_ok=True)
                _download(client, _FFMPEG_RELEASE + ffmpeg_name, ffmpeg)
                ffmpeg.chmod(ffmpeg.stat().st_mode | 0o111)
    if zipvoice and (model / "lexicon-en-us.txt").is_file():
        prepare_zipvoice_english_lexicon(model)
    if prepare_browser:
        _ensure_browser(proxy)
    return {"tts_executable": tts.resolve(), "model_dir": model.resolve(),
            "ffmpeg": ffmpeg.resolve(), "provider": provider, "voice_profile": profile}


def _download(client: httpx.Client, url: str, target: Path) -> None:
    """处理：流式下载发行文件，完成后原子替换临时下载。
    输入：下载客户端、官方资产地址和本地缓存路径。
    输出：完整缓存文件；网络中断留下 .part 文件供排查。
    """
    partial = target.with_name(target.name + ".part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with partial.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                output.write(chunk)
    partial.replace(target)


def _install_archive(client: httpx.Client, url: str, target: Path, cache: Path) -> None:
    """处理：缓存正式发行包，完整解压后将临时目录提升为可复用安装目录。
    输入：下载客户端、归档地址、安装目录与归档缓存目录。
    输出：完整工具或模型目录；中断的下载及解压临时目录留存。
    """
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / url.rsplit("/", 1)[1]
    if not archive.is_file():
        _download(client, url, archive)
    staging = cache / (archive.name + ".extracting")
    staging.mkdir(exist_ok=True)
    with tarfile.open(archive) as package:
        if hasattr(tarfile, "data_filter"):
            package.extractall(staging, filter="data")
        else:
            # Python 3.11.0—3.11.7 没有 data_filter，仅接受归档根内的普通文件与目录。
            members = [member for member in package.getmembers()
                       if (member.isfile() or member.isdir())
                       and (staging / member.name).resolve().is_relative_to(staging.resolve())]
            package.extractall(staging, members=members)
    target.parent.mkdir(parents=True, exist_ok=True)
    (staging / target.name).rename(target)


def _ensure_browser(proxy: str | None, executable_path: str | None = None) -> None:
    """处理：检查 Playwright 管理的 Chromium，缺失时调用现有安装器准备一次。
    输入：当前 Python 环境和可选代理；已存在的浏览器无需联网。
    输出：视频截图可用的 Chromium；安装失败交由 CLI 显示具体错误。
    """
    executable = os.environ.get("SIGNALTRAIL_BROWSER_EXECUTABLE")
    if executable:
        if not Path(executable).is_file():
            raise FileNotFoundError(executable)
        return
    if executable_path is not None:
        if Path(executable_path).is_file():
            return
    else:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as browser:
            if Path(browser.chromium.executable_path).is_file():
                # 显式准备时完成启动验证，渲染则复用其已有驱动上下文。
                instance = browser.chromium.launch(channel="chromium")
                instance.close()
                return
    environment = os.environ.copy()
    if proxy:
        environment.update({"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy})
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--no-shell", "chromium"],
        env=environment, capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
