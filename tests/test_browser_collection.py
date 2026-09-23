import asyncio
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest

from signaltrail import browser_collection
from signaltrail.browser_collection import collect_browser_page, collect_browser_pages
from signaltrail.collector import collect_sources
from signaltrail.config import AppConfig, BrowserConfig, SourceConfig
from signaltrail.models import SourceResult
from signaltrail.utils import read_json


class Page:
    def __init__(self, code=200, fail=False):
        self.code = code
        self.fail = fail
        self.url = "https://example.com/news"
        self.closed = False
        self.fixed_waits = []
        self.ready_waits = []

    async def goto(self, url, **kwargs):
        self.url = url
        if self.fail:
            raise RuntimeError("navigation failed")
        return SimpleNamespace(status=self.code)

    async def title(self):
        return "Example News"

    def locator(self, selector):
        return self

    @property
    def first(self):
        return self

    async def inner_text(self, **kwargs):
        return "Available content"

    async def count(self):
        return 0

    async def evaluate_all(self, script):
        return [{"title": "A sufficiently detailed report headline", "href": "/story"}]

    async def wait_for_function(self, script, **kwargs):
        self.ready_waits.append("function")

    async def wait_for(self, **kwargs):
        self.ready_waits.append("selector")

    async def wait_for_timeout(self, value):
        self.fixed_waits.append(value)

    async def close(self):
        self.closed = True


class Context:
    def __init__(self, page):
        self.page = page

    async def new_page(self):
        return self.page


@pytest.mark.parametrize(
    "code, fail, status",
    [
        (200, False, "success"),
        (429, False, "rate_limited"),
        (403, False, "verification_required"),
        (503, False, "failed"),
        (200, True, "failed"),
    ],
)
def test_browser_page_classifies_failures_and_always_closes(code, fail, status):
    source = SourceConfig(id="example", name="Example", url="https://example.com/news")
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    page = Page(code, fail)
    result = asyncio.run(collect_browser_page(Context(page), source, config))
    assert result.status == status
    assert bool(result.items) == (status == "success")
    assert page.closed
    assert page.fixed_waits == []


@pytest.mark.parametrize(
    "selector, wait_ms, ready, waits",
    [
        (None, None, ["function"], []),
        ("article a", None, ["selector"], []),
        ("article a", 25, [], [25]),
        (None, 0, [], [0]),
    ],
)
def test_browser_wait_uses_readiness_and_honors_explicit_delay(selector, wait_ms, ready, waits):
    source = SourceConfig(
        id="example",
        name="Example",
        url="https://example.com/news",
        ready_selector=selector,
        wait_ms=wait_ms,
    )
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
    page = Page()
    asyncio.run(collect_browser_page(Context(page), source, config))
    assert page.ready_waits == ready
    assert page.fixed_waits == waits


def test_browser_pool_owns_one_context_and_is_fair_and_ordered(monkeypatch, tmp_path):
    source = SourceConfig(id="busy0", name="Busy", url="https://busy.example/0")
    sources = [replace(source, id=f"busy{i}", url=f"https://busy.example/{i}") for i in range(3)]
    sources.append(replace(source, id="other", url="https://other.example/"))
    config = AppConfig(
        timezone="UTC",
        browser=BrowserConfig(
            global_concurrency=2,
            per_domain_concurrency=1,
        ),
        sources=sources,
    )
    launched = []
    closed = []
    completed = []
    maximum = Counter()
    active = Counter()

    async def close():
        closed.append(True)

    context = SimpleNamespace(close=close)

    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=self.launch))

        async def __aexit__(self, *args):
            pass

        async def launch(self, **kwargs):
            launched.append(kwargs)
            return context

    async def run():
        other_started = asyncio.Event()

        async def page_worker(received_context, source, _config):
            assert received_context is context
            domain = source.url.split("/")[2]
            for key in [domain, "all"]:
                active[key] += 1
                maximum[key] = max(maximum[key], active[key])
            if domain == "busy.example":
                await asyncio.wait_for(other_started.wait(), 1)
            else:
                other_started.set()
            await asyncio.sleep(0)
            for key in [domain, "all"]:
                active[key] -= 1
            completed.append(source.id)
            return SourceResult(source.id, source.name, source.url, "success", "2026-09-20")

        monkeypatch.setattr(browser_collection, "collect_browser_page", page_worker)
        return await collect_browser_pages(sources, config, tmp_path, None, False)

    monkeypatch.setattr(browser_collection, "async_playwright", Playwright)
    results = asyncio.run(run())
    assert len(launched) == 1
    assert closed == [True]
    assert maximum["all"] == 2
    assert maximum["busy.example"] == 1
    assert completed[0] == "other"
    assert list(results) == [(source.id, source.url) for source in sources]


def test_collect_sources_merges_async_failures_without_retrying(monkeypatch, tmp_path):
    sources = [
        SourceConfig(id=name, name=name, url=f"https://{name}.example/")
        for name in ["first", "second"]
    ]
    config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=sources)
    monkeypatch.setattr("signaltrail.collector.load_monitor_results", lambda *_: {})
    monkeypatch.setattr("signaltrail.collector.prefetch_browser_pages", lambda *_: {})

    async def pages(selected, *_args):
        return {
            (source.id, source.url): SourceResult(
                source.id,
                source.name,
                source.url,
                "rate_limited",
                "2026-09-20",
                http_status=429,
            )
            for source in reversed(selected)
        }

    monkeypatch.setattr("signaltrail.collector.collect_browser_pages", pages)
    index = read_json(
        collect_sources(config, tmp_path, "morning", False, profile_dir=tmp_path / "profile")
    )
    assert [source["source_id"] for source in index["sources"]] == ["first", "second"]
    assert all(source["status"] == "rate_limited" for source in index["sources"])


def test_cancelled_page_is_closed_and_next_task_can_use_its_slot():
    async def run():
        started = asyncio.Event()

        class WaitingPage(Page):
            async def goto(self, url, **kwargs):
                started.set()
                await asyncio.Event().wait()

        page = WaitingPage()
        source = SourceConfig(id="cancel", name="Cancel", url="https://example.com/")
        config = AppConfig(timezone="UTC", browser=BrowserConfig(), sources=[source])
        slot = asyncio.Semaphore(1)

        async def worker():
            async with slot:
                return await collect_browser_page(Context(page), source, config)

        task = asyncio.create_task(worker())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert page.closed
        await asyncio.wait_for(slot.acquire(), 1)
        slot.release()

    asyncio.run(run())
