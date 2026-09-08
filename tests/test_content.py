from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

import httpx

from daily_intelligence.config import load_config
from daily_intelligence.content import (
    _extract_pipeline,
    _ordered_targets,
    _run_http_extraction,
    _run_parallel_extraction,
    synchronize_nested_items,
)
from daily_intelligence.models import ContentStatus


def _item(item_id: str = "bbc-static") -> dict:
    return {
        "item_id": item_id,
        "source_id": "bbc_world",
        "source_name": "BBC",
        "title": "Original public headline",
        "url": f"https://www.bbc.com/news/articles/{item_id}",
        "content_status": ContentStatus.NOT_FETCHED,
        "metadata": {},
    }


def test_http_first_content_extraction_avoids_browser_for_static_article(
    tmp_path: Path,
):
    config = load_config()
    item = _item()
    article_text = " ".join(["verified public article detail"] * 180)
    document = (
        "<html><head>"
        '<meta property="og:title" content="Updated public headline">'
        '<meta property="article:published_time" content="2026-07-24T08:00:00Z">'
        '<meta property="og:image" content="/image/grey-placeholder.png">'
        '<meta name="twitter:image" content="/image/story.png">'
        "</head><body><article>"
        f"{article_text}"
        "</article></body></html>"
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=document.encode(),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
    )

    browser_targets = asyncio.run(
        _run_http_extraction(
            [item],
            config,
            tmp_path,
            transport=transport,
        )
    )

    assert browser_targets == []
    assert item["content_status"] == ContentStatus.FULL_TEXT
    assert item["metadata"]["content_acquisition"] == "http"
    assert item["published_at"] == "2026-07-24T08:00:00Z"
    assert item["image_url"] == "https://www.bbc.com/image/story.png"
    assert Path(item["content_path"]).is_file()


def test_http_first_content_extraction_uses_browser_only_for_javascript_shell(
    tmp_path: Path,
):
    config = load_config()
    item = _item("bbc-js-shell")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            text="<html><body><main id='app'>Loading</main></body></html>",
            headers={"Content-Type": "text/html"},
        )
    )

    browser_targets = asyncio.run(
        _run_http_extraction(
            [item],
            config,
            tmp_path,
            transport=transport,
        )
    )

    assert browser_targets == [item]
    assert item["content_status"] == ContentStatus.METADATA_ONLY


def test_http_access_failure_stays_verification_required_without_browser_retry(
    tmp_path: Path,
):
    config = load_config()
    item = _item("bbc-forbidden")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            403,
            text="<html><title>Access denied</title></html>",
            headers={"Content-Type": "text/html"},
        )
    )

    browser_targets = asyncio.run(
        _run_http_extraction(
            [item],
            config,
            tmp_path,
            transport=transport,
        )
    )

    assert browser_targets == []
    assert item["content_status"] == ContentStatus.VERIFICATION_REQUIRED
    assert item["metadata"]["content_challenge"]["required"] is True


def test_content_pipeline_reuses_existing_successful_content(monkeypatch, tmp_path: Path):
    config = load_config()
    content_path = tmp_path / "content" / "bbc_world" / "cached" / "body.md"
    content_path.parent.mkdir(parents=True)
    content_path.write_text("cached article", encoding="utf-8")
    item = _item("cached")
    item.update(
        {
            "content_status": ContentStatus.FULL_TEXT,
            "content_path": str(content_path),
        }
    )

    async def unexpected_http(*_args, **_kwargs):
        raise AssertionError("HTTP must not run for reusable content")

    async def unexpected_browser(*_args, **_kwargs):
        raise AssertionError("browser must not run for reusable content")

    monkeypatch.setattr(
        "daily_intelligence.content._run_http_extraction",
        unexpected_http,
    )
    monkeypatch.setattr(
        "daily_intelligence.content._extract_with_browser",
        unexpected_browser,
    )

    metrics = asyncio.run(
        _extract_pipeline(
            [item],
            config,
            tmp_path,
            False,
            tmp_path / "profile",
            None,
        )
    )

    assert metrics["cache_hits"] == 1
    assert metrics["http_attempted"] == 0
    assert metrics["browser_fallback"] == 0
    assert item["metadata"]["content_acquisition"] == "cache"


def test_enriched_root_items_are_mirrored_to_legacy_nested_items():
    payload = {
        "items": [
            {
                "item_id": "item-1",
                "content_status": "full_text",
                "content_path": "content/item-1.md",
            }
        ],
        "sources": [
            {
                "source_id": "source-1",
                "items": [{"item_id": "item-1", "content_status": "not_fetched"}],
            }
        ],
    }

    synchronize_nested_items(payload)

    nested = payload["sources"][0]["items"][0]
    assert nested == payload["items"][0]
    assert nested["content_status"] == "full_text"



def test_enrichment_targets_follow_importance_order_and_hard_limit():
    items = [
        {"item_id": "low"},
        {"item_id": "high"},
        {"item_id": "medium"},
    ]

    targets = _ordered_targets(
        items,
        ["high", "medium", "high", "missing", "low"],
        max_items=2,
    )

    assert [item["item_id"] for item in targets] == ["high", "medium"]



def test_enrichment_is_parallel_across_domains_and_serial_within_domain(
    monkeypatch, tmp_path: Path
):
    config = load_config()
    config.browser.global_concurrency = 2
    config.browser.per_domain_concurrency = 1
    active = 0
    maximum_active = 0
    active_by_domain: dict[str, int] = defaultdict(int)
    maximum_by_domain: dict[str, int] = defaultdict(int)

    async def fake_extract_one(_context, item, _config, _data_dir):
        nonlocal active, maximum_active
        domain = item["url"].split("/")[2]
        active += 1
        active_by_domain[domain] += 1
        maximum_active = max(maximum_active, active)
        maximum_by_domain[domain] = max(
            maximum_by_domain[domain], active_by_domain[domain]
        )
        await asyncio.sleep(0.02)
        active_by_domain[domain] -= 1
        active -= 1

    monkeypatch.setattr("daily_intelligence.content._extract_one", fake_extract_one)
    targets = [
        {"item_id": "a1", "url": "https://a.example/1"},
        {"item_id": "a2", "url": "https://a.example/2"},
        {"item_id": "b1", "url": "https://b.example/1"},
        {"item_id": "c1", "url": "https://c.example/1"},
    ]

    asyncio.run(_run_parallel_extraction(object(), targets, config, tmp_path))

    assert maximum_active == 2
    assert maximum_by_domain["a.example"] == 1
