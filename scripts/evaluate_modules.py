"""运行完整模块评估，记录产物质量、时延、吞吐和进程资源。"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
MODULES = ("collection", "report", "slides", "orchestration", "video")


def peak_rss_mb() -> float | None:
    """读取当前 Python 进程的峰值驻留内存；浏览器和编码器另属子进程。"""
    if os.name != "nt":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)
    import psutil

    try:
        return psutil.Process().memory_info().peak_wset / 1024**2
    except (AttributeError, psutil.Error):
        return None


def compare_video_frames(
    export: dict, slides: list[dict], timeline: list[dict], work_dir: Path, ffmpeg: str,
) -> list[dict]:
    """从成片抽查首条及文字最长的新闻，核对文字范围和对应图文画面。"""
    from PIL import Image, ImageChops
    from playwright.sync_api import sync_playwright

    indices = range(len(slides))
    longest_title = max(indices, key=lambda index: len(slides[index]["title"]))
    longest_narration = max(indices, key=lambda index: len(slides[index].get("narration") or ""))
    samples = {0, longest_title, longest_narration}
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("SIGNALTRAIL_BROWSER_EXECUTABLE")
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(Path(export["source_slides_html"]).resolve().as_uri(),
                  wait_until="domcontentloaded")
        for index in sorted(samples):
            if index:
                page.locator("[data-go]").nth(index).evaluate("(button) => button.click()")
                page.locator(".slide.leaving").wait_for(state="detached")
            slide = page.locator(".slide.active")
            images = max(1, slide.locator("[data-gallery] figure").count())
            start, duration = timeline[index]["start"], timeline[index]["duration"]
            for image_index in sorted({0, images - 1}):
                if image_index:
                    slide.locator(".gallery-thumbnail").nth(image_index).evaluate(
                        "(button) => button.click()"
                    )
                page.wait_for_function(
                    """() => [...document.querySelectorAll('.slide.active figure.active img')]
                        .every(image => image.complete)"""
                )
                page.evaluate("() => document.fonts.ready")
                screenshot = work_dir / f"original-slide-{index + 1}-image-{image_index + 1}.png"
                page.screenshot(path=str(screenshot), animations="disabled")
                story_fits = slide.evaluate("""article => {
                    const controls = document.querySelector('.controls').getBoundingClientRect();
                    const textBottom = Math.min(window.innerHeight, controls.top);
                    return !article.querySelector('.summary') &&
                        ['.headline', '.narration'].every(selector => {
                            const element = article.querySelector(selector);
                            if (!element?.textContent.trim()) return false;
                            const text = document.createRange();
                            text.selectNodeContents(element);
                            const bounds = text.getBoundingClientRect();
                            return bounds.width > 0 && bounds.height > 0 &&
                                bounds.left >= 0 && bounds.right <= window.innerWidth &&
                                bounds.top >= 0 && bounds.bottom <= textBottom;
                        });
                }""")
                event_id = slides[index]["event_id"]
                frame = work_dir / f"video-slide-{index + 1}-image-{image_index + 1}.png"
                timestamp = start + duration * (image_index + 0.5) / images
                subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y",
                                "-ss", f"{timestamp:.6f}", "-i", export["video_path"],
                                "-map", "0:v:0", "-frames:v", "1", "-update", "1", str(frame)],
                               check=True, timeout=30)
                with Image.open(frame) as rendered, Image.open(screenshot) as original:
                    fraction = 1.0
                    if rendered.size == original.size == (1920, 1080):
                        diff = ImageChops.difference(rendered.convert("RGB"),
                                                     original.convert("RGB")).convert("L")
                        counts = diff.histogram()
                        fraction = sum(counts[21:]) / sum(counts)
                # 编码损耗、字形边缘和图像插值会在两份画面间产生小面积差异。
                results.append({"event_id": event_id, "image_index": image_index,
                                "timestamp_seconds": round(timestamp, 6),
                                "visually_matches": fraction < 0.01, "story_fits": story_fits,
                                "different_pixel_fraction": fraction, "video_frame": str(frame),
                                "original_page": str(screenshot)})
        browser.close()
    return results


def video_evaluation(work_dir: Path, args: argparse.Namespace) -> dict:
    """用真实已接受稿测量首次与重复导出，并验证标题变化和文件损坏后的重建。"""
    from signaltrail.qwen_runtime import MMPROJ_NAME, MODEL_NAME
    from signaltrail.slide_video import render_video
    from signaltrail.utils import sha256_file
    from signaltrail.video_runtime import ensure_video_runtime

    deck_bytes = args.video_deck.read_bytes()
    deck = json.loads(deck_bytes.decode("utf-8"))
    deck = deck.get("payload", deck)
    expected_ids = [slide["event_id"] for slide in deck["slides"]]
    if args.tts_worker:
        os.environ["SIGNALTRAIL_TTS_WORKER"] = str(args.tts_worker.resolve())
    managed_model = (args.data_dir / "video-runtime" / "qwen3" / "model").resolve()
    model_names = (MODEL_NAME, MMPROJ_NAME)
    managed_before = {name for name in model_names if (managed_model / name).is_file()}
    explicit_model = bool(args.model_dir or os.environ.get("SIGNALTRAIL_TTS_MODEL_DIR"))
    runtime = ensure_video_runtime(args.data_dir, device=args.device,
                                   model_dir=args.model_dir, tts_executable=args.tts_executable)
    selected_model = Path(runtime["model_dir"]).resolve()
    output = work_dir / "video.mp4"
    render = partial(render_video, args.video_deck, output, args.model_dir, args.data_dir,
                     device=args.device, tts_executable=args.tts_executable)

    def export(**options) -> tuple[dict, float, str]:
        started = time.perf_counter()
        video = render(**options)
        elapsed = time.perf_counter() - started
        return video, elapsed, sha256_file(output)

    first, first_seconds, first_digest = export()
    first_mtime = output.stat().st_mtime_ns
    first_timeline = json.loads(Path(first["timeline_path"]).read_bytes())
    shared_frames = compare_video_frames(
        first, deck["slides"], first_timeline, work_dir, str(runtime["ffmpeg"])
    )
    repeat, repeat_seconds, repeat_digest = export()
    repeat_mtime = output.stat().st_mtime_ns
    repeat_timeline = json.loads(Path(repeat["timeline_path"]).read_bytes())
    revised_title = first["title"] + " (evaluation)"
    revised, revised_seconds, revised_digest = export(title=revised_title)
    # 用同长度首字节损坏验证内容校验，避免仅靠长度检测通过。
    with output.open("r+b") as handle:
        first_byte = handle.read(1)
        handle.seek(0)
        handle.write(bytes([first_byte[0] ^ 0xFF]))
    restored, _, restored_digest = export(title=revised_title)
    # 恢复正常标题，以便评估回执指向初次导出的成片和时间轴。
    final, _, final_digest = export()
    final_receipt = json.loads(Path(final["video_receipt_path"]).read_bytes())
    deck_digest = hashlib.sha256(deck_bytes).hexdigest()
    decoded = subprocess.run([str(runtime["ffmpeg"]), "-v", "error", "-xerror", "-i", str(output),
                              "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                             capture_output=True, check=False, timeout=180)
    managed_after = {name for name in model_names if (managed_model / name).is_file()}
    external_model_reused = (
        runtime["engine"] == "qwen3" and not explicit_model and selected_model != managed_model
    )
    return {
        "workload": {"dataset": "accepted-deck", "pages": len(expected_ids),
                     "deck_sha256": deck_digest},
        "checks": {"complete_video": bool(expected_ids) and first["duration"] > 0
                   and first["pages"] == repeat["pages"] == len(expected_ids)
                   and [page["event_id"] for page in first_timeline] == expected_ids
                   and [page["event_id"] for page in repeat_timeline] == expected_ids,
                   "full_decode": decoded.returncode == 0,
                   "frames_match_original_slides": bool(shared_frames)
                   and all(row["visually_matches"] for row in shared_frames),
                   "story_fits_above_controls": bool(shared_frames)
                   and all(row["story_fits"] for row in shared_frames),
                   "receipt_matches_deck_and_video": final_receipt["deck_sha256"] == deck_digest
                   and final_receipt["output_sha256"] == final_digest,
                   "external_model_discovery_avoids_managed_download": (
                       not external_model_reused or managed_after == managed_before
                   ),
                   "repeat_audio_reused": repeat["tts_page_cache_hits"] == first["pages"],
                   "repeat_frames_reused": repeat["page_clips_reused"] == first["pages"],
                   "same_video_reused": repeat["video_cache_hit"]
                   and repeat["concat_seconds"] == 0 and repeat_timeline == first_timeline
                   and repeat_digest == first_digest and repeat_mtime == first_mtime,
                   "title_change_remuxed": revised["video_cache_hit"] is False
                   and revised["title"] == revised_title and revised_digest != first_digest,
                   "damaged_video_restored": restored["video_cache_hit"] is False
                   and restored_digest == revised_digest and final_digest == first_digest
                   and final["title"] == first["title"]},
        "metrics": {"first_export_seconds": first_seconds,
                    "repeat_export_seconds": repeat_seconds,
                    "title_change_export_seconds": revised_seconds,
                    "output_seconds": first["duration"],
                    "first_realtime_speed": first["duration"] / first_seconds,
                    "repeat_realtime_speed": repeat["duration"] / repeat_seconds,
                    "first_tts_page_cache_hits": first["tts_page_cache_hits"],
                    "first_tts_segments_generated": first["tts_segments_generated"],
                    "repeat_frame_cache_hits": repeat["page_clips_reused"],
                    "qwen_model_resolution": {
                        "model_dir": str(selected_model),
                        "explicit_model": explicit_model,
                        "external_model_reused": external_model_reused,
                        "new_managed_model_files": sorted(managed_after - managed_before),
                    },
                    "first_stages": first, "repeat_stages": repeat},
        "artifacts": {"video": str(output), "timeline": first["timeline_path"],
                      "frame_comparisons": shared_frames},
        "limitations": ["The first export may reuse the supplied data root's audio cache; "
                        "cache hits and generated segments are reported explicitly."]}


def run_worker(args: argparse.Namespace) -> int:
    """在独立进程运行一个完整模块样本，输出质量结果和本次资源计量。"""
    args.work_dir.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    try:
        result = (video_evaluation(args.work_dir, args) if args.worker == "video" else
                  importlib.import_module(f"evals.modules.{args.worker}").evaluate(args.work_dir))
        if args.worker != "video":
            fixture = (ROOT / "evals" / "modules" / f"{args.worker}.py").read_bytes()
            if args.worker == "report":
                fixture += (ROOT / "examples" / "sample_report.json").read_bytes()
            elif args.worker == "orchestration":
                fixture += (ROOT / "evals" / "modules" / "slides.py").read_bytes()
            result["workload"]["fixture_sha256"] = hashlib.sha256(fixture).hexdigest()
        checks = result["checks"]
        result["status"] = "passed" if checks and all(value is True for value in checks.values()) \
            else "failed"
    except Exception:
        result = {"status": "failed", "error": traceback.format_exc(), "metrics": {}}
    result["metrics"].update(module_wall_seconds=time.perf_counter() - started,
                             python_cpu_seconds=time.process_time() - cpu,
                             python_peak_rss_mb=peak_rss_mb())
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


def compare_baseline(result: dict, path: Path | None, limit: float) -> dict:
    """在环境和工作量一致时比较模块时延中位数，其他情况保留不可比较原因。"""
    if path is None:
        return {"status": "measured", "baseline": None}
    previous = json.loads(path.read_text(encoding="utf-8"))
    if previous["environment"] != result["environment"]:
        return {"status": "not_comparable", "reason": "environment_changed"}
    comparisons = {}
    for name, module in result["modules"].items():
        old = previous["modules"].get(name)
        if (module["status"] != "passed" or not old or old["status"] != "passed" or name == "video"
                or module["samples"][0].get("workload") != old["samples"][0].get("workload")):
            comparisons[name] = {"status": "not_comparable", "reason": "workload_or_cache"}
            continue
        ratio = module["wall_seconds"]["median"] / old["wall_seconds"]["median"]
        comparisons[name] = {"ratio": ratio, "status": "regressed" if ratio > 1 + limit
                             else "passed"}
    comparable = [row for row in comparisons.values() if row["status"] != "not_comparable"]
    status = "regressed" if any(row["status"] == "regressed" for row in comparable) \
        else "compared" if comparable else "not_comparable"
    return {"status": status,
            "max_regression_fraction": limit, "modules": comparisons}


def main() -> int:
    """解析模块和样本数，在隔离进程采样并保存可检查的整体评估结果。"""
    parser = argparse.ArgumentParser(
        description="Measure module output quality, latency, throughput and resource use."
    )
    parser.add_argument("--modules", nargs="+", choices=MODULES,
                        default=["collection", "report", "slides", "orchestration"])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-regression", type=float, default=0.2)
    parser.add_argument("--video-deck", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--tts-worker", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--tts-executable", type=Path)
    parser.add_argument("--worker", choices=MODULES, help=argparse.SUPPRESS)
    parser.add_argument("--work-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return run_worker(args)
    if args.repeat < 1 or args.max_regression < 0:
        parser.error("repeat must be positive; max-regression must be nonnegative")
    if "video" in args.modules and not (args.video_deck and args.data_dir):
        parser.error("video requires --video-deck and --data-dir with a local TTS runtime")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    default_output = ROOT / "output" / "module-evaluations" / stamp / "results.json"
    output = (args.output or default_output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error(f"Output already exists: {output}; choose a new evaluation directory")
    samples_root = output.parent / (output.stem + "-samples")
    samples_root.mkdir(exist_ok=False)
    result = {"recorded_at": datetime.now(UTC).isoformat(),
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "cpu": platform.processor(), "logical_cpus": os.cpu_count()},
              "modules": {}}
    for name in args.modules:
        samples = []
        for number in range(1, args.repeat + 1):
            directory = samples_root / f"{name}-{number}"
            directory.mkdir()
            receipt = directory / "result.json"
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", name,
                       "--work-dir", str(directory / "work"), "--result", str(receipt)]
            for flag, value in (("--video-deck", args.video_deck), ("--data-dir", args.data_dir),
                                ("--tts-worker", args.tts_worker), ("--device", args.device),
                                ("--model-dir", args.model_dir),
                                ("--tts-executable", args.tts_executable)):
                if value is not None:
                    command.extend([flag, str(value)])
            with (directory / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.run(command, stdout=log, stderr=log,
                                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            try:
                sample = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                sample = {"status": "failed", "error": str(exc), "metrics": {}}
            if process.returncode:
                sample.update(status="failed", exit_code=process.returncode)
            sample["log"] = str(directory / "worker.log")
            samples.append(sample)
            print(f"{name} sample {number}: {sample['status']}", flush=True)
            if sample["status"] == "failed":
                break
        times = [sample["metrics"]["module_wall_seconds"] for sample in samples
                 if "module_wall_seconds" in sample["metrics"]]
        result["modules"][name] = {
            "status": "passed" if all(row["status"] == "passed" for row in samples) else "failed",
            "samples": samples,
            "wall_seconds": {"median": statistics.median(times), "min": min(times),
                             "max": max(times)} if times else None}
        module = result["modules"][name]
        timing = module["wall_seconds"]
        summary = (f"median={timing['median']:.3f}s "
                   f"range={timing['min']:.3f}-{timing['max']:.3f}s") if timing else "unavailable"
        print(f"{name}: quality={module['status']}, wall {summary}", flush=True)
    result["performance"] = compare_baseline(result, args.baseline, args.max_regression)
    result["status"] = "passed" if all(row["status"] == "passed" for row in
                                        result["modules"].values()) and \
        result["performance"]["status"] != "regressed" else "failed"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "performance": result["performance"],
                      "results": str(output)}, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
