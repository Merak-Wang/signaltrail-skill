from dataclasses import replace
from pathlib import Path

from daily_intelligence.collector import (
    collect_source,
    merge_resume_index,
    merge_verified_results,
)
from daily_intelligence.config import load_config
from daily_intelligence.context import build_context
from daily_intelligence.models import ArticleItem, SourceResult
from daily_intelligence.utils import read_json, write_json
from daily_intelligence.verification import (
    pending_verification_pages,
    write_verification_queue,
)


def test_verified_page_merge_preserves_other_failed_page_links(tmp_path: Path):
    original_path = write_json(
        tmp_path / "data" / "indexes" / "2026-07-14" / "morning-r1.json",
        {
            "date": "2026-07-14",
            "edition": "morning",
            "revision": 1,
            "timezone": "Asia/Shanghai",
            "sources": [
                {
                    "source_id": "bbc_world",
                    "source_name": "BBC",
                    "source_url": "https://www.bbc.com/news",
                    "status": "verification_required",
                    "items": [],
                    "page_results": [
                        {
                            "url": "https://www.bbc.com/news",
                            "status": "verification_required",
                        },
                        {
                            "url": "https://www.bbc.com/news/business",
                            "status": "failed",
                            "error": "HTTP 403",
                        },
                    ],
                }
            ],
            "items": [],
        },
    )
    item = ArticleItem(
        item_id="bbc-1",
        source_id="bbc_world",
        source_name="BBC",
        title="A sufficiently long BBC headline",
        url="https://www.bbc.com/news/articles/example",
        canonical_url="https://www.bbc.com/news/articles/example",
        discovered_at="2026-07-14T06:00:00+08:00",
    )
    captured = SourceResult(
        source_id="bbc_world",
        source_name="BBC",
        source_url="https://www.bbc.com/news",
        status="success",
        collected_at="2026-07-14T06:00:00+08:00",
        final_url="https://www.bbc.com/news",
        http_status=200,
        items=[item],
    )

    merged = read_json(merge_verified_results(original_path, [captured], tmp_path / "data"))

    source = merged["sources"][0]
    assert source["status"] == "partial"
    assert source["items"][0]["item_id"] == "bbc-1"
    assert any(page.get("error") == "HTTP 403" for page in source["page_results"])


def test_verified_merge_rebuilds_source_order_before_context_selects_top15(
    tmp_path: Path,
):
    data_dir = tmp_path / "data"
    existing_items = [
        {
            "item_id": f"bbc-old-{rank}",
            "source_id": "bbc_world",
            "source_name": "BBC",
            "title": f"Existing BBC source item number {rank}",
            "url": f"https://www.bbc.com/news/articles/old-{rank}",
            "canonical_url": f"https://bbc.com/news/articles/old-{rank}",
            "discovered_at": "2026-07-14T05:50:00+08:00",
            "module": "information",
            "category": "international",
            "content_status": "not_fetched",
            "metadata": {"source_rank": rank},
        }
        for rank in range(1, 17)
    ]
    original_path = write_json(
        data_dir / "indexes" / "2026-07-14" / "morning-r1.json",
        {
            "date": "2026-07-14",
            "edition": "morning",
            "revision": 1,
            "timezone": "Asia/Shanghai",
            "source_policies": {
                "bbc_world": {
                    "report_target": 15,
                    "report_max": 15,
                    "item_order": "source",
                }
            },
            "sources": [
                {
                    "source_id": "bbc_world",
                    "source_name": "BBC",
                    "source_url": "https://www.bbc.com/news",
                    "status": "partial",
                    "items": existing_items,
                    "page_results": [
                        {"url": "https://www.bbc.com/news", "status": "success"},
                        {
                            "url": "https://www.bbc.com/news/world",
                            "status": "verification_required",
                        },
                    ],
                }
            ],
            "items": existing_items,
        },
    )
    verified = ArticleItem(
        item_id="bbc-verified-top",
        source_id="bbc_world",
        source_name="BBC",
        title="Newly verified BBC headline at the top of its page",
        url="https://www.bbc.com/news/articles/verified-top",
        canonical_url="https://bbc.com/news/articles/verified-top",
        discovered_at="2026-07-14T05:55:00+08:00",
        module="information",
        category="international",
    )
    captured = SourceResult(
        source_id="bbc_world",
        source_name="BBC",
        source_url="https://www.bbc.com/news/world",
        status="success",
        collected_at="2026-07-14T05:55:00+08:00",
        module="information",
        category="international",
        items=[verified],
    )

    merged_path = merge_verified_results(original_path, [captured], data_dir)
    merged = read_json(merged_path)
    context = read_json(build_context(merged_path, load_config(), data_dir, "morning"))

    expected = ["bbc-verified-top", *[f"bbc-old-{rank}" for rank in range(1, 15)]]
    assert [item["item_id"] for item in merged["items"][:15]] == expected
    assert [item["item_id"] for item in merged["sources"][0]["items"][:15]] == expected
    assert context["brief_plan"][0]["default_item_ids"] == expected


