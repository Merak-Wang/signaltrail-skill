import io
import tarfile

import pytest

from signaltrail import video_runtime


@pytest.mark.parametrize(("system", "machine", "expected"), [
    ("Windows", "AMD64", "sherpa-onnx-v2.0.1-win-x64-shared-MT-Release"),
    ("Windows", "ARM64", "sherpa-onnx-v2.0.1-win-arm64-shared-MT-Release"),
    ("Linux", "x86_64", "sherpa-onnx-v2.0.1-linux-x64-shared"),
    ("Linux", "aarch64", "sherpa-onnx-v2.0.1-linux-aarch64-shared-cpu"),
    ("Darwin", "x86_64", "sherpa-onnx-v2.0.1-osx-x64-shared"),
    ("Darwin", "arm64", "sherpa-onnx-v2.0.1-osx-arm64-shared"),
])
def test_runtime_selects_official_native_package(monkeypatch, system, machine, expected):
    monkeypatch.setattr(video_runtime.platform, "system", lambda: system)
    monkeypatch.setattr(video_runtime.platform, "machine", lambda: machine)
    key = video_runtime.video_platform()
    assert video_runtime._SHERPA_PACKAGES[key] == expected
    assert (key in video_runtime._FFMPEG_BINARIES) == (key != ("Windows", "aarch64"))


def test_explicit_local_runtime_reuses_files_without_network(monkeypatch, tmp_path):
    paths = {"tts_executable": tmp_path / "tts", "model_dir": tmp_path / "model",
             "ffmpeg": tmp_path / "ffmpeg"}
    paths["model_dir"].mkdir()
    paths["tts_executable"].touch()
    paths["ffmpeg"].touch()
    for name, key in (("SIGNALTRAIL_TTS_EXECUTABLE", "tts_executable"),
                      ("SIGNALTRAIL_TTS_MODEL_DIR", "model_dir"),
                      ("SIGNALTRAIL_FFMPEG", "ffmpeg")):
        monkeypatch.setenv(name, str(paths[key]))
    monkeypatch.setattr(video_runtime, "_ensure_browser", lambda proxy: None)
    monkeypatch.setattr(video_runtime, "load_voice", lambda *args: None)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("A configured local runtime must remain offline")

    monkeypatch.setattr(video_runtime.httpx, "Client", unexpected_download)
    assert video_runtime._ensure_legacy_runtime(tmp_path) == {
        **paths, "provider": "cpu", "voice_profile": None}


