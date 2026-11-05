from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

_VISIBLE_DOM = """document.querySelectorAll('body *').forEach(node => {
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') node.remove();
});"""


async def crawl_pages(
    urls: list[str], *, timeout_ms: int, concurrency: int,
    per_domain_concurrency: int, headless: bool = True,
) -> list[dict[str, Any]]:
    """处理：复用一个匿名浏览器，加载动态正文与懒加载媒体。
    输入：已选文章地址、导航时限及全局和同域并发数。
    输出：按输入顺序返回页面 HTML、媒体和访问结果；不落盘原始页面。
    """
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError as exc:
        raise RuntimeError(
            'Crawl4AI is not installed; run python -m pip install -e ".[crawl4ai]" '
            "and crawl4ai-setup"
        ) from exc

    global_limit = asyncio.Semaphore(concurrency)
    domain_limits: dict[str, asyncio.Semaphore] = {}
    browser = BrowserConfig(headless=headless, verbose=False)
    run = CrawlerRunConfig(
        cache_mode=CacheMode.DISABLED, page_timeout=timeout_ms,
        wait_until="domcontentloaded", delay_before_return_html=1.0,
        scan_full_page=True, max_scroll_steps=8, js_code=_VISIBLE_DOM,
        verbose=False,
    )
    async with AsyncWebCrawler(config=browser) as crawler:

        async def fetch(url: str) -> dict[str, Any]:
            """处理：在两级并发限制内取得单页，并保留逐页失败原因。
            输入：已授权进入正文提取的文章地址。
            输出：页面 HTML 与 SDK 的状态、媒体字段，供共享提取器处理。
            """
            domain = urlsplit(url).netloc.lower()
            limit = domain_limits.setdefault(domain, asyncio.Semaphore(per_domain_concurrency))
            # 同域排队先于全局占位，避免一个慢域堵住其他域的可用并发。
            async with limit, global_limit:
                try:
                    result = await asyncio.wait_for(
                        crawler.arun(url=url, config=run), timeout=timeout_ms / 1000 + 5,
                    )
                    return {
                        "html": result.html, "url": result.redirected_url or url,
                        "status_code": result.status_code, "success": result.success,
                        "error": result.error_message, "media": result.media,
                    }
                except Exception as exc:
                    return {
                        "html": "", "url": url, "status_code": None,
                        "success": False, "error": f"{type(exc).__name__}: {exc}", "media": {},
                    }

        return list(await asyncio.gather(*(fetch(url) for url in urls)))
