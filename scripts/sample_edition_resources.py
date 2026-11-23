"""在独立终端按固定间隔采样整机负载，按就绪信号结束并绑定整期验收回执。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from statistics import mean


def gpu_busy(executable: str | None) -> float | None:
    """记录本机 NVIDIA 设备中最忙一张卡的忙碌率，驱动不可用时保留缺测。"""
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=4,
        )
        values = [float(line) for line in result.stdout.splitlines()]
        return max(values) if values and all(0 <= value <= 100 for value in values) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def summarize(samples: list[dict], name: str) -> dict | None:
    """汇总已观察到的百分比，保留有效样本数以显示缺测范围。"""
    values = [sample[name] for sample in samples if sample[name] is not None]
    return {"mean": round(mean(values), 2), "peak": max(values), "samples": len(values)
            } if values else None


def main() -> None:
    """从启动时开始采样，交付方创建本次专用完成标记后保存回执。"""
    import psutil

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "stop-file", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        parser.error("Choose an interval of 1 to 60 seconds")
    if args.stop_file.exists() or args.output.exists():
        parser.error("Use a fresh stop marker and output path for each run")
    started = time.monotonic()
    start_utc = datetime.now(UTC)
    psutil.cpu_percent()
    gpu = shutil.which("nvidia-smi")
    samples = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 每次观测即时落盘，机器重启时仍能核对已有区间的负载。
    with args.output.with_suffix(".samples.jsonl").open("x", encoding="utf-8", buffering=1) as log:
        try:
            while not args.stop_file.exists():
                time.sleep(args.interval)
                sample = {
                    "utc": datetime.now(UTC).isoformat(),
                    "cpu_percent_normalized": psutil.cpu_percent(),
                    "memory_pressure_percent": psutil.virtual_memory().percent,
                    "gpu_busy_percent": gpu_busy(gpu),
                }
                log.write(json.dumps(sample) + "\n")
                samples.append(sample)
        except KeyboardInterrupt:
            pass
    finished = datetime.now(UTC)
    duration = time.monotonic() - started
    raw = args.run.read_bytes()
    run = json.loads(raw)
    created = datetime.fromisoformat(run["created_at"])
    updated = datetime.fromisoformat(run["updated_at"])
    complete = run.get("status") in {"completed", "completed_partial"}
    scope = "edition" if (
        args.stop_file.exists() and complete and start_utc <= created <= updated <= finished
    ) else "partial"
    result = {
        "scope": scope, "run_sha256": sha256(raw).hexdigest(), "sample_count": len(samples),
        "start_utc": start_utc.isoformat(), "end_utc": finished.isoformat(),
        "duration_seconds": round(duration, 3), "interval_seconds": args.interval,
        "resource_scope": "whole_device", "gpu_aggregation": "busiest_nvidia_device",
        "samples": samples,
        **{name: summarize(samples, name) for name in (
            "cpu_percent_normalized", "gpu_busy_percent", "memory_pressure_percent",
        )},
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
