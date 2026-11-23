"""Compare slide packet budgets against saved evidence without calling a model."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from signaltrail.content import synchronize_nested_items  # noqa: E402
from signaltrail.narrative_store import ArtifactReader  # noqa: E402
from signaltrail.news_slides import prepare_slides  # noqa: E402
from signaltrail.runtime import require_data_root_path  # noqa: E402
from signaltrail.utils import read_json, write_json  # noqa: E402


def _copy_benchmark_index(index: Path, data_dir: Path, root: Path) -> Path:
    """处理：将冻结索引引用的正文和 Feed 文件复制到临时测量目录。
    输入：已保存索引、原数据根和基准专用数据根。
    输出：指向临时证据的基准索引，旧计划的父文件仍保留原始字节。
    """
    payload = read_json(index)
    for item in payload["items"]:
        metadata = item.get("metadata") or {}
        for record, key in ((item, "content_path"), (metadata, "feed_content_path")):
            if not record.get(key):
                continue
            relative = require_data_root_path(
                data_dir / record[key], data_dir, "Benchmark evidence",
            ).relative_to(data_dir)
            source, target = data_dir / relative, root / relative
            if source.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            record[key] = str(target)
    synchronize_nested_items(payload)
    return write_json(root / "benchmark-index.json", payload)


def benchmark(data_dir: Path, reuse_plan: Path, report: Path, index: Path) -> dict:
    """处理：复制明确旧计划与新证据，在临时数据根比较三种分包策略。
    输入：已有接受稿的计划、新日报和索引；原运行目录始终只读。
    输出：待写包数与输入估算，真实用量保持未知；保留临时副本供检查。
    """
    data_dir = data_dir.resolve()
    root = Path(tempfile.mkdtemp(prefix="signaltrail-slide-benchmark-"))
    source_reader = ArtifactReader(data_dir)
    old = source_reader.load(reuse_plan, kind="slides-plan")
    paths = {report.resolve(), *(source_reader.parent_path(old, name) for name in old["parents"])}
    for path in paths:
        target = root / path.relative_to(data_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    copied_plan = root / reuse_plan.resolve().relative_to(data_dir)
    shutil.copytree(reuse_plan.parent, copied_plan.parent)
    benchmark_index = _copy_benchmark_index(index, data_dir, root)
    copied_report = root / report.resolve().relative_to(data_dir)
    reader = ArtifactReader(root)
    cases = []
    for name, size, previous in (("baseline_batch4", 4, None),
                                 ("batch5", 5, None),
                                 ("reuse_batch5", 5, copied_plan)):
        result = prepare_slides(copied_report, benchmark_index, root,
                                batch_size=size, reuse_plan=previous)
        packets = [reader.load(Path(path))["payload"] for path in result["packet_paths"]]
        reused = result["reused_count"]
        cases.append({
            "case": name, "news_count": result["news_count"], "new_news_count":
            result["pending_news_count"], "reused_news_count": reused,
            "pending_packets": len(packets), "estimated_input_tokens":
            result["estimated_input_tokens"],
            "compact_model_input_bytes": sum(len(json.dumps(
                packet["model_input"], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")) for packet in packets),
            "actual_usage": {"input_tokens": None, "output_tokens": None, "cost_usd": None},
        })
    return {"temporary_data_dir": str(root), "model_calls_made": 0,
            "packet_count_meaning": "pending writing requests, not observed model calls",
            "cases": cases}


def main() -> None:
    """处理：读取显式文件参数并打印可重复的离线测量。
    输入：命令行指定的旧计划、新报告、索引及其共同数据根。
    输出：JSON 比较结果和保留副本位置，不估算美元成本。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-dir", "reuse-plan", "report", "index"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.data_dir, args.reuse_plan, args.report, args.index),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
