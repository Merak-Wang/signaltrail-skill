from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import httpx

from signaltrail.adapters import browser_items_from_rows
from signaltrail.collector import collect_source
from signaltrail.config import AppConfig, BrowserConfig, SourceConfig
from signaltrail.models import ArticleItem, SourceResult, SourceStatus
from signaltrail.prefetch import _prefetch_all, html_index_rows, page_needs_browser


def _source(
    source_id: str = "example",
    url: str = "https://example.com/news",
    explore_urls: list[str] | None = None,
) -> SourceConfig:
    domain = url.split("/")[2]
    return SourceConfig(
        id=source_id,
        name=source_id,
        url=url,
        include_domains=[domain],
        article_patterns=[rf"^https://{domain}/articles/"],
        explore_urls=explore_urls or [],
        report_target=1,
        report_max=2,
    )


def test_public_html_rows_preserve_title_link_and_time_context():
    title, rows = html_index_rows(
        """
        <html><head><title>Example News</title></head><body>
          <article><time datetime="2026-07-17T05:00:00+08:00"></time>
            <a href="/articles/one"><h2>A sufficiently long public headline</h2></a>
            <img src="/images/grey-placeholder.png" alt="">
            <img data-src="/images/one.jpg" alt="">
          </article>
        </body></html>
        """
    )

    assert title == "Example News"
    assert rows[0]["href"] == "/articles/one"
    assert rows[0]["title"] == "A sufficiently long public headline"
    assert "2026-07-17" in rows[0]["context"]
    assert rows[0]["image_url"] == "/images/one.jpg"
    assert rows[0]["image_candidates"] == ["/images/one.jpg"]
    items = browser_items_from_rows(
        rows,
        _source(),
        "2026-07-17T06:00:00+08:00",
        "https://example.com/news",
    )
    assert items[0].image_url == "https://example.com/images/one.jpg"



def test_yicai_firstlist_dates_bind_to_urls_without_changing_order(tmp_path):
    source = replace(
        _source("yicai_economy", "https://www.yicai.com/news/"),
        article_patterns=[r"^https://www\.yicai\.com/news/\d+\.html$"],
        collect_all_items=True, include_domains=["yicai.com"],
    )
    html = """
    <a href="/news/2.html">Second article headline about the economy</a>
    <a href="/news/1.html">First article headline about the economy</a>
    <a href="/news/3.html">Third article headline about the economy</a>
    <script>var firstlist = [
      {"NewsID":1,"url":"/news/1.html","CreateDate":"2026-11-06T13:53:03",
       "LastDate":"2026-11-05T11:00:00"},
      {"NewsID":2,"url":"/news/2.html","CreateDate":"2026-11-06T12:00:00"},
      {"NewsID":4,"url":"/news/4.html","CreateDate":"2026-11-06T14:00:00"}
    ];</script>
    """
    config = AppConfig(timezone="Asia/Shanghai", browser=BrowserConfig(), sources=[source])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=html))
    result = asyncio.run(_prefetch_all([source], config, tmp_path, transport=transport))
    items = result[(source.id, source.url)].items

    assert [item.url for item in items] == [
        "https://www.yicai.com/news/2.html", "https://www.yicai.com/news/1.html",
        "https://www.yicai.com/news/3.html",
    ]
    assert [item.published_at for item in items] == [
        "2026-11-06T12:00:00+08:00", "2026-11-06T13:53:03+08:00", None,
    ]
    assert items[1].metadata["yicai_create_date"] == "2026-11-06T13:53:03"

def test_missing_card_image_does_not_turn_the_index_page_into_an_image():
    items = browser_items_from_rows(
        [
            {
                "title": "A sufficiently long public headline",
                "href": "/articles/one",
                "context": "",
                "image_url": "",
            }
        ],
        _source(),
        "2026-07-17T06:00:00+08:00",
        "https://example.com/news",
    )

    assert items[0].image_url is None


def test_static_index_prefers_srcset_width_over_fallback_src():
    _title, rows = html_index_rows(
        "<article><a href='/articles/one'>A sufficiently long public headline</a>"
        "<img src='/small.jpg' srcset='/large.jpg 1600w, /small.jpg 400w'></article>"
    )
    assert rows[0]["image_url"] == "/large.jpg"


