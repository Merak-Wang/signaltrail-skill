"""Reproducible local retrieval comparison; no network, models or production claims."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

from signaltrail.clustering import lexical_tokens
from signaltrail.research import prepare_research_snapshot, search_research
from signaltrail.utils import write_json

CASES = [
    ("算力账单", "算力账单下降只在业务量、质量和其他成本相同的条件下成立。"),
    ("准入许可证", "准入许可证有适用范围，政策公布不等于已经完成实施。"),
    ("利润分配", "利润分配取决于合同中的成本传导约定，不能从单价直接推出。"),
    ("历史融资", "历史融资发生在早期投入阶段，旧融资不代表当期收入。"),
    ("inference latency", "Inference latency was measured at a fixed batch size and hardware."),
    ("electricity capacity", "Electricity capacity constrains deployment at the tested site."),
    ("contract margin", "The contract margin excludes tax and one-time installation costs."),
    ("export regulation", "The export regulation is a proposal rather than an enacted rule."),
]


def evaluate(repeats: int) -> dict:
    """处理：比较同一组合样本的标题检索与正文块检索，并测量本地热运行耗时。
    输入：固定中英文问题和人工指定相关块；重复次数只用于耗时分布。
    输出：命中数、分母和 p50/p95，不外推生产新闻、模型质量或成本节约。
    """
    timings = []
    baseline_hits = 0
    research_hits = 0
    with tempfile.TemporaryDirectory(prefix="signaltrail-research-") as directory:
        root = Path(directory)
        items = []
        for n, (_, body) in enumerate(CASES):
            blocks = write_json(
                root / f"body-{n}.json", {"blocks": [{"block_id": "body", "text": body}]}
            )
            items.append(
                {
                    "item_id": f"sample-{n}",
                    "source_id": f"source-{n}",
                    "source_name": f"Synthetic source {n}",
                    "title": f"研究材料 {n}",
                    "url": f"https://example.org/synthetic/{n}",
                    "content_status": "full_text",
                    "published_at": None,
                    "metadata": {"content_blocks_path": str(blocks)},
                }
            )
        questions = [
            {
                "key": f"q{n}",
                "domain": "ai_technology",
                "question": query,
                "weight": 1,
                "state": "not_evidenced",
                "evidence_span_ids": [],
                "gap": "Synthetic retrieval probe",
            }
            for n, (query, _) in enumerate(CASES)
        ]
        index = write_json(
            root / "index.json",
            {"date": "2026-09-20", "edition": "morning", "items": items, "sources": []},
        )
        start = perf_counter()
        snapshot = prepare_research_snapshot(
            index, [i["item_id"] for i in items], "2026-09-20T09:00:00+08:00", questions, root
        )
        prepare_ms = (perf_counter() - start) * 1000
        for n, (query, body) in enumerate(CASES):
            query_terms = set(lexical_tokens(query))
            baseline = [i for i in items if query_terms & set(lexical_tokens(i["title"]))]
            baseline_hits += bool(baseline and baseline[0]["item_id"] == f"sample-{n}")
            hits = search_research(snapshot, query, root, limit=1)
            research_hits += bool(hits and hits[0]["text"] == body)
        for _ in range(repeats):
            for query, _ in CASES:
                start = perf_counter()
                search_research(snapshot, query, root, limit=1)
                timings.append((perf_counter() - start) * 1000)
    return {
        "scope": "synthetic_eight_case_component_comparison",
        "python": platform.python_version(),
        "platform": platform.system(),
        "questions": len(CASES),
        "title_only_top1_hits": baseline_hits,
        "body_bm25_top1_hits": research_hits,
        "prepare_ms": round(prepare_ms, 3),
        "warm_search_samples": len(timings),
        "warm_search_p50_ms": round(statistics.median(timings), 3),
        "warm_search_p95_ms": round(sorted(timings)[math.ceil(0.95 * len(timings)) - 1], 3),
        "network_calls": 0,
        "model_calls": 0,
        "production_daily_latency": None,
        "reader_comprehension": None,
        "production_token_savings": None,
        "limitation": "Gold terms intentionally occur in bodies, not titles. This tests the "
        "value of accessing saved blocks, not superiority over an existing production retriever.",
    }


def main() -> None:
    """处理：运行固定样本实验并写出可检查的 JSON。
    输入：输出路径和重复次数；所有研究临时文件在独立目录中自动清理。
    输出：本地实验指标文件和标准输出，不触碰真实日报数据根。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    result = evaluate(args.repeats)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
