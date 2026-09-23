from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, async_playwright

from .access import classify_access_text
from .adapters import (
    ARXIV_ROWS_JS,
    BROWSER_ROWS_JS,
    TWZ_ROWS_JS,
    YEAR_ROWS_JS,
    _clear_misattributed_descriptions,
    arxiv_items_from_rows,
    browser_items_from_rows,
    latest_year_url,
    seed_items_from_payload,
    twz_items_from_rows,
    weibo_items_from_payload,
)
from .config import AppConfig, SourceConfig
from .models import ArticleItem, SourceResult, SourceStatus
from .utils import now_iso


async def _wait_for_index(page: Page, source: SourceConfig, config: AppConfig) -> None:
    """处理：等待索引内容就绪，显式站点等待优先，避免普遍固定休眠。
    输入：导航后的页面、来源选择器及等待预算。
    输出：页面出现候选结构或等待到期后交给解析器，访问状态另行判定。
    """
    if source.wait_ms is not None:
        await page.wait_for_timeout(source.wait_ms)
        return
    timeout = max(1, config.browser.default_wait_ms)
    with contextlib.suppress(Exception):
        if source.ready_selector:
            await page.locator(source.ready_selector).first.wait_for(
                state="attached", timeout=timeout
            )
        elif source.adapter_name == "browser_index":
            await page.wait_for_function(
                """rules => Array.from(document.querySelectorAll('a[href]')).some(a =>
                    (a.innerText || a.getAttribute('title') || '').trim().length >= 8 &&
                    (!rules.include.length ||
                        rules.include.some(p => new RegExp(p).test(a.href))) &&
                    !rules.exclude.some(p => new RegExp(p).test(a.href)))""",
                arg={"include": source.article_patterns, "exclude": source.exclude_patterns},
                timeout=timeout,
            )
        else:
            selector = {
                "arxiv_index": "dl dt",
                "twz_index": "h3 a, a h3",
                "latest_year_index": "a[href]",
                "weibo_api": "body",
                "seed_papers": "body",
            }[source.adapter_name]
            await page.locator(selector).first.wait_for(state="attached", timeout=timeout)


async def _candidates(page: Page, source: SourceConfig, result: SourceResult) -> list[ArticleItem]:
    """处理：异步读取页面数据，复用现有适配器的过滤和条目转换算法。
    输入：就绪页面、来源配置与观察时间。
    输出：与同步验证入口使用相同规则的文章列表。
    """
    mode = source.adapter_name
    observed = result.collected_at
    if mode == "seed_papers":
        async with page.expect_response(
            lambda response: "get_article_list_v2" in response.url, timeout=30_000
        ) as pending:
            await page.reload(wait_until="domcontentloaded", timeout=45_000)
        response = await pending.value
        result.http_status = response.status
        if not response.ok:
            raise RuntimeError(f"ByteDance Seed papers API returned HTTP {response.status}")
        return seed_items_from_payload(await response.json(), source, observed)
    if mode == "weibo_api":
        return weibo_items_from_payload(
            json.loads(await page.locator("body").inner_text()),
            source,
            observed,
        )
    if mode == "latest_year_index":
        rows = await page.locator("a[href]").evaluate_all(YEAR_ROWS_JS)
        response = await page.goto(
            latest_year_url(rows), wait_until="domcontentloaded", timeout=45_000
        )
        result.http_status = response.status if response else None
        if response is None or not response.ok:
            raise RuntimeError(
                f"Latest year index returned HTTP {response.status if response else None}"
            )
        mode = "browser_index"
    if mode == "browser_index":
        rows = await page.locator("a[href]").evaluate_all(BROWSER_ROWS_JS)
        items = browser_items_from_rows(rows, source, observed, page.url)
    elif mode == "arxiv_index":
        rows = await page.locator("dl#articles dt, dl dt").evaluate_all(ARXIV_ROWS_JS)
        items = arxiv_items_from_rows(rows, source, observed)
    elif mode == "twz_index":
        rows = await page.locator("h3").evaluate_all(TWZ_ROWS_JS)
        items = twz_items_from_rows(rows, source, observed)
    else:
        raise ValueError(f"Unknown async source adapter {mode!r}")
    return _clear_misattributed_descriptions(items)