def test_resume_merge_replaces_a_source_without_moving_its_group(tmp_path: Path):
    data_dir = tmp_path / "data"

    def item(source_id: str, suffix: str) -> dict:
        return {
            "item_id": f"{source_id}-{suffix}",
            "source_id": source_id,
            "title": f"{source_id} story {suffix}",
            "url": f"https://{source_id}.example/{suffix}",
        }

    original_path = write_json(
        data_dir / "indexes" / "2026-07-14" / "morning-r1.json",
        {
            "date": "2026-07-14",
            "edition": "morning",
            "revision": 1,
            "timezone": "Asia/Shanghai",
            "sources": [
                {"source_id": "source_a", "items": [item("source_a", "old")]},
                {"source_id": "source_b", "items": [item("source_b", "old")]},
                {"source_id": "source_c", "items": [item("source_c", "old")]},
            ],
            "items": [
                item("source_a", "old"),
                item("source_b", "old"),
                item("source_c", "old"),
            ],
        },
    )
    retry_path = write_json(
        tmp_path / "retry.json",
        {
            "date": "2026-07-14",
            "edition": "morning",
            "generated_at": "2026-07-14T06:30:00+08:00",
            "sources": [{"source_id": "source_b", "items": [item("source_b", "new")]}],
            "items": [item("source_b", "new")],
        },
    )

    merged = read_json(merge_resume_index(original_path, retry_path, data_dir))

    assert [row["source_id"] for row in merged["sources"]] == [
        "source_a",
        "source_b",
        "source_c",
    ]
    assert [row["item_id"] for row in merged["items"]] == [
        "source_a-old",
        "source_b-new",
        "source_c-old",
    ]
    assert [row["items"][0]["item_id"] for row in merged["sources"]] == [
        "source_a-old",
        "source_b-new",
        "source_c-old",
    ]


def test_verification_queue_includes_failed_and_challenged_links(tmp_path: Path):
    index = {
        "date": "2026-07-15",
        "edition": "morning",
        "sources": [
            {
                "source_id": "bbc_world",
                "source_name": "BBC",
                "source_url": "https://www.bbc.com/news",
                "status": "partial",
                "page_results": [
                    {
                        "url": "https://www.bbc.com/news",
                        "status": "verification_required",
                    },
                    {
                        "url": "https://www.bbc.com/news/business",
                        "status": "failed",
                    },
                ],
            },
            {
                "source_id": "sec_edgar_latest",
                "source_name": "SEC EDGAR",
                "source_url": "https://www.sec.gov/cgi-bin/browse-edgar",
                "status": "no_items",
                "error": "HTTP 403",
                "page_results": [
                    {
                        "url": "https://www.sec.gov/cgi-bin/browse-edgar",
                        "status": "no_items",
                    }
                ],
            },
            {
                "source_id": "huggingface_papers",
                "source_name": "Hugging Face Papers",
                "source_url": "https://huggingface.co/papers/month",
                "status": "verification_required",
                "page_results": [],
            },
            {
                "source_id": "reuters",
                "source_name": "Reuters",
                "source_url": "https://www.reuters.com/",
                "status": "rate_limited",
                "page_results": [],
            },
        ],
    }

    pending = pending_verification_pages(index)
    markdown_path, html_path = write_verification_queue(tmp_path, index, pending)

    assert [item["status"] for item in pending] == [
        "verification_required",
        "failed",
        "failed",
        "verification_required",
        "rate_limited",
    ]
    assert "https://www.bbc.com/news/business" in markdown_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert "daily_intel_verify__bbc_world--0" in html
    assert "逐个点击链接" in html
    assert "sec.gov/cgi-bin/browse-edgar" in html
    assert 'https://huggingface.co/papers/trending"' in html
    assert "https://huggingface.co/papers/month" not in html
    assert "未连接采集器" in html
    assert "window.verificationPortal" in html
    assert "overflow-y:scroll" in html
    assert "列表区域可独立滚动" in html
    assert "共 5 项" in html
    assert 'data-status="rate_limited"' in html
    assert "暂时限制" in html


