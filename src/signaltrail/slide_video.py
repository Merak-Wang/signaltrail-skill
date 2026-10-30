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
from pathlib import Path

from bs4 import BeautifulSoup

from .voice_synthesis import VoiceSynthesizer
from .voice_synthesis import run_native as _run

_VIDEO_ZOOM = 1.4
# 整数 CSS 视口在该像素比下精确生成 1920×1080，避免裁边或二次缩放。
_VIDEO_DEVICE_SCALE = 1.4005
_VIDEO_VIEWPORT = {"width": 1371, "height": 771}


def _source_slides_html(deck_path: Path, data_dir: Path) -> tuple[Path, bool]:
    """处理：从稿件父级定位正在交付的图文页面。
    输入：图文稿路径和数据根，独立稿件使用其同名 HTML。
    输出：已发布的 HTML 路径及是否采用日报嵌入视图，视频直接截取该页面。
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
                return report_html, True
            raise FileNotFoundError(f"Rendered report slides HTML is required: {report_html}")
    source = deck_path.with_suffix(".html")
    if not source.is_file():
        raise FileNotFoundError(f"Rendered slides HTML is required: {source}")
    return source, False


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
    source_html, embedded = _source_slides_html(deck_path, data_dir)
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
    playback_digest = hashlib.sha256(playback.encode("utf-8")).hexdigest()
    synthesizer = VoiceSynthesizer(
        runtime, data_dir / "video-runtime" / "voice-cache", threads=threads
    )
    timeline, offset = [], 0.0
    diagnostics = []

    def record_stage(stage: str, started_at: float, result: str, **details: object) -> None:
        """处理：保存已完成或失败的本地调用。
        输入：阶段、起始时间、结果及页和产物关联。
        输出：更新本次诊断文件供运行中查看。
        """
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

    for index, slide in enumerate(deck["slides"]):
        brief = slide["video_tldr"].strip()
        # 短稿由模型阅读完整讲解后生成，音频缓存按标题与短稿定位。
        audio_key = hashlib.sha256(
            json.dumps([slide["title"], brief, deck.get("language")], ensure_ascii=False).encode()
        ).hexdigest()
        wav = work / f"{audio_key}.wav"
        page_started = time.perf_counter()
        try:
            speech = synthesizer.page(
                slide["title"], brief, wav, language=deck.get("language", "zh-CN")
            )
        except Exception:
            record_stage(
                "speech", page_started, "failed", event_id=slide["event_id"], output=str(wav)
            )
            raise
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
        record_stage(
            "speech",
            page_started,
            "ok",
            event_id=slide["event_id"],
            output=str(wav),
            page_cache_hit=speech.get("page_cache_hit", False),
        )
        _progress("speech", page=index + 1, pages=len(deck["slides"]), event_id=slide["event_id"])
        offset += duration
    tts_seconds = time.perf_counter() - started
    render_seconds = encode_seconds = 0.0
    generated = reused = rendered = 0
    pages = []
    for index, (_slide, entry, node) in enumerate(
        zip(deck["slides"], timeline, source_slides, strict=True)
    ):
        count = max(1, len(node.select("[data-gallery] figure")))
        # 非内嵌图像可能随网络或本地文件变化，不能仅凭 HTML 复用画面。
        dynamic_images = any(
            not str(image.get("src") or "").startswith("data:")
            for image in node.select("[data-gallery] img")
        )
        key = hashlib.sha256(
            (
                playback_digest
                + json.dumps(
                    [
                        "original-slides-v3",
                        _VIDEO_ZOOM,
                        str(source_html.resolve()),
                        embedded,
                        index,
                        _VIDEO_VIEWPORT["width"],
                        _VIDEO_VIEWPORT["height"],
                        _VIDEO_DEVICE_SCALE,
                        entry["duration"],
                        25,
                        "libx264",
                        "ultrafast",
                        "yuv420p",
                        ffmpeg,
                    ],
                    ensure_ascii=False,
                )
            ).encode()
        ).hexdigest()
        pages.append((index, count, dynamic_images, work / f"{key}.mp4", entry))
    pending = [(i, p) for i, p in enumerate(pages) if p[2] or not p[3].is_file()]
    reused = len(pages) - len(pending)
    for _, _, dynamic_images, clip, entry in pages:
        if not dynamic_images and clip.is_file():
            record_stage(
                "reuse_page",
                time.perf_counter(),
                "reused",
                event_id=entry["event_id"],
                input=str(clip),
                output=str(clip),
            )
    if pending:
        render_attempt = time.perf_counter()
        active_event = None
        phase = "render"
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as browser_api:
                executable_path = (
                    os.environ.get("SIGNALTRAIL_BROWSER_EXECUTABLE")
                    or browser_api.chromium.executable_path
                )
                _ensure_browser(None, executable_path=executable_path)
                browser = browser_api.chromium.launch(executable_path=executable_path)
                page = browser.new_page(
                    viewport=_VIDEO_VIEWPORT, device_scale_factor=_VIDEO_DEVICE_SCALE
                )
                page.goto(
                    source_html.resolve().as_uri() + ("?embed=1" if embedded else ""),
                    wait_until="load",
                )
                page.evaluate("() => window.signaltrailPlayback.ready")
                for index, (_, count, dynamic_images, clip, entry) in pending:
                    active_event = entry["event_id"]
                    if not dynamic_images and clip.is_file():
                        reused += 1
                        record_stage(
                            "reuse_page",
                            time.perf_counter(),
                            "reused",
                            event_id=entry["event_id"],
                            input=str(clip),
                            output=str(clip),
                        )
                        continue
                    page_started = time.perf_counter()
                    frames = work / f"frames-{clip.stem}"
                    frames.mkdir(exist_ok=True)
                    for image in range(count):
                        page.evaluate(
                            "([s,i]) => window.signaltrailPlayback.seek(s,i)", [index, image]
                        )
                        page.wait_for_timeout(1100)
                        page.screenshot(path=str(frames / f"{image:03}.png"))
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
                        "encode_page", page=index + 1, pages=len(pages), event_id=entry["event_id"]
                    )
                browser.close()
        except Exception:
            if phase == "render":
                record_stage("render", render_attempt, "failed", event_id=active_event)
            raise
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
        "source_slides_html": str(source_html),
        "video_zoom": _VIDEO_ZOOM,
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
        "reference_id": (synthesizer.reference["id"] if synthesizer.reference else None),
        "tts_segments_generated": synthesizer.generated,
        "tts_cache_hits": synthesizer.hits,
        "tts_page_cache_hits": synthesizer.page_hits,
        "tts_seconds": tts_seconds,
        "render_seconds": render_seconds,
        "encode_seconds": encode_seconds + concat_seconds,
        "concat_seconds": concat_seconds,
        "pages_rendered": rendered,
        "page_clips_generated": generated,
        "page_clips_reused": reused,
    }