async def collect_browser_page(
    context: BrowserContext,
    source: SourceConfig,
    config: AppConfig,
) -> SourceResult:
    """处理：采集单页并关闭页面，失败只影响当前来源。
    输入：唯一浏览器上下文、当前页面来源配置及超时预算。
    输出：真实访问状态和候选；限流、验证及错误页不生成新闻条目。
    """
    result = SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        module=source.module,
        category=source.category,
        status=SourceStatus.FAILED,
        collected_at=now_iso(config.timezone),
    )
    page = None
    try:
        page = await context.new_page()
        response = await page.goto(
            source.url, wait_until="domcontentloaded", timeout=config.browser.navigation_timeout_ms
        )
        result.http_status = response.status if response else None
        if result.http_status is None or result.http_status < 400:
            await _wait_for_index(page, source, config)
        result.page_title = await page.title()
        body = await page.locator("body").inner_text(timeout=3000)
        iframe_count = await page.locator(
            'iframe[src*="captcha"], iframe[src*="challenge"], iframe[title*="challenge" i]'
        ).count()
        result.challenge = classify_access_text(
            result.http_status,
            result.page_title,
            body[:30000],
            iframe_detected=iframe_count > 0,
        )
        if result.challenge["rate_limited"]:
            result.status = SourceStatus.RATE_LIMITED
        elif result.challenge["required"]:
            result.status = SourceStatus.VERIFICATION_REQUIRED
        elif result.http_status is not None and result.http_status >= 400:
            result.status = SourceStatus.FAILED
        else:
            result.items = await _candidates(page, source, result)
            result.status = SourceStatus.SUCCESS if result.items else SourceStatus.NO_ITEMS
        if result.http_status is not None and result.http_status >= 400:
            result.error = f"HTTP {result.http_status}"
    except Exception as exc:
        result.challenge = classify_access_text(result.http_status, "", "")
        result.status = (
            SourceStatus.RATE_LIMITED if result.challenge["rate_limited"] else
            SourceStatus.VERIFICATION_REQUIRED if result.challenge["required"] else
            SourceStatus.FAILED
        )
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if page is not None:
            result.final_url = page.url
            with contextlib.suppress(Exception):
                await page.close()
    return result


async def collect_browser_pages(
    sources: list[SourceConfig],
    config: AppConfig,
    profile: Path,
    channel: str | None,
    headed: bool,
) -> dict[tuple[str, str], SourceResult]:
    """处理：在一个持久会话内有界并发采集页面，统一拥有和关闭 profile。
    输入：需要浏览器的来源页面列表、并发配置和浏览器启动参数。
    输出：按输入顺序构造的页面结果表，供原来源合并逻辑使用。
    """
    global_limit = asyncio.Semaphore(max(1, config.browser.global_concurrency))
    domain_limits = defaultdict(
        lambda: asyncio.Semaphore(max(1, config.browser.per_domain_concurrency))
    )
    async with async_playwright() as playwright:
        kwargs: dict[str, Any] = {
            "user_data_dir": str(profile),
            "headless": not headed,
            "locale": "en-US",
            "timezone_id": config.timezone,
            "viewport": {"width": 1440, "height": 1000},
        }
        if channel:
            kwargs["channel"] = channel
        context = await playwright.chromium.launch_persistent_context(**kwargs)

        async def bounded(source: SourceConfig) -> SourceResult:
            """处理：先等待同域空位，再开页占用全局浏览器名额。
            输入：单个来源页面及外层共享会话。
            输出：页面结果；取消或失败时由上下文管理器释放名额。
            """
            async with domain_limits[urlsplit(source.url).netloc.lower()], global_limit:
                return await collect_browser_page(context, source, config)

        try:
            results = await asyncio.gather(*(bounded(source) for source in sources))
        finally:
            await context.close()
    return {
        (source.id, source.url): result for source, result in zip(sources, results, strict=True)
    }
