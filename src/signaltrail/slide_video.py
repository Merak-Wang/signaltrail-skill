"""以本地配音的实际时长驱动图文帧，导出 MP4。"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import shutil
import sys
import time
import wave
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Lock
from uuid import uuid4

from bs4 import BeautifulSoup

from .slide_renderer import display_slide_title
from .storage import write_immutable_json
from .utils import read_json, sha256_file, write_json
from .voice_synthesis import VoiceSynthesizer
from .voice_synthesis import run_native as _run

_VIDEO_VIEWPORT = {"width": 1920, "height": 1080}
_VIDEO_SEEK_SCRIPT = """async ([s, i]) => {
    let timer;
    let timedOut;
    try {
        timedOut = await Promise.race([
            window.signaltrailPlayback.seek(s, i).then(() => false),
            new Promise(resolve => {
                timer = setTimeout(() => {
                    document.querySelectorAll('.slide.active figure.active img').forEach(image => {
                        if (image.complete) return;
                        image.classList.add('broken');
                        image.closest('.image-frame')?.classList.add('has-error');
                        image.removeAttribute('srcset');
                        image.removeAttribute('src');
                    });
                    resolve(true);
                }, 30000);
            }),
        ]);
    } finally {
        clearTimeout(timer);
    }
    window.scrollTo(0, 0);
    return timedOut;
}"""


def _source_slides_html(deck_path: Path, data_dir: Path) -> Path:
    """处理：从稿件父级定位正在交付的图文页面。
    输入：图文稿路径和数据根，独立稿件使用其同名 HTML。
    输出：读者直接打开的图文 HTML 路径，供视频原样取景。
    """
    from .narrative_store import load_artifact, parent_path

    record = json.loads(deck_path.read_text(encoding="utf-8"))
    if isinstance(record, dict) and "plan" in record.get("parents", {}):
        deck = load_artifact(deck_path, data_dir, kind="slides-deck")
        plan = load_artifact(parent_path(deck, "plan", data_dir), data_dir, kind="slides-plan")
        if "report" in plan.get("parents", {}):
            report = parent_path(plan, "report", data_dir)
            report_html = report.with_name(report.stem + "-slides.html")
            if report_html.is_file():
                return report_html
            raise FileNotFoundError(f"Rendered report slides HTML is required: {report_html}")
    source = deck_path.with_suffix(".html")
    if not source.is_file():
        raise FileNotFoundError(f"Rendered slides HTML is required: {source}")
    return source


def _progress(stage: str, **details: object) -> None:
    """处理：向终端报告导出进度。
    输入：阶段名称、页码和事件等字段。
    输出：一行标准错误 JSON，供长任务直接观察。
    """
    print(json.dumps({"stage": stage, **details}, ensure_ascii=False), file=sys.stderr, flush=True)


def _matching_video_receipt(path: Path, output: Path, inputs: dict) -> dict | None:
    """处理：核对封装输入及现存成片的字节指纹。
    输入：上次成功导出的回执、目标成片和本轮选出的素材及封装参数。
    输出：返回真正匹配的回执，供相同成片复用和本次图文修订绑定。
    """
    try:
        receipt = read_json(path)
        if (
            isinstance(receipt, dict)
            and receipt.get("inputs") == inputs
            and receipt.get("output_sha256") == sha256_file(output)
        ):
            return receipt
    except (OSError, ValueError):
        pass
    return None


def _process_running(pid: int) -> bool:
    """处理：以只读进程查询判断遗留导出进程是否仍存活。
    输入：旧版锁记录的正整数进程编号。
    输出：进程仍存在或无权查询时返回真，防止绕过旧版持有者。
    """
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return True

    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER：进程已消失。
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0：进程已退出。
    finally:
        kernel.CloseHandle(handle)


def _guard_legacy_export(work: Path) -> None:
    """处理：阻止旧版导出器与新版同时写同一页面缓存。
    输入：已由新版操作系统文件锁保护的缓存目录。
    输出：确认没有活动的旧版持有者，并保留一个让旧版拒绝写入的持久标记。
    """
    path = work / ".export.lock"
    marker = {"kind": "os-lock-migration"}
    if not path.exists():
        try:
            write_immutable_json(path, marker)
            return
        except FileExistsError:
            # 旧版可能恰好在此时取得互斥标记，继续核对其进程。
            pass
    try:
        old = read_json(path)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Cannot verify legacy video export lock {path}") from error
    if old == marker:
        return
    pid = old.get("pid") if isinstance(old, dict) else None
    if type(pid) is not int or not 0 < pid <= 0x7FFFFFFF:
        raise RuntimeError(f"Cannot verify legacy video export lock {path}")
    if _process_running(pid):
        raise RuntimeError(f"Another video export holds legacy lock {path} (PID {pid})")
    write_json(path, marker)


@contextmanager
def _os_file_lock(path: Path) -> Iterator[None]:
    """处理：用本地操作系统的非阻塞文件锁独占资源路径。
    输入：导出或共享语音缓存的稳定锁文件。
    输出：进入上下文时取得锁，退出或进程终止时由操作系统释放。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # 保留稳定的锁文件，避免另一个进程在新文件上取得同名锁。
    with path.open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                # Windows 支持锁定文件末尾后的字节，不需要向文件写入数据。
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise RuntimeError(f"Another video export holds {path}") from error
            raise
        yield


