from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from daily_intelligence.config import load_config
from daily_intelligence.content import (
    _apply_http_document,
    _extract_pipeline,
    _ordered_targets,
    _run_http_extraction,
    _run_parallel_extraction,
    extract_visible_text,
    synchronize_nested_items,
)
from daily_intelligence.content_extraction import extract_document
from daily_intelligence.models import ContentStatus
from daily_intelligence.utils import read_json


def test_short_article_beats_long_related_body_and_preserves_structured_evidence(tmp_path):
    document = (
        "<html><body><article><h1>正式公告</h1>"
        "<p>自2026年9月12日起，服务价格调整为每月10元，其他条件不变。</p>"
        "<p>现有用户在当前订阅期内继续适用原价格，无需额外操作。</p>"
        "<ul><li>适用地区：中国。</li><li>结算单位：人民币。</li></ul>"
        "<table><tr><th>方案</th><th>价格（元/月）</th></tr>"
        "<tr><td>标准</td><td>10</td></tr></table></article><div>"
        + "RELATED_STORY " * 300 + "</div></body></html>"
    )
    config = load_config()
    item = _item()
    retry = _apply_http_document(
        item, config.source_by_id(item["source_id"]), document, item["url"], 200,
        config, tmp_path,
    )
    assert retry is False
    assert item["content_status"] == ContentStatus.FULL_TEXT
    assert item["metadata"]["content_quality"]["extraction_status"] == "short_complete"
    assert item["metadata"]["content_selector"] == "article"
    text = Path(item["content_path"]).read_text(encoding="utf-8")
    assert "RELATED_STORY" not in text
    assert "条件不变。\n\n现有用户" in text
    blocks = read_json(Path(item["metadata"]["content_blocks_path"]))["blocks"]
    assert [block["type"] for block in blocks] == [
        "heading", "paragraph", "paragraph", "list_item", "list_item", "table",
    ]
    assert [cell["text"] for cell in blocks[-1]["rows"][0]] == ["方案", "价格（元/月）"]
    assert [cell["text"] for cell in blocks[-1]["rows"][1]] == ["标准", "10"]


@pytest.mark.parametrize(("markup", "status", "quality"), [
    ("<body>" + "Long but unbounded page content. " * 100 + "</body>",
     ContentStatus.PARTIAL, "partial"),
    ("<article><h1>A headline with no article body at all</h1></article>",
     ContentStatus.METADATA_ONLY, "insufficient"),
    ("<article>Loading</article>", ContentStatus.METADATA_ONLY, "insufficient"),
    ("<article><p>Available opening paragraph about the announcement.</p>"
     "<p>Subscribe to read the full article.</p></article>", ContentStatus.PARTIAL, "partial"),
    ("<article>" + "<a href='/other'>Linked recommendation without body</a>" * 100
     + "</article>", ContentStatus.METADATA_ONLY, "insufficient"),
])
def test_content_quality_does_not_equate_length_or_successful_access_with_full_text(
    markup, status, quality,
):
    result = extract_document(BeautifulSoup(markup, "html.parser"), ["article", "main"])
    assert result.status == status
    assert result.quality["extraction_status"] == quality


def test_multiple_article_candidates_ignore_link_farm_and_hidden_recommendations():
    soup = BeautifulSoup(
        "<body><article><a href='/x'>" + "Recommendations " * 200 + "</a></article>"
        "<article><p>The service will resume on Monday, with the existing terms unchanged.</p>"
        "<div class='related-content'>UNRELATED</div><p hidden>HIDDEN</p></article></body>",
        "html.parser",
    )
    result = extract_document(soup, ["body", "article"])
    assert result.status == ContentStatus.FULL_TEXT
    assert result.text == "The service will resume on Monday, with the existing terms unchanged."


def test_inline_words_chinese_and_table_spans_survive_extraction():
    result = extract_document(BeautifulSoup(
        "<article><p>价格为<strong>10</strong>元；un<strong>changed</strong> terms remain.</p>"
        "<table><tr><th colspan='2'>Monthly price</th></tr>"
        "<tr><td>Plan A</td><td>10 USD</td></tr></table></article>", "html.parser",
    ), ["article"])
    assert "价格为10元；unchanged terms remain." in result.text
    assert result.blocks[-1]["rows"][0][0]["colspan"] == "2"


def test_nested_list_paragraphs_quotes_and_preformatted_text_keep_structure():
    result = extract_document(BeautifulSoup(
        "<article><ol><li><p>First ordered condition remains applicable.</p>"
        "<ul><li>A nested exception.</li></ul></li></ol>"
        "<blockquote><p>The source explicitly states this qualification.</p></blockquote>"
        "<pre>if ready:\n    publish()\n</pre></article>", "html.parser",
    ), ["article"])
    assert result.blocks[0]["type"] == "list_item"
    assert result.blocks[0]["ordered"] is True
    assert result.blocks[1]["list_depth"] == 2
    assert result.blocks[2]["type"] == "quote"
    assert result.blocks[3]["text"] == "if ready:\n    publish()\n"


