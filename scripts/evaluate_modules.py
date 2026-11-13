"""运行完整模块评估，记录产物质量、时延、吞吐和进程资源。"""

from __future__ import annotations

import argparse
import ctypes
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
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        """接收 Windows 进程内存计数中的峰值工作集。"""

        _fields_ = [("cb", wintypes.DWORD), ("page_faults", wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in (
                        "peak_working_set", "working_set", "peak_paged", "paged",
                        "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]]

    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = wintypes.HANDLE
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    if not query(current(), ctypes.byref(counters), counters.cb):
        return None
    return counters.peak_working_set / 1024**2


def video_evaluation(work_dir: Path, args: argparse.Namespace) -> dict:
    """用真实已接受稿和本机语音环境导出两遍视频，检查成片并记录缓存收益。"""
    from signaltrail.slide_video import render_video
    from signaltrail.video_runtime import ensure_video_runtime

    deck = json.loads(args.video_deck.read_text(encoding="utf-8"))
    deck = deck.get("payload", deck)
    expected_ids = [slide["event_id"] for slide in deck["slides"]]
    if args.tts_worker:
        os.environ["SIGNALTRAIL_TTS_WORKER"] = str(args.tts_worker.resolve())
    runtime = ensure_video_runtime(args.data_dir, device=args.device,
                                   model_dir=args.model_dir, tts_executable=args.tts_executable)
    output = work_dir / "video.mp4"
    started = time.perf_counter()
    first = render_video(args.video_deck, output, args.model_dir, args.data_dir,
                         device=args.device, tts_executable=args.tts_executable)
    first_seconds = time.perf_counter() - started
    first_timeline = json.loads(Path(first["timeline_path"]).read_text(encoding="utf-8"))
    started = time.perf_counter()
    repeat = render_video(args.video_deck, output, args.model_dir, args.data_dir,
                          device=args.device, tts_executable=args.tts_executable)
    repeat_seconds = time.perf_counter() - started
    repeat_timeline = json.loads(Path(repeat["timeline_path"]).read_text(encoding="utf-8"))
    decoded = subprocess.run([str(runtime["ffmpeg"]), "-v", "error", "-i", str(output),
                              "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                             capture_output=True, check=False, timeout=180)
    return {
        "workload": {"dataset": "accepted-deck", "pages": len(expected_ids),
                     "deck_sha256": hashlib.sha256(args.video_deck.read_bytes()).hexdigest()},
        "checks": {"complete_video": bool(expected_ids) and first["duration"] > 0
                   and first["pages"] == repeat["pages"] == len(expected_ids)
                   and [page["event_id"] for page in first_timeline] == expected_ids
                   and [page["event_id"] for page in repeat_timeline] == expected_ids,
                   "full_decode": decoded.returncode == 0,
                   "repeat_audio_reused": repeat["tts_page_cache_hits"] == first["pages"],
                   "repeat_frames_reused": repeat["page_clips_reused"] == first["pages"]},
        "metrics": {"first_export_seconds": first_seconds,
                    "repeat_export_seconds": repeat_seconds,
                    "output_seconds": first["duration"],
                    "first_realtime_speed": first["duration"] / first_seconds,
                    "repeat_realtime_speed": repeat["duration"] / repeat_seconds,
                    "first_tts_page_cache_hits": first["tts_page_cache_hits"],
                    "first_tts_segments_generated": first["tts_segments_generated"],
                    "repeat_frame_cache_hits": repeat["page_clips_reused"],
                    "first_stages": first, "repeat_stages": repeat},
        "artifacts": {"video": str(output), "timeline": first["timeline_path"]},
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
    parser = argparse.ArgumentParser(description=__doc__)
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