def test_browser_index_uses_shared_srcset_parser_and_keeps_observed_dimensions():
    items = browser_items_from_rows([{
        "title": "A sufficiently long public headline", "href": "/articles/one",
        "image_sources": [{
            "srcset": "/large.jpg 1600w, /small.jpg 400w", "current_src": "/small.jpg",
            "natural_width": 400, "natural_height": 300,
        }],
    }], _source(), "2026-09-11T06:00:00+08:00", "https://example.com/")
    assert items[0].image_url == "https://example.com/large.jpg"
    assert items[0].metadata["image_source_observations"][0]["natural_width"] == 400


def test_parallel_prefetch_obeys_global_and_per_domain_limits(tmp_path: Path):
    config = AppConfig(
        timezone="Asia/Shanghai",
        browser=BrowserConfig(
            collection_global_concurrency=2,
            collection_per_domain_concurrency=1,
        ),
        sources=[],
    )
    sources = [
        _source(
            "alpha",
            "https://alpha.example/news",
            ["https://alpha.example/world"],
        ),
        _source("beta", "https://beta.example/news"),
    ]
    active = 0
    maximum_active = 0
    active_by_domain: defaultdict[str, int] = defaultdict(int)
    maximum_by_domain: defaultdict[str, int] = defaultdict(int)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        domain = request.url.host
        active += 1
        active_by_domain[domain] += 1
        maximum_active = max(maximum_active, active)
        maximum_by_domain[domain] = max(
            maximum_by_domain[domain], active_by_domain[domain]
        )
        await asyncio.sleep(0.02)
        active_by_domain[domain] -= 1
        active -= 1
        return httpx.Response(
            200,
            text=(
                '<article><a href="/articles/story">'
                "A sufficiently long public headline</a></article>"
            ),
        )

    results = asyncio.run(
        _prefetch_all(
            sources,
            config,
            tmp_path,
            transport=httpx.MockTransport(handler),
        )
    )

    assert len(results) == 3
    assert maximum_active == 2
    assert maximum_by_domain["alpha.example"] == 1
    assert all(result.status == SourceStatus.SUCCESS for result in results.values())


def test_successful_prefetch_bypasses_edge(tmp_path: Path):
    source = _source()
    config = AppConfig(
        timezone="Asia/Shanghai",
        browser=BrowserConfig(),
        sources=[source],
    )
    item = ArticleItem(
        item_id="example-1",
        source_id=source.id,
        source_name=source.name,
        title="A sufficiently long public headline",
        url="https://example.com/articles/one",
        canonical_url="https://example.com/articles/one",
        discovered_at="2026-07-17T06:00:00+08:00",
    )
    prefetched = SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        status=SourceStatus.SUCCESS,
        collected_at="2026-07-17T06:00:00+08:00",
        items=[item],
    )

    result = collect_source(
        None,
        source,
        config,
        tmp_path,
        {(source.id, source.url): prefetched},
    )

    assert result.status == SourceStatus.SUCCESS
    assert result.items == [item]


def test_rate_limit_is_not_retried_in_edge_but_empty_public_html_is():
    rate_limited = SourceResult(
        source_id="reuters",
        source_name="Reuters",
        source_url="https://reuters.com",
        status=SourceStatus.RATE_LIMITED,
        collected_at="2026-07-17T06:00:00+08:00",
    )
    empty = SourceResult(
        source_id="example",
        source_name="Example",
        source_url="https://example.com",
        status=SourceStatus.NO_ITEMS,
        collected_at="2026-07-17T06:00:00+08:00",
    )

    assert page_needs_browser(rate_limited) is False
    assert page_needs_browser(empty) is True


def test_picture_and_lazy_srcset_are_index_image_candidates():
    _, rows = html_index_rows("""<article><a href='/articles/one'>A detailed headline</a>
        <picture><source data-srcset='/large.webp 1600w, /medium.webp 800w'>
        <img src='/small.jpg'></picture></article>""")
    assert rows[0]["image_candidates"] == ["/large.webp", "/medium.webp", "/small.jpg"]