def test_browser_and_static_paths_use_the_same_short_article_rule():
    markup = (
        "<body><article><p>The official announcement takes effect tomorrow at noon.</p>"
        "<p>Existing subscriptions retain the agreed price until renewal.</p></article>"
        + "Other news " * 400 + "</body>"
    )

    class PageSnapshot:
        def locator(self, _selector):
            return self

        async def evaluate_all(self, _script):
            pass

        async def content(self):
            return markup

    result = extract_document(BeautifulSoup(markup, "html.parser"), ["article"])
    text, selector = asyncio.run(extract_visible_text(PageSnapshot(), ["article"]))
    assert (text, selector) == (result.text, "article")
    assert "Other news" not in text


def test_http_byte_limit_records_partial_content(monkeypatch, tmp_path):
    from daily_intelligence import content

    config = load_config()
    item = _item()
    original_read = content._read_bounded_html

    async def bounded(response):
        return await original_read(response, max_bytes=1800)

    monkeypatch.setattr(content, "_read_bounded_html", bounded)
    transport = httpx.MockTransport(lambda _: httpx.Response(
        200, text="<article>" + "Official document paragraph. " * 200 + "</article>",
    ))
    asyncio.run(_run_http_extraction([item], config, tmp_path, transport=transport))
    assert item["content_status"] == ContentStatus.PARTIAL
    assert item["metadata"]["content_quality"]["response_truncated"] is True


def test_image_selection_uses_article_caption_before_unrelated_metadata(tmp_path):
    config = load_config()
    item = _item()
    item["title"] = "Orion reactor begins operation"
    markup = (
        "<head><meta property='og:image' content='/generic-brand.jpg'></head><body>"
        "<article><p>Orion reactor began operation on Monday after commissioning tests.</p>"
        "<img src='/brand.jpg' alt='Company logo'>"
        "<figure><img src='/small.jpg' srcset='/large.jpg 1600w, /small.jpg 400w' "
        "alt='Orion reactor'><figcaption>Orion reactor commissioning test.</figcaption></figure>"
        "<aside><img src='/unrelated.jpg'></aside></article></body>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )
    assert item["image_url"] == "https://www.bbc.com/large.jpg"
    details = item["metadata"]["image_candidate_details"]
    assert details[0]["caption"] == "Orion reactor commissioning test."
    assert details[0]["provenance"] == "article_body"
    assert details[0]["relevance_score"] > 0
    assert details[0]["semantic_verification"] == "not_performed"
    assert not any(entry["url"].endswith(("/brand.jpg", "/unrelated.jpg")) for entry in details)


def test_repeated_extraction_never_overwrites_prior_body_or_blocks(tmp_path):
    config = load_config()
    item = _item()
    source = config.source_by_id(item["source_id"])
    first = "<article><p>The official announcement takes effect on Monday.</p></article>"
    _apply_http_document(item, source, first, item["url"], 200, config, tmp_path)
    path = Path(item["content_path"])
    content = path.read_bytes()
    _apply_http_document(item, source, first.replace("Monday", "Tuesday"), item["url"], 200,
                         config, tmp_path)
    assert Path(item["content_path"]) != path
    assert path.read_bytes() == content
    assert path.with_suffix(".json").exists()


def test_unlabeled_article_image_does_not_displace_publisher_metadata(tmp_path):
    config = load_config()
    item = _item()
    markup = (
        "<head><meta property='og:image' content='/publisher.jpg'></head>"
        "<article><p>Official announcement about new reactor commissioning dates.</p>"
        "<img src='/unlabeled.jpg'></article>"
    )
    _apply_http_document(
        item, config.source_by_id(item["source_id"]), markup, item["url"], 200,
        config, tmp_path,
    )
    assert item["image_url"] == "https://www.bbc.com/publisher.jpg"


@pytest.mark.parametrize(("http_status", "expected"), [
    (403, ContentStatus.VERIFICATION_REQUIRED),
    (429, ContentStatus.VERIFICATION_REQUIRED),
    (500, ContentStatus.FAILED),
])
def test_non_html_error_response_keeps_access_failure(tmp_path, http_status, expected):
    item = _item()
    transport = httpx.MockTransport(lambda _: httpx.Response(http_status, json={"error": "failed"}))
    fallback = asyncio.run(
        _run_http_extraction([item], load_config(), tmp_path, transport=transport),
    )
    assert fallback == []
    assert item["content_status"] == expected


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
