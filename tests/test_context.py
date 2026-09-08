import json
from pathlib import Path

from daily_intelligence.config import load_config
from daily_intelligence.context import _continuity_entry, build_context
from daily_intelligence.utils import read_json, write_json


def test_evening_context_loads_morning_and_continuity_state(tmp_path: Path):
    data_dir = tmp_path / "data"
    report_dir = data_dir / "reports" / "2026-07-14"
    morning = {
        "report_id": "daily-2026-07-14-morning-r1",
        "date": "2026-07-14",
        "edition": "morning",
        "generated_at": "2026-07-14T06:00:00+08:00",
        "sections": [
            {
                "items": [
                    {
                        "event_id": "event-pending-evaluation",
                        "title": "未经评估的摘要不应复用",
                        "status": "NEW",
                        "importance": 80,
                        "source_refs": [{"item_id": "source-item-1"}],
                    }
                ]
            }
        ],
        "analyses": [{"analysis_id": "analysis-pending", "claim": "未经评估的研判"}],
    }
    write_json(report_dir / "morning-r1.json", morning)
    write_json(data_dir / "state" / "theses.json", {"items": [{"analysis_id": "a1"}]})
    write_json(data_dir / "state" / "watchlist.json", {"items": [{"watch_id": "w1"}]})
    write_json(data_dir / "state" / "predictions.json", {"items": [{"prediction_id": "p1"}]})
    index_path = write_json(
        data_dir / "indexes" / "2026-07-14" / "evening-r1.json",
        {"date": "2026-07-14", "edition": "evening", "items": []},
    )

    output = build_context(index_path, load_config(), data_dir, "evening")
    context = read_json(output)

    assert context["continuity_reports"][0]["report_id"] == morning["report_id"]
    assert context["continuity_reports"][0]["reuse_status"] == "selective"
    assert context["continuity_reports"][0]["events"] == [
        {
            "event_id": "event-pending-evaluation",
            "status": "NEW",
            "source_item_ids": ["source-item-1"],
        }
    ]
    assert context["continuity_reports"][0]["analyses"] == []
    assert context["active_theses"][0]["analysis_id"] == "a1"
    assert context["active_watchlist"][0]["watch_id"] == "w1"
    assert context["open_predictions"][0]["prediction_id"] == "p1"
    assert "never infer unseen details" in context["content_loading_rule"]
    assert "candidate_index" not in context


def test_context_caps_candidates_and_rejects_contaminated_history(tmp_path: Path):
    data_dir = tmp_path / "data"
    report = {
        "report_id": "bad-report",
        "date": "2026-07-13",
        "edition": "evening",
        "generated_at": "2026-07-13T18:00:00+08:00",
        "sections": [{"items": [{"event_id": "bad-event", "title": "错误英文残留"}]}],
        "analyses": [{"analysis_id": "bad-analysis", "claim": "错误判断"}],
        "quality_evaluation": {
            "continuity_decision": "reject",
            "exclude_from_continuity": ["all"],
        },
    }
    write_json(data_dir / "reports" / "2026-07-13" / "evening-r1.json", report)
    items = [
        {
            "item_id": f"item-{position}",
            "source_id": "bbc_world",
            "source_name": "BBC",
            "title": f"新闻标题 {position}",
            "url": f"https://www.bbc.com/news/articles/{position}",
            "discovered_at": f"2026-07-14T{position % 24:02d}:00:00+08:00",
        }
        for position in range(30)
    ]
    index_path = write_json(
        data_dir / "indexes" / "2026-07-14" / "morning-r1.json",
        {"date": "2026-07-14", "edition": "morning", "items": items, "sources": []},
    )

    context = read_json(build_context(index_path, load_config(), data_dir, "morning"))

    assert len(context["candidate_items"]) == 25
    batch = context["brief_authoring_batches"][0]
    assert batch["batch_id"] == "brief-batch-1"
    assert batch["source_ids"] == ["bbc_world"]
    assert batch["candidate_count"] == 15
    assert batch["author_item_count"] == 15
    assert Path(batch["packet_path"]).is_file()
    assert context["brief_plan"] == [
        {
            "source_id": "bbc_world",
            "section_id": "information.international",
            "batch_id": "brief-batch-1",
            "target_count": 15,
            "default_item_ids": [f"item-{position}" for position in range(15)],
            "reuse_item_ids": [],
            "author_item_ids": [f"item-{position}" for position in range(15)],
        }
    ]
    prior = context["continuity_reports"][0]
    assert prior["reuse_status"] == "reject"
    assert prior["events"] == []
    assert prior["analyses"] == []


def test_context_overrides_a_low_score_accept_decision(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "examples" / "sample_report.json").read_text(encoding="utf-8"))
    report["quality_evaluation"] = {
        "dimensions": [
            {"id": dimension, "score": 2, "finding": "该维度存在严重质量问题。"}
            for dimension in (
                "coverage",
                "importance_ordering",
                "factual_reliability",
                "summary_accuracy",
                "analysis_traceability",
                "historical_continuity",
                "readability",
                "timeliness",
                "compliance_boundaries",
            )
        ],
        "total_score": 18,
        "continuity_decision": "accept",
        "exclude_from_continuity": [],
    }
    path = tmp_path / "data" / "reports" / "2026-07-12" / "morning-r1.json"

    entry = _continuity_entry(path, report)

    assert entry["reuse_status"] == "reject"
    assert entry["excluded"] == ["all"]
    assert entry["events"] == []
    assert entry["analyses"] == []
    assert "reject all content" in entry["continuity_override"]


