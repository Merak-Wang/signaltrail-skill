"""以本地配音的实际时长驱动图文帧，导出 MP4。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Lock

from bs4 import BeautifulSoup

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
    输出：读者打开的独立图文 HTML 路径，供视频按原始尺寸取景。
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
    started = time.perf_counter()
    from .video_runtime import _ensure_browser, ensure_video_runtime

    output = output.resolve()
    work = output.with_suffix("") / "page-cache"
    work.mkdir(parents=True, exist_ok=True)
    diagnostics_path = work / "diagnostics.json"
    diagnostics_path.write_text("[]", encoding="utf-8")
    record = json.loads(deck_path.read_text(encoding="utf-8"))
    deck = record.get("payload", record)
    title = title or deck.get("video_title") or deck.get("title") or "News video"
    source_html = _source_slides_html(deck_path, data_dir)
    playback = source_html.read_text(encoding="utf-8")
    document = BeautifulSoup(playback, "html.parser")
    source_slides = document.select(".slide")
    if len(source_slides) != len(deck["slides"]) or any(
        node.select_one("h2") is None
        or node.select_one("h2").get_text(strip=True) != slide["title"]
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
        # 短稿由模型阅读完整讲解后生成，音频缓存按标题与短稿定位。
        audio_key = hashlib.sha256(
            json.dumps([slide["title"], brief, deck.get("language")], ensure_ascii=False).encode()
        ).hexdigest()
        wav = work / f"{audio_key}.wav"
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
    pages = []
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
            settings = json.dumps(
                        [
                            "slides-html-v1",
                            str(source_html.resolve()),
                            index,
                            _VIDEO_VIEWPORT,
                            entry["duration"],
                            25,
                            "libx264",
                            "ultrafast",
                            "yuv420p",
                            ffmpeg,
                        ],
                        ensure_ascii=False,
                    )
            following = source_slides[(index + 1) % len(source_slides)]
            following_title = following.h2.get_text(strip=True)
            page_data = json.dumps(
                [str(node), len(source_slides), following_title], ensure_ascii=False,
            )
            key = hashlib.sha256((shell_digest + page_data + settings).encode()).hexdigest()
            clip = work / f"{key}.mp4"
            pages.append((index, count, dynamic_images, clip, entry))
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
    encode_started = time.perf_counter()
    combined = work / "audio.wav"
    with wave.open(str(combined), "wb") as target:
        for index, entry in enumerate(timeline):
            with wave.open(str(work / entry["audio"]), "rb") as source:
                if index == 0:
                    target.setparams(source.getparams())
                target.writeframes(source.readframes(source.getnframes()))
                padding = round(entry["duration"] * source.getframerate()) - source.getnframes()
                target.writeframes(b"\0" * padding * source.getsampwidth() * source.getnchannels())
    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{clip.name}'\n" for _, _, _, clip, _ in pages), encoding="utf-8"
    )
    _progress("concat", pages=len(pages))
    pending_output = output.with_name(output.stem + ".pending.mp4")
    try:
        _run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-i",
                str(combined),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-metadata",
                f"title={title}",
                str(pending_output),
            ]
        )
        os.replace(pending_output, output)
    except Exception:
        record_stage("concat", encode_started, "failed", input=str(listing), output=str(output))
        raise
    concat_seconds = time.perf_counter() - encode_started
    record_stage("concat", encode_started, "ok", input=str(listing), output=str(output))
    timeline_path = work / "timeline.json"
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "video_path": str(output),
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
        "pages_rendered": rendered,
        "page_clips_generated": generated,
        "page_clips_reused": reused,
    }