def test_prefetch_stops_stream_at_limit_and_marks_partial(monkeypatch, tmp_path):
    consumed = []
    closed = []
    page = b'<article><a href="/articles/one">A sufficiently long headline</a></article>'

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in [page, b"x" * 100, b"must not be downloaded"]:
                consumed.append(part)
                yield part

        async def aclose(self):
            closed.append(True)

    config = AppConfig(timezone="UTC", browser=BrowserConfig(
        http_prefetch_max_bytes=len(page) + 10), sources=[])
    results = asyncio.run(_prefetch_all(
        [_source()], config, tmp_path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Stream())),
    ))
    result = next(iter(results.values()))
    assert len(consumed) == 2
    assert closed == [True]
    assert result.status == SourceStatus.PARTIAL
    assert len(result.items) == 1
    assert result.challenge["response_truncated"] is True
    assert page_needs_browser(result)


def test_prefetch_keeps_public_index_with_captcha_script_as_success(tmp_path):
    source = _source()
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    page = (
        '<script src="https://o.alicdn.com/captcha-frontend/AliyunCaptcha.js"></script>'
        '<article><a href="/articles/one">A detailed public market headline</a></article>'
    )
    results = asyncio.run(_prefetch_all(
        [source], config, tmp_path,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, text=page)),
    ))

    result = results[(source.id, source.url)]
    assert result.status == SourceStatus.SUCCESS
    assert len(result.items) == 1
    assert result.challenge["required"] is False


def test_busy_domain_does_not_starve_other_domains(tmp_path):
    async def run():
        other_started = asyncio.Event()

        async def handler(request):
            if request.url.host == "busy.example":
                await asyncio.wait_for(other_started.wait(), 1)
            else:
                other_started.set()
            return httpx.Response(200, text='<a href="/articles/one">A detailed news headline</a>')

        config = AppConfig(timezone="UTC", sources=[], browser=BrowserConfig(
            collection_global_concurrency=2, collection_per_domain_concurrency=1,
        ))
        sources = [_source(str(i), "https://busy.example/news") for i in range(4)]
        sources.append(_source("other", "https://other.example/news"))
        return await _prefetch_all(
            sources, config, tmp_path, transport=httpx.MockTransport(handler),
        )

    results = asyncio.run(run())
    assert len(results) == 5
    assert all(result.status == SourceStatus.SUCCESS for result in results.values())


def test_browser_fallback_keeps_http_candidates_and_attempts(tmp_path):
    source = _source()
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    item = browser_items_from_rows([{
        "title": "A sufficiently long public headline", "href": "/articles/one",
    }], source, "2026-07-17T06:00:00+08:00", source.url)[0]
    http = SourceResult(source.id, source.name, source.url, SourceStatus.PARTIAL,
                        "2026-07-17T06:00:00+08:00", error="truncated",
                        challenge={"response_truncated": True}, items=[item])
    browser = SourceResult(source.id, source.name, source.url, SourceStatus.FAILED,
                           "2026-07-17T06:00:00+08:00", error="browser failed")
    result = collect_source(None, source, config, tmp_path,
                            {(source.id, source.url): http},
                            browser_results={(source.id, source.url): browser})
    assert result.status == SourceStatus.PARTIAL
    assert result.items == [item]
    assert [(p["acquisition_method"], p["error"]) for p in result.page_results] == [
        ("http", "truncated"), ("browser", "browser failed")]


def test_successful_browser_fallback_keeps_http_failure_as_diagnostic(tmp_path):
    source = _source()
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    item = browser_items_from_rows([{
        "title": "A sufficiently long public headline", "href": "/articles/one",
    }], source, "2026-07-17T06:00:00+08:00", source.url)[0]
    http = SourceResult(source.id, source.name, source.url, SourceStatus.FAILED,
                        "2026-07-17T06:00:00+08:00", error="connection failed")
    browser = SourceResult(source.id, source.name, source.url, SourceStatus.SUCCESS,
                           "2026-07-17T06:00:00+08:00", items=[item])
    result = collect_source(None, source, config, tmp_path,
                            {(source.id, source.url): http},
                            browser_results={(source.id, source.url): browser})
    assert result.status == SourceStatus.SUCCESS
    assert result.items == [item]
    assert result.page_results[0]["error"] == "connection failed"
    assert [p["acquisition_method"] for p in result.page_results] == ["http", "browser"]