@contextmanager
def _export_lock(work: Path) -> Iterator[None]:
    """处理：串行化共享页面缓存访问并保留旧版安全检查。
    输入：目标成片对应的页面缓存目录。
    输出：持有导出及旧版兼容保护的临界区。
    """
    with _os_file_lock(work / ".export.os-lock"):
        _guard_legacy_export(work)
        yield


def _page_audio_path(work: Path, title: str, brief: str, language: str | None) -> Path:
    """处理：根据最终导出口播标题、短稿和稿件语言定位逐页缓存。
    输入：目标页面缓存、已接受口播字段和图文语言。
    输出：与既有视频导出兼容的本地 WAV 路径。
    """
    key_input = json.dumps([title, brief, language], ensure_ascii=False).encode()
    return work / f"{hashlib.sha256(key_input).hexdigest()}.wav"


def prefetch_speech(
    plan_path: Path,
    output: Path,
    model_dir: Path | None,
    data_dir: Path,
    *,
    ffmpeg: str | None = None,
    threads: int = 2,
    tts_executable: Path | None = None,
    device: str | None = None,
    voice: str | Path | None = None,
    reference_id: str | None = None,
    follow_seconds: int = 0,
) -> dict:
    """处理：仅为已有接受回执的新闻预合成逐页配音。
    输入：冻结图文计划、最终 MP4 路径及将用于导出的配音配置。
    输出：本轮缓存命中和新生成页数，及仍待接受的批次编号。
    """
    from .narrative_store import ArtifactReader
    from .news_slides import slides_status
    from .video_runtime import ensure_video_runtime

    if follow_seconds < 0:
        raise ValueError("follow_seconds must be non-negative")
    started = time.perf_counter()
    deadline = started + follow_seconds if follow_seconds else None
    reader = ArtifactReader(data_dir)
    plan = reader.load(plan_path, kind="slides-plan")["payload"]
    status = slides_status(plan_path, data_dir, reader=reader)
    authored = {slide["event_id"]: slide for slide in plan.get("reused_slides", [])}
    work = output.resolve().with_suffix("") / "page-cache"
    language = plan.get("language")
    result = {
        "page_cache": str(work), "ready_pages": 0, "unprocessed_ready_pages": 0,
        "follow_seconds": follow_seconds, "timed_out": False,
        "skipped_missing_short_script": 0,
        "tts_page_cache_hits": 0, "tts_pages_generated": 0,
    }
    seen_paths: set[str] = set()
    seen_events: set[str] = set()
    providers = set()
    synthesizer = None
    with ExitStack() as stack:
        while True:
            for path in status["completed_paths"]:
                if path not in seen_paths:
                    draft = reader.load(Path(path))["payload"]["draft"]
                    authored.update({slide["event_id"]: slide for slide in draft["slides"]})
                    seen_paths.add(path)
            pages = [
                row | authored[event_id]
                for row in plan["news"]
                if (event_id := row["event_id"]) in authored and event_id not in seen_events
            ]
            seen_events.update(row["event_id"] for row in pages)
            ready = [
                row for row in pages
                if isinstance(row.get("video_tldr"), str) and row["video_tldr"].strip()
            ]
            result["ready_pages"] += len(ready)
            result["skipped_missing_short_script"] += len(pages) - len(ready)
            for row in ready:
                if deadline is not None and time.perf_counter() >= deadline:
                    result["timed_out"] = True
                    break
                if synthesizer is None:
                    stack.enter_context(_export_lock(work))
                    speech_lock = data_dir / "video-runtime" / ".speech.os-lock"
                    stack.enter_context(_os_file_lock(speech_lock))
                    runtime = ensure_video_runtime(
                        data_dir, model_dir=model_dir, tts_executable=tts_executable,
                        ffmpeg=ffmpeg or shutil.which("ffmpeg"), device=device,
                        voice=voice, reference_id=reference_id, prepare_browser=False,
                    )
                    synthesizer = VoiceSynthesizer(
                        runtime, data_dir / "video-runtime" / "voice-cache", threads=threads
                    )
                    stack.callback(synthesizer.close)
                    if deadline is not None and time.perf_counter() >= deadline:
                        result["timed_out"] = True
                        break
                brief = row["video_tldr"].strip()
                title = row["title"]
                wav = _page_audio_path(work, title, brief, language)
                speech = synthesizer.page(title, brief, wav, language=language or "zh-CN")
                providers.add(speech["provider"])
                hit = speech.get("page_cache_hit", False)
                result["tts_page_cache_hits" if hit else "tts_pages_generated"] += 1
                _progress("prefetch_speech", event_id=row["event_id"], page_cache_hit=hit)
            pending = status["pending_batches"]
            if not pending or deadline is None or result["timed_out"]:
                break
            # 空闲时只查尚未接收批次的文件名，首次出现正式回执才读盘校验。
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    result["timed_out"] = True
                    break
                if any(next(plan_path.parent.glob(f"slides-result-{n}-r*.json"), None)
                       for n in pending):
                    status = slides_status(plan_path, data_dir, reader=reader)
                    break
                time.sleep(min(2.0, remaining))
            if result["timed_out"]:
                break
        if synthesizer is not None:
            result.update(
                providers_used=sorted(providers), execution_mode=synthesizer.execution_mode,
                tts_segments_generated=synthesizer.generated, tts_cache_hits=synthesizer.hits,
                fallback_reason=synthesizer.fallback_reason,
            )
    result["pending_batches"] = status["pending_batches"]
    result["unprocessed_ready_pages"] = (
        result["ready_pages"] - result["tts_page_cache_hits"] - result["tts_pages_generated"]
    )
    result["elapsed_seconds"] = time.perf_counter() - started
    return result