def test_context_keeps_index_top_order_even_when_a_lower_item_is_enriched(tmp_path: Path):
    data_dir = tmp_path / "data"
    items = [
        {
            "item_id": f"bbc-{position}",
            "source_id": "bbc_world",
            "source_name": "BBC",
            "title": f"BBC headline {position} with enough detail",
            "url": f"https://www.bbc.com/news/articles/{position}",
            "discovered_at": f"2026-07-16T{position % 24:02d}:00:00+08:00",
            "content_status": "not_fetched",
            "metadata": {"source_rank": position + 1},
        }
        for position in range(30)
    ]
    items[19].update(
        {
            "content_status": "full_text",
            "content_path": "content/bbc-19.md",
            "published_at": None,
        }
    )
    index_path = write_json(
        data_dir / "indexes" / "2026-07-16" / "morning-r1.json",
        {
            "date": "2026-07-16",
            "edition": "morning",
            "items": items,
            "sources": [],
            "source_policies": {"bbc_world": {"report_target": 10}},
        },
    )

    context = read_json(build_context(index_path, load_config(), data_dir, "morning"))

    assert context["candidate_items"][0]["item_id"] == "bbc-0"
    assert context["candidate_items"][19]["item_id"] == "bbc-19"
    assert context["candidate_items"][19]["content_status"] == "full_text"
    assert context["brief_plan"][0]["default_item_ids"][0] == "bbc-0"
    assert context["brief_plan"][0]["default_item_ids"][-1] == "bbc-14"
    assert "bbc-19" not in context["brief_plan"][0]["default_item_ids"]
    assert context["brief_plan"][0]["target_count"] == 15
    assert "title_zh" in context["brief_authoring_rule"]
    assert "three concurrent harness workers" in context["brief_authoring_rule"]
    assert "may process the packets serially" in context["brief_authoring_rule"]
    assert "packet is the complete data boundary" in context["brief_authoring_rule"]
    assert "main agent" not in context["brief_authoring_rule"].lower()
    assert "short receipt" not in context["brief_authoring_rule"].lower()
    batch = context["brief_authoring_batches"][0]
    packet = read_json(Path(batch["packet_path"]))
    assert batch["author_item_count"] == len(packet["author_item_ids"])
    assert packet["task"].startswith("Author exactly one structured Chinese brief")
    assert "Do not browse the web" in packet["tool_policy"]
    assert "at most one repair" in packet["repair_policy"]
    assert "_source_rank" not in read_json(index_path)["items"][0]


def test_context_splits_all_formal_top15_work_into_bounded_authoring_waves(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    config = load_config()
    items = [
        {
            "item_id": f"{source.id}-{rank}",
            "source_id": source.id,
            "source_name": source.name,
            "title": f"A sufficiently descriptive source headline {source.id} {rank}",
            "url": f"https://example.com/{source.id}/{rank}",
            "canonical_url": f"https://example.com/{source.id}/{rank}",
            "discovered_at": "2026-07-16T05:50:00+08:00",
            "module": source.module,
            "category": source.category,
            "content_status": "not_fetched",
            "metadata": {"source_rank": rank},
        }
        for source in config.sources
        for rank in range(1, 16)
    ]
    index_path = write_json(
        data_dir / "indexes" / "2026-07-16" / "morning-r1.json",
        {
            "date": "2026-07-16",
            "edition": "morning",
            "timezone": "Asia/Shanghai",
            "sources": [
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_url": source.url,
                    "status": "success",
                }
                for source in config.sources
            ],
            "items": items,
            "source_policies": {
                source.id: {
                    "report_target": 15,
                    "report_max": 15,
                    "item_order": "source",
                }
                for source in config.sources
            },
        },
    )

    context = read_json(build_context(index_path, config, data_dir, "morning"))
    batches = context["brief_authoring_batches"]

    assert len(context["brief_plan"]) == 32
    assert all(len(plan["default_item_ids"]) == 15 for plan in context["brief_plan"])
    assert len(batches) == 11
    assert sum(batch["author_item_count"] for batch in batches) == 480
    assert max(batch["author_item_count"] for batch in batches) == 45


def test_context_preserves_published_at_order_already_written_to_index(tmp_path: Path):
    data_dir = tmp_path / "data"
    items = [
        {
            "item_id": "bbc-newer",
            "source_id": "bbc_world",
            "source_name": "BBC",
            "title": "Newer item ranked second on the source page",
            "url": "https://www.bbc.com/news/articles/newer",
            "published_at": "2026-07-16T09:00:00+08:00",
            "content_status": "not_fetched",
            "metadata": {"source_rank": 2},
        },
        {
            "item_id": "bbc-older",
            "source_id": "bbc_world",
            "source_name": "BBC",
            "title": "Older item ranked first on the source page",
            "url": "https://www.bbc.com/news/articles/older",
            "published_at": "2026-07-15T09:00:00+08:00",
            "content_status": "not_fetched",
            "metadata": {"source_rank": 1},
        },
    ]
    index_path = write_json(
        data_dir / "indexes" / "2026-07-16" / "evening-r1.json",
        {
            "date": "2026-07-16",
            "edition": "evening",
            "items": items,
            "sources": [],
            "source_policies": {
                "bbc_world": {
                    "report_target": 15,
                    "report_max": 15,
                    "item_order": "published_at",
                }
            },
        },
    )

    context = read_json(build_context(index_path, load_config(), data_dir, "evening"))

    assert context["brief_plan"][0]["default_item_ids"] == [
        "bbc-newer",
        "bbc-older",
    ]
    assert [item["source_rank"] for item in context["candidate_items"]] == [2, 1]