def test_prefetch_retries_connection_error_once(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, text='<a href="/articles/one">A detailed news headline</a>')

    source = _source()
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    result = asyncio.run(_prefetch_all(
        [source], config, tmp_path, transport=httpx.MockTransport(handler),
    ))[(source.id, source.url)]
    assert len(calls) == 2
    assert result.status == SourceStatus.SUCCESS
    assert result.error is None
    assert result.challenge["attempt_count"] == 2
    assert "connection reset" in result.challenge["first_transport_error"]


def test_prefetch_does_not_retry_http_rejections_or_certificate_errors(tmp_path):
    for outcome in (403, 429, "certificate"):
        calls = []

        def handler(request, calls=calls, outcome=outcome):
            calls.append(request)
            if outcome == "certificate":
                raise httpx.ConnectError("certificate verify failed", request=request)
            return httpx.Response(outcome, text="Access denied")

        source = _source()
        config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
        result = asyncio.run(_prefetch_all(
            [source], config, tmp_path, transport=httpx.MockTransport(handler),
        ))[(source.id, source.url)]
        assert len(calls) == 1
        assert result.challenge["attempt_count"] == 1


def test_browser_failure_preserves_http_verification_status(tmp_path):
    source = _source()
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    http = SourceResult(source.id, source.name, source.url, SourceStatus.VERIFICATION_REQUIRED,
                        "2026-07-17T06:00:00+08:00", error="HTTP 403",
                        challenge={"required": True, "matched_text": "verify you are human"})
    browser = SourceResult(source.id, source.name, source.url, SourceStatus.FAILED,
                           "2026-07-17T06:00:00+08:00", error="HTTP 403")
    result = collect_source(None, source, config, tmp_path,
                            {(source.id, source.url): http},
                            browser_results={(source.id, source.url): browser})
    assert result.status == SourceStatus.VERIFICATION_REQUIRED
    assert result.page_results[0]["challenge"]["required"] is True
    assert result.page_results[1]["error"] == "HTTP 403"


def test_live_item_inherits_missing_original_date_from_same_feed(tmp_path):
    from dataclasses import replace

    from signaltrail.article_time import original_publication_time
    from signaltrail.collector import _merge_monitor_evidence

    source = _source()
    live = browser_items_from_rows([{
        "title": "A sufficiently long public headline", "href": "/articles/one",
    }], source, "2026-11-06T15:00:00+08:00", source.url)[0]
    cached = replace(live, published_at="2026-11-06T13:39:30+08:00", metadata={
        "published_raw": "Fri, 06 Nov 2026 00:39:30 -0500",
        "published_precision": "datetime", "feed_url": "https://example.com/feed",
    })
    merged = _merge_monitor_evidence(live, cached, tmp_path)
    assert original_publication_time(merged.to_dict()) == "2026-11-06T13:39:30+08:00"
    assert merged.metadata["feed_url"] == "https://example.com/feed"
    assert merged.metadata["published_raw"] == cached.metadata["published_raw"]
    dated = replace(live, published_at="2026-11-05T10:00:00+08:00")
    assert _merge_monitor_evidence(dated, cached, tmp_path).published_at == dated.published_at


def test_platform_feed_time_does_not_replace_original_publication(tmp_path):
    from dataclasses import replace

    from signaltrail.collector import _merge_monitor_evidence

    source = _source()
    live = browser_items_from_rows([{
        "title": "A sufficiently long public headline", "href": "/articles/one",
    }], source, "2026-11-06T15:00:00+08:00", source.url)[0]
    live.metadata["publication_time_kind"] = "platform"
    cached = replace(live, published_at="2026-11-06T13:00:00+08:00")
    assert _merge_monitor_evidence(live, cached, tmp_path).published_at is None