def render_video(
    deck_path: Path,
    output: Path,
    model_dir: Path | None,
    data_dir: Path,
    *,
    ffmpeg: str | None = None,
    threads: int = 2,
    tts_executable: Path | None = None,
    device: str | None = None,
    voice: str | Path | None = None,
    reference_id: str | None = None,
    title: str | None = None,
) -> dict:
    """处理：以实测口播时长驱动画面并复用未改变的页面。
    输入：已保存的新闻稿、输出路径和本地语音运行环境。
    输出：视频路径、逐页时间轴、缓存统计与阶段耗时。
    """
    output = output.resolve()
    work = output.with_suffix("") / "page-cache"
    with _export_lock(work), _os_file_lock(data_dir / "video-runtime" / ".speech.os-lock"):
        return _render_video_locked(
            deck_path, output, model_dir, data_dir, work,
            ffmpeg=ffmpeg, threads=threads, tts_executable=tts_executable,
            device=device, voice=voice, reference_id=reference_id, title=title,
        )


def _render_video_locked(
    deck_path: Path,
    output: Path,
    model_dir: Path | None,
    data_dir: Path,
    work: Path,
    *,
    ffmpeg: str | None,
    threads: int,
    tts_executable: Path | None,
    device: str | None,
    voice: str | Path | None,
    reference_id: str | None,
    title: str | None,
) -> dict:
    """处理：持有输出缓存的导出锁期间完成本期音画处理和封装。
    输入：图文稿、独占页面缓存及调用方选定的配音与编码环境。
    输出：本轮音画验证结果、成片路径、时间轴与阶段耗时。
    """
    started = time.perf_counter()
    from .video_runtime import _ensure_browser, ensure_video_runtime

    diagnostics_path = work / "diagnostics.json"
    diagnostics_path.write_text("[]", encoding="utf-8")
    deck_bytes = deck_path.read_bytes()
    deck_sha256 = hashlib.sha256(deck_bytes).hexdigest()
    record = json.loads(deck_bytes)
    deck = record.get("payload", record)
    title = title or deck.get("video_title") or deck.get("title") or "News video"
    source_html = _source_slides_html(deck_path, data_dir)
    playback = source_html.read_text(encoding="utf-8")
    document = BeautifulSoup(playback, "html.parser")
    source_slides = document.select(".slide")
    if len(source_slides) != len(deck["slides"]) or any(
        node.select_one("h2") is None
        or node.select_one("h2").get_text(strip=True) not in {
            slide["title"], display_slide_title(slide["title"]),
        }
        for node, slide in zip(source_slides, deck["slides"], strict=True)
    ):
        raise ValueError("Rendered slides HTML does not match the selected deck")
    missing = [
        slide.get("event_id", "unknown")
        for slide in deck["slides"]
        if not isinstance(slide.get("video_tldr"), str) or not slide["video_tldr"].strip()
    ]
    if missing:
        raise ValueError(
            "Missing video_tldr for "
            + ", ".join(map(str, missing))
            + "; have the model read the full narration and generate short scripts first"
        )
    runtime = ensure_video_runtime(
        data_dir,
        model_dir=model_dir,
        tts_executable=tts_executable,
        ffmpeg=ffmpeg or shutil.which("ffmpeg"),
        device=device,
        voice=voice,
        reference_id=reference_id,
        prepare_browser=False,
    )
    ffmpeg = str(runtime["ffmpeg"])
    setup_seconds = time.perf_counter() - started
    started = time.perf_counter()
    language = deck.get("language", "zh-CN")
    scripts = [slide["video_tldr"].strip() for slide in deck["slides"]]
    for slide_node in source_slides:
        slide_node.extract()
    shell_digest = hashlib.sha256((str(document) + _VIDEO_SEEK_SCRIPT).encode()).hexdigest()
    synthesizer = VoiceSynthesizer(
        runtime, data_dir / "video-runtime" / "voice-cache", threads=threads
    )
    _progress("runtime", provider=synthesizer.provider,
              execution_mode=synthesizer.execution_mode,
              worker_path=str(runtime.get("tts_worker_executable") or ""),
              worker_note=runtime.get("worker_note"))
    timeline, offset = [], 0.0
    diagnostics = []
    diagnostics_lock = Lock()
    tts_seconds = 0.0

    def record_stage(stage: str, started_at: float, result: str, **details: object) -> None:
        """处理：保存已完成或失败的本地调用。
        输入：阶段、起始时间、结果及页和产物关联。
        输出：更新本次诊断文件供运行中查看。
        """
        with diagnostics_lock:
            diagnostics.append(
                {
                    "stage": stage,
                    **details,
                    "seconds": time.perf_counter() - started_at,
                    "result": result,
                }
            )
            diagnostics_path.write_text(
                json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def synthesize_page(index: int) -> tuple[Path, dict]:
        """处理：单线程依次合成下一页，在主线程处理当前画面时预取。
        输入：原稿页序和共享的语音缓存。
        输出：已完成音频及实测时长；同一时刻只有一个原生语音调用。
        """
        nonlocal tts_seconds
        slide = deck["slides"][index]
        brief = scripts[index]
        wav = _page_audio_path(work, slide["title"], brief, deck.get("language"))
        page_started = time.perf_counter()
        try:
            speech = synthesizer.page(
                slide["title"], brief, wav, language=language
            )
        except Exception:
            record_stage(
                "speech", page_started, "failed", event_id=slide["event_id"], output=str(wav)
            )
            raise
        record_stage(
            "speech",
            page_started,
            "ok",
            event_id=slide["event_id"],
            output=str(wav),
            page_cache_hit=speech.get("page_cache_hit", False),
        )
        _progress("speech", page=index + 1, pages=len(deck["slides"]), event_id=slide["event_id"])
        tts_seconds += time.perf_counter() - page_started
        return wav, speech

    render_seconds = encode_seconds = 0.0
    generated = reused = rendered = 0
    clips = []
    page = None
    # 只预取下一页语音，主线程按页序消费，浏览器始终由同一线程持有。
    with ExitStack() as browser_stack, ThreadPoolExecutor(max_workers=1) as speech_pool:
        browser_stack.callback(synthesizer.close)
        speech_future = speech_pool.submit(synthesize_page, 0) if deck["slides"] else None
        for index, (slide, node) in enumerate(zip(deck["slides"], source_slides, strict=True)):
            wav, speech = speech_future.result()
            if index + 1 < len(deck["slides"]):
                speech_future = speech_pool.submit(synthesize_page, index + 1)
            brief = scripts[index]
            duration = math.ceil(speech["duration"] * 25) / 25
            timeline.append(
                {
                    "event_id": slide["event_id"],
                    "start": offset,
                    "duration": duration,
                    "text": f"{slide['title']}\n{brief}",
                    "audio": wav.name,
                    "provider": speech["provider"],
                    "voice_manifest": str(wav.with_suffix(".voice.json")),
                }
            )
            entry = timeline[-1]
            offset += duration
            count = max(1, len(node.select("[data-gallery] figure")))
            # 非内嵌图像可能随网络或本地文件变化，不能仅凭 HTML 复用画面。
            dynamic_images = any(
                not str(image.get("src") or "").startswith("data:")
                for image in node.select("[data-gallery] img")
            )
            # 画面包括本页完整讲解和导航栏的下一条标题；音频由封装回执单独绑定。
            following = source_slides[(index + 1) % len(source_slides)]
            frame_inputs = [
                "slides-html-v1", shell_digest, str(source_html.resolve()), str(node),
                following.select_one("h2").get_text(), index, len(source_slides),
                _VIDEO_VIEWPORT, entry["duration"],
                25, "libx264", "ultrafast", "yuv420p", ffmpeg,
            ]
            key = hashlib.sha256(json.dumps(frame_inputs, ensure_ascii=False).encode()).hexdigest()
            clip = work / f"{key}.mp4"
            clips.append(clip)
            if not dynamic_images and clip.is_file():
                reused += 1
                record_stage(
                    "reuse_page", time.perf_counter(), "reused",
                    event_id=entry["event_id"], input=str(clip), output=str(clip),
                )
                continue
            render_attempt = time.perf_counter()
            phase = "render"
            try:
                if page is None:
                    from playwright.sync_api import sync_playwright

                    browser_api = browser_stack.enter_context(sync_playwright())
                    executable_path = (
                        os.environ.get("SIGNALTRAIL_BROWSER_EXECUTABLE")
                        or browser_api.chromium.executable_path
                    )
                    _ensure_browser(None, executable_path=executable_path)
                    browser = browser_api.chromium.launch(executable_path=executable_path)
                    browser_stack.callback(browser.close)
                    page = browser.new_page(viewport=_VIDEO_VIEWPORT, device_scale_factor=1)
                    # 页面初始化后由 seek 等待当前图片，避免整份图文的远程资源阻塞启动。
                    page.goto(
                        source_html.resolve().as_uri(),
                        wait_until="domcontentloaded",
                        timeout=120_000,
                    )
                page_started = time.perf_counter()
                frames = work / f"frames-{clip.stem}"
                frames.mkdir(exist_ok=True)
                for image in range(count):
                    image_started = time.perf_counter()
                    image_timed_out = page.evaluate(_VIDEO_SEEK_SCRIPT, [index, image])
                    if image_timed_out:
                        record_stage(
                            "render_image", image_started, "timed_out",
                            event_id=entry["event_id"], image=image + 1,
                        )
                    # 截图直接快进页面动画到终点，逐图省去固定过渡等待。
                    page.screenshot(
                        path=str(frames / f"{image:03}.png"), animations="disabled"
                    )
                rendered += 1
                render_seconds += time.perf_counter() - page_started
                encode_started = time.perf_counter()
                phase = "encode"
                pending_clip = clip.with_name(clip.stem + ".pending.mp4")
                command = [
                    ffmpeg,
                    "-y",
                    "-framerate",
                    str(count / entry["duration"]),
                    "-i",
                    str(frames / "%03d.png"),
                    "-vf",
                    "tpad=stop_mode=clone:stop_duration=1",
                    "-frames:v",
                    str(round(entry["duration"] * 25)),
                    "-r",
                    "25",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(pending_clip),
                ]
                try:
                    _run(command)
                    os.replace(pending_clip, clip)
                except Exception:
                    record_stage(
                        "encode_page",
                        encode_started,
                        "failed",
                        event_id=entry["event_id"],
                        input=str(frames),
                        output=str(clip),
                    )
                    raise
                seconds = time.perf_counter() - encode_started
                encode_seconds += seconds
                generated += 1
                record_stage(
                    "encode_page",
                    encode_started,
                    "ok",
                    event_id=entry["event_id"],
                    input=str(frames),
                    output=str(clip),
                )
                phase = "render"
                _progress(
                    "encode_page", page=index + 1, pages=len(deck["slides"]),
                    event_id=entry["event_id"],
                )
            except Exception:
                if phase == "render":
                    record_stage("render", render_attempt, "failed", event_id=entry["event_id"])
                raise
    pipeline_seconds = time.perf_counter() - started
    concat_started = time.perf_counter()
    combined = work / "audio.wav"
    listing = work / "concat.txt"
    timeline_path = work / "timeline.json"
    receipt_path = work / f"video-receipt{output.suffix}.json"
    command = [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(combined),
        "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", "-metadata",
        f"title={title}",
    ]
    # 绑定实际选出的音频和画面字节，避免仅凭稿件或缓存文件名跳过封装。
    receipt_inputs = {
        "version": 1,
        "command": command,
        "ffmpeg_sha256": sha256_file(Path(ffmpeg)),
        "pages": [
            {
                "audio_sha256": sha256_file(work / entry["audio"]),
                "clip_sha256": sha256_file(clip),
                "duration": entry["duration"],
                "event_id": entry["event_id"],
            }
            for clip, entry in zip(clips, timeline, strict=True)
        ],
    }
    matched_receipt = _matching_video_receipt(receipt_path, output, receipt_inputs)
    video_cache_hit = matched_receipt is not None
    video_cache_check_seconds = time.perf_counter() - concat_started
    concat_seconds = 0.0
    if matched_receipt is not None:
        output_digest = matched_receipt["output_sha256"]
        _progress("reuse_video", pages=len(clips))
        record_stage("reuse_video", concat_started, "reused", output=str(output))
    else:
        concat_started = time.perf_counter()
        # 唯一的同目录文件避免另一导出目标和本轮待发布文件使用相同名称。
        pending_output = output.with_name(f".{uuid4().hex}.pending.mp4")
        try:
            with wave.open(str(combined), "wb") as target:
                for index, entry in enumerate(timeline):
                    with wave.open(str(work / entry["audio"]), "rb") as source:
                        if index == 0:
                            target.setparams(source.getparams())
                        target.writeframes(source.readframes(source.getnframes()))
                        target_frames = round(entry["duration"] * source.getframerate())
                        padding = target_frames - source.getnframes()
                        target.writeframes(
                            b"\0" * padding * source.getsampwidth() * source.getnchannels()
                        )
            listing.write_text(
                "".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8"
            )
            _progress("concat", pages=len(clips))
            _run([*command, str(pending_output)])
            output_digest = sha256_file(pending_output)
            os.replace(pending_output, output)
        except Exception:
            record_stage("concat", concat_started, "failed", input=str(listing), output=str(output))
            raise
        concat_seconds = time.perf_counter() - concat_started
        record_stage("concat", concat_started, "ok", input=str(listing), output=str(output))
    write_json(timeline_path, timeline)
    if matched_receipt is None or matched_receipt.get("deck_sha256") != deck_sha256:
        write_json(receipt_path, {"inputs": receipt_inputs, "output_sha256": output_digest,
                                  "deck_sha256": deck_sha256})
    return {
        "video_path": str(output),
        "video_receipt_path": str(receipt_path),
        "title": title,
        "source_slides_html": str(source_html),
        "video_zoom": 1.0,
        "timeline_path": str(timeline_path),
        "diagnostics_path": str(diagnostics_path),
        "duration": offset,
        "pages": len(timeline),
        "setup_seconds": setup_seconds,
        "device": synthesizer.provider,
        "provider": synthesizer.provider,
        "requested_device": runtime.get("requested_device", device),
        "fallback_reason": synthesizer.fallback_reason,
        "providers_used": sorted({entry["provider"] for entry in timeline}),
        "model": str(runtime["model_dir"]),
        "voice": synthesizer.profile.get("name"),
        "engine": synthesizer.engine,
        "execution_mode": synthesizer.execution_mode,
        "worker_path": str(synthesizer.runtime.get("tts_worker_executable") or ""),
        "worker_note": synthesizer.runtime.get("worker_note"),
        "reference_id": (synthesizer.reference["id"] if synthesizer.reference else None),
        "tts_segments_generated": synthesizer.generated,
        "tts_cache_hits": synthesizer.hits,
        "tts_page_cache_hits": synthesizer.page_hits,
        "tts_seconds": tts_seconds,
        "pipeline_seconds": pipeline_seconds,
        "render_seconds": render_seconds,
        "encode_seconds": encode_seconds + concat_seconds,
        "concat_seconds": concat_seconds,
        "video_cache_hit": video_cache_hit,
        "video_cache_check_seconds": video_cache_check_seconds,
        "pages_rendered": rendered,
        "page_clips_generated": generated,
        "page_clips_reused": reused,
    }
