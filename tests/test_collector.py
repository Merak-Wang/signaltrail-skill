from dataclasses import replace
from pathlib import Path

from signaltrail.collector import (
    collect_source,
    merge_resume_index,
    merge_verified_results,
)
from signaltrail.config import load_config
from signaltrail.context import build_context
from signaltrail.models import ArticleItem, SourceResult
from signaltrail.utils import read_json, write_json
from signaltrail.verification import (
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
        "signaltrail.collector.collect_one", lambda *_args, **_kwargs: failed
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

    monkeypatch.setattr("signaltrail.collector.collect_one", fake_collect_one)

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

    monkeypatch.setattr("signaltrail.collector.collect_one", fake_collect_one)

    result = collect_source(None, source, config, tmp_path)

    assert [item.item_id for item in result.items] == [
        "world-1",
        "world-0",
        "news-1",
    ]
    assert [item.metadata["source_rank"] for item in result.items] == [4, 2, 3]


def test_frozen_window_refreshes_old_cache_and_preserves_original_rank(monkeypatch, tmp_path):
    from datetime import datetime

    from signaltrail.collector import _current_monitor_items

    config = load_config()
    source = replace(config.source_by_id("bbc_world"), explore_urls=[], max_items=3,
                     report_target=1, report_max=1)
    window = (datetime.fromisoformat("2026-11-01T06:00:00+08:00"),
              datetime.fromisoformat("2026-11-02T06:00:00+08:00"))

    def item(name, date, **metadata):
        return ArticleItem(item_id=name, source_id=source.id, source_name=source.name,
                           title=name, url=f"https://bbc.com/{name}",
                           canonical_url=f"https://bbc.com/{name}",
                           discovered_at="2026-11-02T05:00:00+08:00",
                           published_at=date, metadata=metadata)

    old = item("old", "2026-10-01T05:00:00+08:00")
    fresh = item("fresh", "2026-11-02T05:00:00+08:00")
    stale = item("stale", fresh.published_at, feed_stale=True)
    retained = item("retained", fresh.published_at, retained_from_previous_snapshot=True)
    assert _current_monitor_items([old, fresh, stale, retained], source, window) == [fresh]
    assert _current_monitor_items([old], replace(source, role="discovery"), window) == [old]
    cache = SourceResult(source.id, source.name, source.url, "success",
                         "2026-11-02T05:30:00+08:00", items=[old])
    calls = []

    def refresh(*args):
        calls.append(True)
        return replace(cache, items=[old, fresh])

    monkeypatch.setattr("signaltrail.collector.collect_one", refresh)
    result = collect_source(None, source, config, tmp_path, monitor_result=cache, window=window)
    assert calls == [True]
    assert [i.item_id for i in result.items] == ["fresh", "old"]
    assert [i.metadata["source_rank"] for i in result.items] == [2, 1]
    fresh.metadata["source_rank"] = 50
    calls.clear()
    result = collect_source(None, source, config, tmp_path,
                            monitor_result=replace(cache, items=[old, fresh]), window=window)
    assert calls == []
    assert result.items[0].metadata["source_rank"] == 50
    calls.clear()
    result = collect_source(None, source, config, tmp_path,
                            monitor_result=replace(cache, items=[old, stale, retained]),
                            window=window)
    assert calls == [True]
    assert [i.item_id for i in result.items] == ["fresh", "old"]
    monkeypatch.setattr("signaltrail.collector.collect_one", lambda *args: replace(
        cache, status="failed", items=[], error="HTTP 503"))
    result = collect_source(None, source, config, tmp_path, monitor_result=cache, window=window)
    assert result.status == "failed"
    assert result.items == []


def test_live_item_recovers_matching_current_feed_without_changing_rank(monkeypatch, tmp_path):
    from datetime import datetime

    from signaltrail.utils import write_json

    config = load_config()
    source = replace(config.source_by_id("bbc_world"), explore_urls=[], max_items=3,
                     report_target=2, report_max=2)
    window = (datetime.fromisoformat("2026-11-01T06:00:00+08:00"),
              datetime.fromisoformat("2026-11-02T06:00:00+08:00"))
    live = ArticleItem("one", source.id, source.name, "Title", "https://bbc.com/a",
                       "https://bbc.com/a", "2026-11-02T05:00:00+08:00",
                       published_at="2026-11-02T05:00:00+08:00")
    feed = write_json(tmp_path / "feed.json", {"source_id": source.id, "item_id": "one",
                      "url": live.url, "text": "A substantive article summary."})
    cached = replace(live, description="A substantive article summary.", metadata={
        "feed_content_path": str(feed), "feed_content_sha256": "hash",
        "feed_content_characters": 30,
    })
    cache = SourceResult(source.id, source.name, source.url, "success", "now", items=[cached])
    monkeypatch.setattr("signaltrail.collector.collect_one", lambda *args: replace(
        cache, items=[live]))
    result = collect_source(None, source, config, tmp_path, monitor_result=cache, window=window)
    assert result.items[0].description == cached.description
    assert result.items[0].metadata["feed_content_path"] == str(feed)
    assert result.items[0].metadata["source_rank"] == 1
    assert live.description == "" and live.metadata == {}
    assert result.items[0].published_at == live.published_at

    old_live = replace(live, published_at="2026-10-01T05:00:00+08:00")
    old_cache = replace(cached, published_at=old_live.published_at)
    monkeypatch.setattr("signaltrail.collector.collect_one", lambda *args: replace(
        cache, items=[old_live]))
    result = collect_source(None, source, config, tmp_path,
                            monitor_result=replace(cache, items=[old_cache]), window=window)
    assert result.items[0].description == cached.description
    assert result.items[0].published_at == old_live.published_at
    assert [item.item_id for item in result.items] == ["one"]
    monkeypatch.setattr("signaltrail.collector.collect_one", lambda *args: replace(
        cache, items=[live]))

    for altered in (replace(cached, source_id="other"),
                    replace(cached, item_id="other"),
                    replace(cached, metadata={**cached.metadata, "feed_stale": True})):
        result = collect_source(None, source, config, tmp_path,
                                monitor_result=replace(cache, items=[altered]), window=window)
        assert result.items[0].description == ""
    write_json(feed, {"source_id": source.id, "item_id": "one", "url": live.url,
                      "text": "Comments"})
    navigation = replace(cached, description="Comments")
    result = collect_source(None, source, config, tmp_path,
                            monitor_result=replace(cache, items=[navigation]), window=window)
    assert result.items[0].description == ""
    assert "feed_content_path" not in result.items[0].metadata