def test_windows_arm64_without_native_ffmpeg_stops_before_download(monkeypatch, tmp_path):
    monkeypatch.setattr(video_runtime, "video_platform", lambda: ("Windows", "aarch64"))
    monkeypatch.setattr(video_runtime.shutil, "which", lambda name: None)
    for name in ("SIGNALTRAIL_TTS_EXECUTABLE", "SIGNALTRAIL_TTS_MODEL_DIR", "SIGNALTRAIL_FFMPEG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(video_runtime, "load_voice", lambda *args: None)
    with pytest.raises(RuntimeError, match="No managed FFmpeg binary"):
        video_runtime._ensure_legacy_runtime(tmp_path)


def test_cuda_requires_harness_provided_native_runtime(monkeypatch, tmp_path):
    monkeypatch.delenv("SIGNALTRAIL_TTS_EXECUTABLE", raising=False)
    monkeypatch.setattr(video_runtime, "load_voice", lambda *args: None)
    with pytest.raises(RuntimeError, match="supplied by the harness"):
        video_runtime._ensure_legacy_runtime(tmp_path, device="cuda")


def test_install_adds_platform_package_beside_existing_runtime(tmp_path):
    cache = tmp_path / "downloads"
    cache.mkdir()
    runtime = tmp_path / "sherpa"
    (runtime / "existing-platform").mkdir(parents=True)
    content = b"native executable"
    with tarfile.open(cache / "new-platform.tar.bz2", "w:bz2") as archive:
        member = tarfile.TarInfo("new-platform/bin/tts")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    video_runtime._install_archive(
        None, "https://example.test/new-platform.tar.bz2", runtime / "new-platform", cache
    )
    assert (runtime / "new-platform" / "bin" / "tts").read_bytes() == content
    assert (runtime / "existing-platform").is_dir()


def test_registered_voice_pack_survives_relocation(tmp_path):
    import json
    import shutil

    source = tmp_path / "source"
    source.mkdir()
    (source / "reference.wav").write_bytes(b"reference audio")
    profile = {"name": "test-voice", "engine": "zipvoice", "references": [
        {"id": "neutral-a", "audio": "reference.wav", "text": "Hello", "language": "en"}]}
    path = source / "voice.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    first = tmp_path / "first"
    saved = video_runtime.register_voice(path, first, make_default=True)
    assert json.loads(saved.read_text())["references"][0]["audio"] == "neutral-a.wav"
    second = tmp_path / "second"
    shutil.copytree(first, second)
    loaded = video_runtime.load_voice(second)
    assert loaded["reference_id"] == "neutral-a"
    assert loaded["references"][0]["audio"] == str(
        (second / "video-runtime/voices/test-voice/neutral-a.wav").resolve())


def test_render_browser_check_reuses_supplied_executable(monkeypatch, tmp_path):
    executable = tmp_path / "chromium"
    executable.touch()

    def unexpected_install(*args, **kwargs):
        raise AssertionError("An existing render browser requires no installer")

    monkeypatch.setattr(video_runtime.subprocess, "run", unexpected_install)
    monkeypatch.delenv("SIGNALTRAIL_BROWSER_EXECUTABLE", raising=False)
    video_runtime._ensure_browser(None, str(executable))


def test_zipvoice_english_lexicon_preserves_initials_vowels_and_single_word_the(tmp_path):
    (tmp_path / "tokens.txt").write_text(
        "l 0\nˈ 1\na 2\nɪ 3\nb 4\nɹ 5\nɛ 6\ni 7\nː 8\nv 9\nn 10\nŋ 11\nð 12\nə 13\n",
        encoding="utf-8")
    original = "library || lˈ a ɪ b ɹ ɛ ɹ i\nevening || ˈ iː v n ɪ ŋ\nthe || ð ə\n"
    original += "the Angeles || ð i\n"
    (tmp_path / "lexicon-en-us.txt").write_text(original, encoding="utf-8")
    converted = video_runtime.prepare_zipvoice_english_lexicon(tmp_path)
    lexicon = {line.split()[0]: line.split()[1:] for line in
               converted.read_text(encoding="utf-8").splitlines()}
    assert lexicon["library"] == ["l", "ˈ", "a", "ɪ", "b", "ɹ", "ɛ", "ɹ", "i"]
    assert lexicon["evening"] == ["ˈ", "i", "ː", "v", "n", "ɪ", "ŋ"]
    assert lexicon["the"] == ["ð", "ə"]
    assert (tmp_path / "lexicon-en-us.txt").read_text(encoding="utf-8") == original


@pytest.mark.parametrize(("system", "provider", "asset"), [
    (("Windows", "x86_64"), "cuda", "win-cuda-12.4-x64.zip"),
    (("Windows", "aarch64"), "vulkan", "win-vulkan-arm64.zip"),
    (("Linux", "x86_64"), "cuda", "ubuntu-cuda-12.8-x64.tar.gz"),
    (("Linux", "aarch64"), "cpu", "ubuntu-arm64.tar.gz"),
    (("Darwin", "x86_64"), "cpu", "macos-x64.tar.gz"),
    (("Darwin", "aarch64"), "metal", "macos-arm64.tar.gz"),
])
def test_qwen_package_uses_published_asset(monkeypatch, tmp_path, system, provider, asset):
    from signaltrail import qwen_runtime

    urls = []

    def unpack(url, target, proxy):
        urls.append(url)
        target.mkdir(parents=True)
        (target / ("llama-tts.exe" if system[0] == "Windows" else "llama-tts")).touch()

    monkeypatch.setattr(qwen_runtime, "_unpack", unpack)
    program = qwen_runtime._program(tmp_path, system, provider, None)
    assert program.is_file()
    assert urls == [qwen_runtime._RELEASE + "llama-b11981-bin-" + asset]


@pytest.mark.parametrize("has_gpu", [True, False])
def test_qwen_auto_uses_native_probe_and_falls_back_to_cpu(monkeypatch, tmp_path, has_gpu):
    from signaltrail import qwen_runtime

    model = tmp_path / "models"
    model.mkdir()
    for name in (qwen_runtime.MODEL_NAME, qwen_runtime.MMPROJ_NAME):
        (model / name).touch()
    monkeypatch.setattr(video_runtime, "video_platform", lambda: ("Windows", "x86_64"))
    monkeypatch.setattr(qwen_runtime.shutil, "which", lambda name: "nvidia-smi")
    programs = []

    def program(root, system, provider, proxy):
        path = tmp_path / (provider + ".exe")
        path.touch()
        programs.append(provider)
        return path

    monkeypatch.setattr(qwen_runtime, "_program", program)
    monkeypatch.setattr(qwen_runtime, "_unpack", lambda *args: None)
    monkeypatch.setattr(qwen_runtime, "_probe", lambda *args: (
        [("CUDA0", "test GPU")] if has_gpu else [], "native probe"))
    profile = {"engine": "qwen3", "name": "reference"}
    result = qwen_runtime.ensure_qwen_runtime(tmp_path, profile, model_dir=model)
    assert result["requested_device"] == "auto"
    assert result["voice_profile"] == profile
    assert result["provider"] == ("cuda" if has_gpu else "cpu")
    assert result["device_name"] == ("CUDA0" if has_gpu else "none")
    if has_gpu:
        retry = qwen_runtime.cpu_qwen_runtime(result)
        assert retry["provider"] == "cpu" and retry["voice_profile"] == profile
        assert retry["model_path"] == result["model_path"]
    else:
        assert programs == ["cuda", "vulkan", "cpu"]
        assert result["fallback_reason"]


def test_local_reference_profile_is_fallback_when_present(monkeypatch, tmp_path):
    import json

    assets = tmp_path / "assets/tts/reference"
    assets.mkdir(parents=True)
    profile = {"name": "reference", "engine": "qwen3", "references": [
        {"id": "neutral-a", "audio": "reference.wav", "text": "reference", "language": "zh"}]}
    (assets / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(video_runtime, "project_root", lambda: tmp_path)
    monkeypatch.delenv("SIGNALTRAIL_VOICE", raising=False)
    result = video_runtime.load_voice(tmp_path / "data")
    assert result["engine"] == "qwen3"
    assert result["references"][0]["audio"] == str((assets / "reference.wav").resolve())


def test_missing_voice_reports_import_command_before_runtime_download(monkeypatch, tmp_path):
    from signaltrail import qwen_runtime

    monkeypatch.setattr(video_runtime, "project_root", lambda: tmp_path)
    monkeypatch.delenv("SIGNALTRAIL_VOICE", raising=False)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Voice must be configured before runtime preparation")

    monkeypatch.setattr(qwen_runtime, "ensure_qwen_runtime", unexpected_download)
    monkeypatch.setattr(video_runtime.httpx, "Client", unexpected_download)
    with pytest.raises(ValueError, match=r"slides voice-setup --profile PROFILE.json --default"):
        video_runtime.ensure_video_runtime(tmp_path / "data")


def test_supplied_cpu_program_auto_never_downloads_cuda_libraries(monkeypatch, tmp_path):
    from signaltrail import qwen_runtime

    executable = tmp_path / "cpu-tts.exe"
    executable.touch()
    for name in (qwen_runtime.MODEL_NAME, qwen_runtime.MMPROJ_NAME):
        (tmp_path / name).touch()
    monkeypatch.setattr(video_runtime, "video_platform", lambda: ("Windows", "x86_64"))
    monkeypatch.setattr(qwen_runtime.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(qwen_runtime, "_probe", lambda *args: ([], "CPU-only executable"))

    def unexpected_download(*args):
        raise AssertionError("Explicit CPU executable must not trigger CUDA library downloads")

    monkeypatch.setattr(qwen_runtime, "_unpack", unexpected_download)
    result = qwen_runtime.ensure_qwen_runtime(
        tmp_path, {"engine": "qwen3"}, model_dir=tmp_path, tts_executable=executable)
    assert result["provider"] == "cpu"
    assert result["tts_executable"] == executable
    assert "CPU-only executable" in result["fallback_reason"]


def test_probe_excludes_software_vulkan_devices(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from signaltrail import qwen_runtime

    listing = (b"Available devices:\n  Vulkan0: llvmpipe (LLVM 19)\n"
               b"  Vulkan1: lavapipe software renderer\n  Vulkan2: SwiftShader Device\n"
               b"  Vulkan3: NVIDIA GeForce RTX 4060 Laptop GPU\n")
    monkeypatch.setattr(qwen_runtime.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=listing, stderr=b"", returncode=0))
    devices, _ = qwen_runtime._probe(tmp_path / "llama-tts")
    assert devices == [("Vulkan3", "NVIDIA GeForce RTX 4060 Laptop GPU")]


@pytest.mark.parametrize("missing_library", [False, True])
def test_managed_cuda_repairs_only_missing_library_not_hidden_devices(
    monkeypatch, tmp_path, missing_library
):
    from signaltrail import qwen_runtime

    for name in (qwen_runtime.MODEL_NAME, qwen_runtime.MMPROJ_NAME):
        (tmp_path / name).touch()
    executable = tmp_path / "llama-tts.exe"
    executable.touch()
    monkeypatch.setattr(video_runtime, "video_platform", lambda: ("Windows", "x86_64"))
    monkeypatch.setattr(qwen_runtime.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(qwen_runtime, "_program", lambda *args: executable)
    repairs = []

    def unpack(url, target, proxy):
        repairs.append(url)

    def probe(program, libraries=None):
        if libraries is not None:
            return [("CUDA0", "test GPU")], "repaired CUDA library"
        return [], ("failed to load ggml-cuda.dll" if missing_library else "Available devices:")

    monkeypatch.setattr(qwen_runtime, "_unpack", unpack)
    monkeypatch.setattr(qwen_runtime, "_probe", probe)
    result = qwen_runtime.ensure_qwen_runtime(tmp_path, {"engine": "qwen3"}, model_dir=tmp_path)
    assert result["provider"] == ("cuda" if missing_library else "cpu")
    assert len(repairs) == int(missing_library)
