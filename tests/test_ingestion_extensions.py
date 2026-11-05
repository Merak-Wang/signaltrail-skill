import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from signaltrail.config import (
    AppConfig,
    BrowserConfig,
    RSSHubConfig,
    SourceConfig,
    load_config,
)
from signaltrail.content import _extract_pipeline
from signaltrail.monitor import _feed_phase
from signaltrail.utils import read_json


def test_rsshub_route_uses_configured_instance_and_existing_feed_pipeline(tmp_path):
    source = SourceConfig(
        id="rsshub", name="RSSHub", url="https://news.example/",
        feed_urls=["https://news.example/rss"], rsshub_route="/news/latest?limit=20",
    )
    config = AppConfig(
        timezone="Asia/Shanghai", browser=BrowserConfig(), sources=[source],
        rsshub=RSSHubConfig(base_url="http://127.0.0.1:1200/"),
    )
    config.monitor.auto_discover_feeds = False
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, text="""<rss><channel><item>
          <title>A report from the configured route</title>
          <link>https://news.example/story</link>
          </item></channel></rss>""")

    feeds, _, _ = asyncio.run(_feed_phase(
        [source], config, tmp_path, force=True,
        checked_at="2026-11-02T10:00:00+08:00", transport=httpx.MockTransport(handler),
    ))
    assert source.feed_urls == [
        "https://news.example/rss", "http://127.0.0.1:1200/news/latest?limit=20",
    ]
    assert set(seen) == set(source.feed_urls)
    assert all(result.items[0].title == "A report from the configured route"
               for result in feeds[source.id])


@pytest.mark.parametrize("extra", [
    "rsshub:\n  base_url: ''\n",
    "rsshub:\n  base_url: ftp://example.com\n",
])
def test_rsshub_route_requires_an_instance(tmp_path, extra):
    path = tmp_path / "sources.yaml"
    path.write_text(extra + "sources:\n- id: route\n  name: Route\n"
                    "  url: https://example.com\n  rsshub_route: /news/latest\n", "utf-8")
    with pytest.raises(ValueError, match="rsshub.base_url"):
        load_config(path)


@pytest.mark.parametrize("blocked", [False, True])
def test_optional_crawl4ai_backend_records_real_content_and_access_status(
    monkeypatch, tmp_path, blocked,
):
    config = load_config()
    config.collection.browser_extractor = "crawl4ai"
    config.collection.retain_public_html = True
    item = {
        "item_id": "dynamic", "source_id": "bbc_world", "title": "Service update",
        "url": "https://www.bbc.com/news/articles/dynamic", "metadata": {},
        "content_status": "not_fetched",
    }
    markup = (
        "<html><head><meta property='og:title' content='Service update'></head>"
        "<body><article><h1>Service update</h1><p>"
        + "The service publishes detailed terms for its current customers. " * 20
        + "</p></article></body></html>"
    )
    if blocked:
        markup = "<html><title>Verify you are human</title><body>Access denied</body></html>"
    captured = {}

    class Crawler:
        def __init__(self, config):
            captured["browser"] = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def arun(self, url, config):
            captured["run"] = config
            return SimpleNamespace(
                html=markup, redirected_url=url, status_code=429 if blocked else 200,
                success=not blocked, error_message="rate limited" if blocked else None,
                media={"images": [{"src": "/photo.jpg"}],
                       "videos": [{"src": "https://video.example/story.mp4"}]},
            )

    monkeypatch.setitem(sys.modules, "crawl4ai", SimpleNamespace(
        AsyncWebCrawler=Crawler, BrowserConfig=SimpleNamespace,
        CrawlerRunConfig=SimpleNamespace, CacheMode=SimpleNamespace(DISABLED="disabled"),
    ))

    async def http(targets, *_args):
        return targets

    async def unexpected_browser(*_args):
        raise AssertionError("Crawl4AI replaces this browser attempt")

    monkeypatch.setattr("signaltrail.content._run_http_extraction", http)
    monkeypatch.setattr("signaltrail.content._extract_with_browser", unexpected_browser)
    metrics = asyncio.run(_extract_pipeline(
        [item], config, tmp_path, False, tmp_path / "profile", None,
    ))
    assert metrics["browser_extractor"] == "crawl4ai"
    assert item["metadata"]["content_attempts"][-1]["channel"] == "crawl4ai"
    assert captured["run"].cache_mode == "disabled"
    assert captured["run"].max_scroll_steps == 8
    assert not list(tmp_path.rglob("*.response.bin"))
    if blocked:
        assert item["content_status"] == "verification_required"
        assert item["metadata"]["content_challenge"]["rate_limited"] is True
        assert metrics["complete"] == 0
        assert not item.get("content_path")
    else:
        assert item["content_status"] == "full_text"
        assert "detailed terms" in Path(item["content_path"]).read_text("utf-8")
        artifact = read_json(Path(item["metadata"]["content_blocks_path"]))
        assert artifact["acquisition"] == "crawl4ai"
        assert artifact["input"]["kind"] == "visible_dom_utf8"
        assert item["image_url"] == "https://www.bbc.com/photo.jpg"
        assert item["metadata"]["video_candidates"][0]["url"].endswith("story.mp4")

def test_crawl4ai_same_domain_queue_does_not_hold_global_slots(monkeypatch):
    from signaltrail.crawl4ai_adapter import crawl_pages

    async def exercise():
        release = asyncio.Event()
        fast_started = asyncio.Event()

        class Crawler:
            def __init__(self, config):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            async def arun(self, url, config):
                if "slow.example" in url:
                    await release.wait()
                else:
                    fast_started.set()
                return SimpleNamespace(html="<article>Evidence</article>", redirected_url=url,
                                       status_code=200, success=True, error_message=None, media={})

        monkeypatch.setitem(sys.modules, "crawl4ai", SimpleNamespace(
            AsyncWebCrawler=Crawler, BrowserConfig=SimpleNamespace,
            CrawlerRunConfig=SimpleNamespace, CacheMode=SimpleNamespace(DISABLED="disabled"),
        ))
        task = asyncio.create_task(crawl_pages(
            ["https://slow.example/one", "https://slow.example/two", "https://fast.example/news"],
            timeout_ms=5000, concurrency=2, per_domain_concurrency=1,
        ))
        try:
            await asyncio.wait_for(fast_started.wait(), timeout=1)
        finally:
            release.set()
            results = await task
        assert len(results) == 3
        assert all(result["success"] for result in results)

    asyncio.run(exercise())