def test_collect_source_never_keeps_an_access_error_as_no_items(monkeypatch, tmp_path: Path):
    config = load_config()
    source = replace(
        config.source_by_id("bbc_world"),
        url="https://www.bbc.com/news",
        explore_urls=[],
    )
    failed = SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        status="no_items",
        collected_at="2026-07-15T06:00:00+08:00",
        error="HTTP 403",
    )
    monkeypatch.setattr(
        "daily_intelligence.collector.collect_one", lambda *_args, **_kwargs: failed
    )

    result = collect_source(None, source, config, tmp_path)

    assert result.status == "failed"
    assert result.page_results[0]["status"] == "failed"


def test_multi_page_source_merge_is_balanced(monkeypatch, tmp_path: Path):
    config = load_config()
    source = replace(
        config.source_by_id("bbc_world"),
        url="https://www.bbc.com/news",
        explore_urls=["https://www.bbc.com/news/world", "https://www.bbc.com/news/business"],
        max_items=3,
    )

    def fake_collect_one(_context, page_source, _config, _data_dir):
        slug = page_source.url.rsplit("/", 1)[-1]
        items = [
            ArticleItem(
                item_id=f"{slug}-{position}",
                source_id=source.id,
                source_name=source.name,
                title=f"A sufficiently long headline {slug} {position}",
                url=f"https://www.bbc.com/news/articles/{slug}-{position}",
                canonical_url=f"https://bbc.com/news/articles/{slug}-{position}",
                discovered_at="2026-07-14T06:00:00+08:00",
            )
            for position in range(3)
        ]
        return SourceResult(
            source_id=source.id,
            source_name=source.name,
            source_url=page_source.url,
            status="success",
            collected_at="2026-07-14T06:00:00+08:00",
            items=items,
        )

    monkeypatch.setattr("daily_intelligence.collector.collect_one", fake_collect_one)

    result = collect_source(None, source, config, tmp_path)

    assert [item.item_id for item in result.items] == ["news-0", "world-0", "business-0"]
    assert [item.metadata["source_rank"] for item in result.items] == [1, 2, 3]


def test_multi_page_source_can_sort_by_publication_without_losing_top_rank(
    monkeypatch, tmp_path: Path
):
    config = load_config()
    source = replace(
        config.source_by_id("bbc_world"),
        url="https://www.bbc.com/news",
        explore_urls=["https://www.bbc.com/news/world"],
        max_items=3,
        item_order="published_at",
    )

    def fake_collect_one(_context, page_source, _config, _data_dir):
        slug = page_source.url.rsplit("/", 1)[-1]
        year = 2024 if slug == "news" else 2026
        items = [
            ArticleItem(
                item_id=f"{slug}-{position}",
                source_id=source.id,
                source_name=source.name,
                title=f"A sufficiently long headline {slug} {position}",
                url=f"https://www.bbc.com/news/articles/{slug}-{position}",
                canonical_url=f"https://bbc.com/news/articles/{slug}-{position}",
                discovered_at="2026-07-14T06:00:00+08:00",
                published_at=f"{year}-07-{10 + position:02d}",
            )
            for position in range(2)
        ]
        return SourceResult(
            source_id=source.id,
            source_name=source.name,
            source_url=page_source.url,
            status="success",
            collected_at="2026-07-14T06:00:00+08:00",
            items=items,
        )

    monkeypatch.setattr("daily_intelligence.collector.collect_one", fake_collect_one)

    result = collect_source(None, source, config, tmp_path)

    assert [item.item_id for item in result.items] == [
        "world-1",
        "world-0",
        "news-1",
    ]
    assert [item.metadata["source_rank"] for item in result.items] == [4, 2, 3]
