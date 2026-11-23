from __future__ import annotations

import asyncio
import contextlib
import re
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import BrowserContext, Page

from .access import CHALLENGE_TEXTS, classify_access_text, classify_source_status
from .adapters import collect_candidates, is_eligible
from .article_time import (
    _declared_datetime,
    abc_live_entry_id,
    in_window,
    normalize_time,
    observe_items,
    original_publication_time,
    published_on_date,
    uses_platform_publication_time,
)
from .brief_selection import select_brief_items
from .browser_collection import collect_browser_pages
from .config import (
    AppConfig,
    SourceConfig,
    resolve_browser_channel,
    resolve_profile_dir,
    source_urls,
)
from .content import (
    _HTTP_ACCEPT,
    PublicationPage,
    prepare_publication_content,
    probe_google_news_dates,
    probe_publication_time,
)
from .content_extraction import is_navigation_only
from .models import SourceResult, SourceStatus, effective_page_results, order_source_items
from .monitor import load_monitor_results
from .prefetch import _USER_AGENT, page_needs_browser, prefetch_browser_pages
from .storage import next_revision, write_immutable_json
from .utils import canonicalize_url, now_iso, read_json, timestamp_slug, today_str, write_json

__all__ = ["CHALLENGE_TEXTS", "is_eligible"]


def _paper_publisher_url(url: str) -> str:
    """处理：将 HF 论文镜像指向相同编号的 arXiv 原文。
    输入：规范候选地址；输出：同一篇论文的原发地址或原候选地址。
    """
    parts = urlsplit(url)
    if parts.hostname == "huggingface.co":
        paper = re.fullmatch(r"/papers/(\d{4}\.\d{4,6})/?", parts.path)
        if paper:
            return f"https://arxiv.org/abs/{paper[1]}"
    return url


def _within_window(item: Any, start: datetime, end: datetime) -> bool:
    """处理：用来源实际发布日期判断本期窗口，不以采集时间代替。
    输入：文章与冻结的日报起止时间。
    输出：仅有效且明确位于窗口内的日期返回真。
    """
    return in_window(item.published_at, start, end)


def _current_monitor_items(
    items: list[Any], source: SourceConfig | None = None,
    window: tuple[datetime, datetime] | None = None,
) -> list[Any]:
    """处理：排除陈旧、历史保留缓存，并按冻结窗口计算可替代实时抓取的候选。
    输入：监控文章、来源排序语义与可选日报窗口。
    输出：当前有效候选；发现榜单保留排名含义，未知日期不伪装为新鲜。
    """
    return [
        item for item in items
        if not item.metadata.get("retained_from_previous_snapshot")
        and not item.metadata.get("feed_stale")
        and (window is None or (source is not None and source.role == "discovery")
             or not item.published_at or _within_window(item, *window))
    ]


def _monitor_sufficient(
    result: SourceResult | None, source: SourceConfig,
    window: tuple[datetime, datetime] | None, date_value: str | None,
) -> bool:
    """处理：按简报的原文日期门槛统计可用的监控候选。
    输入：监控结果、来源配置、冻结窗口及本版上海自然日。
    输出：候选达到来源门槛时复用快照，否则采集实时页面。
    """
    if result is None or result.status not in {SourceStatus.SUCCESS, SourceStatus.PARTIAL}:
        return False
    if source.collect_all_items or source.id == "huggingface_papers":
        return False
    items = _current_monitor_items(result.items, source, window)
    if date_value:
        cutoff = window[1].isoformat() if window else None
        count = sum(published_on_date(item.to_dict(), date_value, cutoff) for item in items)
    else:
        count = len(items)
    return count >= max(1, min(source.report_target, source.max_items))


def _merge_monitor_evidence(item: Any, cached: Any, data_dir: Path) -> Any:
    """处理：用同源同文章的当前 Feed 补充实时条目。
    输入：实时条目、监控条目和内容文件所在数据根。
    输出：保留实时排名与访问状态，并用同篇 Feed 的精确时间补足兼容的列表日期。
    """
    if (item.source_id, item.item_id, item.canonical_url) != (
        cached.source_id, cached.item_id, cached.canonical_url
    ):
        return item
    metadata = dict(item.metadata)
    description = item.description
    published_at = item.published_at
    live_item = item.to_dict()
    cached_original = original_publication_time(cached.to_dict())
    live_original = original_publication_time(live_item)
    # 列表可能记录发布地的日历日，带偏移的原始 Feed 时间才可提升到时刻精度。
    raw_feed_time = None
    if (
        live_original and len(live_original) == 10
        and cached.metadata.get("acquisition_method") == "feed"
        and not cached.metadata.get("feed_stale")
        and not uses_platform_publication_time(live_item)
        and urlsplit(str(cached.metadata.get("feed_url") or "")).hostname
        == urlsplit(item.url).hostname
    ):
        raw_feed_time = _declared_datetime(str(cached.metadata.get("published_raw") or ""))
    finer_feed_time = (
        cached_original and len(cached_original) > 10
        and raw_feed_time is not None and raw_feed_time.utcoffset() is not None
        and datetime.fromisoformat(cached_original) == raw_feed_time.replace(microsecond=0)
        and live_original in {raw_feed_time.date().isoformat(), cached_original[:10]}
    )
    if cached_original and (not live_original or finer_feed_time):
        relative = metadata.get("publication_time_basis") == "relative"
        published_at = cached_original if relative or finer_feed_time else (
            published_at or cached_original
        )
        for key in ("published_raw", "published_precision", "feed_url"):
            if cached.metadata.get(key) and not (relative and key == "published_raw"):
                metadata[key] = cached.metadata[key]
        if cached.metadata.get("content_source", {}).get("published_at"):
            metadata["content_source"] = {
                **metadata.get("content_source", {}),
                "published_at": cached.metadata["content_source"]["published_at"],
            }
        metadata["publication_time_missing"] = False
        if relative:
            metadata["publication_time_basis"] = "publisher"
    if not description and cached.description and not is_navigation_only(cached.description):
        description = cached.description
    path = cached.metadata.get("feed_content_path")
    if path and not metadata.get("feed_content_path"):
        try:
            feed_path = Path(path).resolve()
            feed_path.relative_to(data_dir.resolve())
            record = read_json(feed_path)
            if (record.get("source_id") == item.source_id
                    and record.get("item_id") == item.item_id
                    and canonicalize_url(record.get("url", "")) == item.canonical_url
                    and record.get("text") and not is_navigation_only(record["text"])):
                for key in ("feed_content_path", "feed_content_sha256", "feed_content_characters"):
                    if key in cached.metadata:
                        metadata[key] = cached.metadata[key]
        except (OSError, ValueError, TypeError, KeyError):
            pass
    # 联合国列表中的简报链接可能只写日期，附时间的官方稿件订阅同时提供正式标题。
    if (item.source_id == "un_press" and cached_original
            and cached.metadata.get("feed_url") == "https://press.un.org/en/rss.xml"):
        return replace(item, title=cached.title, published_at=cached_original,
                       description=description, metadata=metadata)
    return replace(item, published_at=published_at, description=description, metadata=metadata)


def detect_challenge(page: Page, http_status: int | None) -> dict[str, Any]:
    """处理：从页面标题、正文和 iframe 迹象识别登录、验证码或限流挑战。
    输入：已加载的 Playwright 页面、页面最近一次 HTTP 状态码。
    输出：“从页面标题、正文和 iframe 迹象识别登录、验证码或限流挑战”形成的结构化字典；
      键值表达该处理定义的业务记录或查找关系。
    """
    title = ""
    body = ""
    with contextlib.suppress(Exception):
        title = page.title().lower()
    with contextlib.suppress(Exception):
        body = page.locator("body").inner_text(timeout=3000).lower()[:30000]
    iframe_count = 0
    with contextlib.suppress(Exception):
        iframe_count = page.locator(
            'iframe[src*="captcha"], iframe[src*="challenge"], iframe[title*="challenge" i]'
        ).count()
    return classify_access_text(
        http_status,
        title,
        body,
        iframe_detected=iframe_count > 0,
    )


def collect_one(
    context: BrowserContext,
    source: SourceConfig,
    config: AppConfig,
    data_dir: Path,
) -> SourceResult:
    """处理：打开单个来源页面，等待加载后返回带状态和条目的采集结果。
    输入：带入口与筛选规则的来源配置、已校验的采集和输出配置、本次运行的数据根。
    - ``context``：浏览器、写作或报告上下文对象；包含当前阶段已经绑定的受控状态。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    collected_at = now_iso(config.timezone)
    page = context.new_page()
    response = None
    try:
        response = page.goto(
            source.url,
            wait_until="domcontentloaded",
            timeout=config.browser.navigation_timeout_ms,
        )
        page.wait_for_timeout(source.wait_ms or config.browser.default_wait_ms)
        http_status = response.status if response else None
        return collect_loaded_page(page, source, config, http_status, collected_at)
    except Exception as exc:
        return SourceResult(
            source_id=source.id,
            source_name=source.name,
            source_url=source.url,
            status=SourceStatus.FAILED,
            collected_at=collected_at,
            module=source.module,
            category=source.category,
            page_title=_safe_title(page),
            final_url=page.url,
            http_status=response.status if response else None,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        page.close()


def collect_loaded_page(
    page: Page,
    source: SourceConfig,
    config: AppConfig,
    http_status: int | None = None,
    collected_at: str | None = None,
) -> SourceResult:
    """处理：检测已加载页面的访问挑战，并在可访问时提取候选文章。
    输入：已加载的 Playwright 页面、
      带入口与筛选规则的来源配置、已校验的采集和输出配置、页面最近一次 HTTP 状态码。
    - ``collected_at``：页面或 Feed 的采集时间；用于状态记录和时间回退，不冒充发布时间。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    collected_at = collected_at or now_iso(config.timezone)
    challenge = detect_challenge(page, http_status)
    page_title = _safe_title(page)
    # 挑战页上的文本和链接不是新闻条目；确认可访问前不得进入候选解析。
    items = [] if challenge["required"] else collect_candidates(page, source, collected_at)
    status = classify_source_status(
        http_status,
        challenge["required"],
        bool(items),
        bool(challenge.get("rate_limited")),
    )
    error = f"HTTP {http_status}" if http_status is not None and http_status >= 400 else None
    return SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        status=status,
        collected_at=collected_at,
        module=source.module,
        category=source.category,
        page_title=page_title,
        final_url=page.url,
        http_status=http_status,
        error=error,
        challenge=challenge,
        items=items,
    )


def collect_source(
    context: BrowserContext | None,
    source: SourceConfig,
    config: AppConfig,
    data_dir: Path,
    prefetched_pages: dict[tuple[str, str], SourceResult] | None = None,
    monitor_result: SourceResult | None = None,
    browser_results: dict[tuple[str, str], SourceResult] | None = None,
    *, window: tuple[datetime, datetime] | None = None, date_value: str | None = None,
) -> SourceResult:
    """处理：采集单个来源的主页和扩展页，并合并预取、监控或浏览器结果。
    输入：带入口与筛选规则的来源配置、已校验的采集和输出配置、本次运行的数据根。
    - ``context``：浏览器、写作或报告上下文对象；包含当前阶段已经绑定的受控状态。
    - ``prefetched_pages``：HTTP 预取阶段按来源与 URL 保存的页面结果；可避免再次导航。
    - ``monitor_result``：零模型监控器为同一来源生成的结果；采集阶段可复用其条目和状态。
    - ``window``：本期冻结窗口；用于缓存刷新判断和候选的新鲜度分区。
    - ``date_value``：本期上海自然日；用于缓存充足性判断。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    prefetch_supplied = prefetched_pages is not None
    prefetched_pages = prefetched_pages or {}
    monitor_sufficient = _monitor_sufficient(monitor_result, source, window, date_value)
    cache_result = replace(
        monitor_result, items=_current_monitor_items(monitor_result.items),
    ) if monitor_result is not None else None
    if monitor_result is not None:
        # 监控快照会为仪表盘保留历史项；日报只能复用本轮刷新仍实际可见的候选。
        monitor_result = replace(
            monitor_result,
            items=_current_monitor_items(monitor_result.items, source, window),
        )
    page_results: list[SourceResult] = [monitor_result] if monitor_result else []
    attempts: list[tuple[SourceResult, str]] = (
        [(monitor_result, "monitor_cache")] if monitor_result else []
    )
    urls = [] if monitor_sufficient else source_urls(source, data_dir)
    for url in urls:
        prefetched = prefetched_pages.get((source.id, url))
        if prefetched is not None:
            attempts.append((prefetched, "http"))
        if not page_needs_browser(prefetched):
            page_results.append(prefetched)
            continue
        if browser_results is not None and (source.id, url) in browser_results:
            browser = browser_results[(source.id, url)]
        else:
            if context is None and prefetch_supplied:
                raise RuntimeError(
                    f"Edge fallback required for source {source.id!r} page {url}, "
                    "but no browser context is available"
                )
            browser = collect_one(context, replace(source, url=url), config, data_dir)
        attempts.append((browser, "browser"))
        # 浏览器优先保留完整排序；HTTP 候选在后续轮询中补足遗漏。
        if browser.status == SourceStatus.SUCCESS or (
            browser.status == SourceStatus.NO_ITEMS and not (
                prefetched and (prefetched.items or prefetched.status in {
                    SourceStatus.VERIFICATION_REQUIRED, SourceStatus.RATE_LIMITED,
                })
            )
        ):
            page_results.append(replace(browser, items=browser.items + (
                prefetched.items if prefetched else []
            )))
        elif prefetched and prefetched.items:
            page_results.append(replace(
                browser, status=SourceStatus.PARTIAL, items=browser.items + prefetched.items,
            ))
        elif prefetched and prefetched.status in {
            SourceStatus.VERIFICATION_REQUIRED, SourceStatus.RATE_LIMITED,
        }:
            page_results.append(prefetched)
        else:
            page_results.append(browser)
    for result in [*page_results, *(attempt for attempt, _ in attempts)]:
        if result.status == SourceStatus.NO_ITEMS and (
            result.error or (result.http_status is not None and result.http_status >= 400)
        ):
            # 修复旧适配器可能产生的矛盾状态，访问失败不能伪装成正常无条目。
            result.status = SourceStatus.FAILED
    # 实时页面成功返回候选时，以实时页面为本轮排名权威；Monitor 仅在所有实时
    # 候选之后补充去重后的尾部项。否则旧快照会把刚升到 Top1 的实时条目压到后面。
    live_results = [
        result
        for result in page_results
        if result is not monitor_result and result.items
    ]
    ranked_results = live_results or page_results
    cache_fallback = cache_result if live_results and cache_result else None
    # 多个实时页面仍按页轮询，避免第一个宽泛页面在达到上限前挤掉后续专题页面。
    seen: set[str] = set()
    items = []
    position = 0
    collect_all_ranked_candidates = (source.collect_all_items
                                     or source.item_order == "published_at" or window is not None)
    while collect_all_ranked_candidates or len(items) < source.max_items:
        added = False
        for result in ranked_results:
            if position >= len(result.items):
                continue
            item = result.items[position]
            if item.canonical_url in seen:
                continue
            seen.add(item.canonical_url)
            items.append(item)
            added = True
            if not collect_all_ranked_candidates and len(items) >= source.max_items:
                break
        position += 1
        if not added and all(position >= len(result.items) for result in ranked_results):
            break
    if cache_fallback is not None:
        current_cache = {item.canonical_url: item for item in cache_fallback.items}
        items = [_merge_monitor_evidence(item, current_cache[item.canonical_url], data_dir)
                 if item.canonical_url in current_cache else item for item in items]
        for item in cache_fallback.items:
            if item.canonical_url in seen:
                continue
            seen.add(item.canonical_url)
            items.append(item)
            if not collect_all_ranked_candidates and len(items) >= source.max_items:
                break
    for source_rank, item in enumerate(items, start=1):
        if monitor_sufficient:
            item.metadata.setdefault("source_rank", source_rank)
        else:
            # 实时多页轮询建立统一名次；纯缓存复用保留 Feed 中的原始名次。
            item.metadata["source_rank"] = source_rank
    items = order_source_items(items, source.item_order)
    if window is not None and source.role != "discovery":
        items = [item for item in items if not item.published_at or in_window(
            item.published_at, datetime.min.replace(tzinfo=window[1].tzinfo), window[1],
        )]
        items.sort(key=lambda item: not _within_window(item, *window))
    if not source.collect_all_items:
        items = items[: source.max_items]
    statuses = {result.status for result in page_results}
    if items and statuses <= {SourceStatus.SUCCESS, SourceStatus.NO_ITEMS}:
        status = SourceStatus.SUCCESS
    elif items:
        status = SourceStatus.PARTIAL
    elif SourceStatus.RATE_LIMITED in statuses:
        status = SourceStatus.RATE_LIMITED
    elif SourceStatus.VERIFICATION_REQUIRED in statuses:
        status = SourceStatus.VERIFICATION_REQUIRED
    elif SourceStatus.FAILED in statuses:
        status = SourceStatus.FAILED
    else:
        status = SourceStatus.NO_ITEMS
    return SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=source.url,
        status=status,
        collected_at=now_iso(config.timezone),
        module=source.module,
        category=source.category,
        error="; ".join(result.error for result in page_results
                        if result.error and result.status != SourceStatus.SUCCESS) or None,
        page_results=[
            {
                "url": result.source_url,
                "final_url": result.final_url,
                "status": result.status,
                "http_status": result.http_status,
                "error": result.error,
                "challenge": result.challenge,
                "items_count": len(result.items),
                "acquisition_method": method,
            }
            for result, method in attempts
        ],
        items=items,
    )


async def _complete_publication_times(
    results: list[SourceResult], config: AppConfig, previous: dict[str, Any],
    *, date_value: str | None = None,
) -> dict[str, PublicationPage]:
    """处理：为缺少原文日期的候选复用已知日期或并发读取公开页面日期。
    输入：本轮采集结果、并发配置及前次索引，按文章规范地址合并同文请求。
    输出：补充日期和探测结果；为本版候选在内存中保留完整响应。
    """
    known_dates = {}
    for item in previous.get("items", []):
        content_source = (item.get("metadata") or {}).get("content_source") or {}
        if not content_source.get("published_at"):
            continue
        date = original_publication_time(item, config.timezone)
        if date and (item.get("source_id") not in {"arxiv_ai", "xinhua_en"} or len(date) > 10):
            known_dates[canonicalize_url(item.get("canonical_url") or item["url"])] = (
                date, content_source.get("url"),
            )
    source_configs = {source.id: source for source in config.report_sources}
    pending: dict[str, list[Any]] = defaultdict(list)
    for result in results:
        for item in result.items:
            relative = item.metadata.get("publication_time_basis") == "relative"
            # BBC 的 Feed 日期也可能是更新时刻，文章需以原文声明为准。
            bbc_article = (item.source_id == "bbc_world"
                           and urlsplit(item.url).path.startswith("/news/articles/"))
            page_date = (item.metadata.get("content_source") or {}).get("published_at")
            abc_entry = abc_live_entry_id(item.url)
            if abc_entry:
                source_metadata = item.metadata.get("content_source") or {}
                item.metadata.pop("published_raw", None)
                if source_metadata.get("publication_entry_id") != abc_entry:
                    # 旧版和 Feed 可能记录的是母页更新，不能作为独立条目时间。
                    source_metadata.pop("published_at", None)
                    item.published_at = None
                    item.metadata["publication_time_missing"] = True
            url = canonicalize_url(item.canonical_url or item.url)
            publisher_url = _paper_publisher_url(url)
            paper_mirror = url != publisher_url
            original = original_publication_time(item.to_dict())
            if result.source_id == "weibo_hot" or (
                original and not relative
                and (item.source_id != "arxiv_ai" or len(original) > 10)
                and (item.source_id != "xinhua_en" or original != date_value)
                and (not paper_mirror or (item.metadata.get("content_source") or {}).get(
                    "url") == publisher_url)
                and (not bbc_article or page_date)
            ):
                continue
            source = source_configs[result.source_id]
            article_link = source.article_patterns and is_eligible(source, item.title, item.url)
            if not (article_link or item.metadata.get("acquisition_method") == "feed"):
                continue
            if publisher_url in known_dates and not abc_entry:
                date, known_publisher_url = known_dates[publisher_url]
                content_source = item.metadata.setdefault("content_source", {})
                content_source["published_at"] = date
                if paper_mirror or known_publisher_url:
                    content_source["url"] = publisher_url if paper_mirror else known_publisher_url
                item.metadata["publication_time_basis"] = "publisher"
                item.metadata["publication_time_missing"] = False
                if not uses_platform_publication_time(item.to_dict()):
                    item.published_at = date
            else:
                key = urlsplit(url).path if bbc_article else publisher_url
                pending[key].append(item)
    if not pending:
        return {}
    pages: dict[str, PublicationPage] = {}

    def retain(url: str, probe: dict, page: PublicationPage) -> None:
        """处理：按上海自然日暂存可能入选的完整响应。
        输入：原始链接、日期回执及完整网页。
        输出：本版候选可继续使用的网页材料，历史文章仅保留日期。
        """
        raw_date = probe.get("published_at") or ""
        stamp = normalize_time(raw_date, config.timezone)
        if stamp and (stamp[:10] == date_value or raw_date[:10] == date_value):
            pages[url] = page

    global_limit = asyncio.Semaphore(config.browser.collection_global_concurrency)
    domain_limits = defaultdict(
        lambda: asyncio.Semaphore(config.browser.collection_per_domain_concurrency)
    )
    async with httpx.AsyncClient(
        timeout=config.browser.http_prefetch_timeout_ms / 1000,
        follow_redirects=True, headers={"User-Agent": _USER_AGENT, "Accept": _HTTP_ACCEPT},
    ) as client:

        async def read_date(article_url: str) -> dict:
            """处理：在全局和同域配额内读取一份日期证据。
            输入：同文去重后的来源原始 URL。
            输出：供同文全部候选复用的探测回执。
            """
            async with domain_limits[urlsplit(article_url).netloc], global_limit:
                if date_value:
                    return await probe_publication_time(client, article_url, retain=retain)
                return await probe_publication_time(client, article_url)

        groups: dict[str, list[Any]] = defaultdict(list)
        for items in pending.values():
            groups[_paper_publisher_url(items[0].url)].extend(items)
        probes = dict(zip(groups, await asyncio.gather(*(read_date(url) for url in groups)),
                          strict=True))
    google_wrappers = [
        url for url, items in groups.items()
        if any(item.source_id == "google_news_china" for item in items)
        and urlsplit(url).hostname == "news.google.com"
        and urlsplit(probes[url].get("final_url") or "").hostname == "news.google.com"
        and probes[url]["status"] == "success" and not probes[url].get("published_at")
    ]
    if google_wrappers:
        resolved = (await probe_google_news_dates(google_wrappers, config, retain=retain)
                    if date_value else await probe_google_news_dates(google_wrappers, config))
        probes.update({url: {**probe, "acquisition_method": "browser"}
                       for url, probe in resolved.items()})
    for url, items in groups.items():
        probe = probes[url]
        raw_date = probe.get("published_at")
        valid = probe["status"] == "success" and normalize_time(raw_date or "", config.timezone)
        final_url = probe.get("final_url")
        for item in items:
            item.metadata["publication_time_probe"] = probe
            if url in pages:
                # 同一规范文章的镜像共用一次公开响应。
                pages[item.url] = pages[url]
            if item.source_id == "bbc_world" and not valid:
                item.metadata["publication_time_missing"] = True
            if (item.source_id == "google_news_china" and final_url
                    and urlsplit(final_url).hostname != "news.google.com"):
                item.metadata.setdefault("content_source", {})["url"] = final_url
            abc_entry = abc_live_entry_id(item.url)
            if valid and (not abc_entry or probe.get("publication_entry_id") == abc_entry):
                content_source = item.metadata.setdefault("content_source", {})
                content_source["published_at"] = raw_date
                if abc_entry:
                    content_source["publication_entry_id"] = abc_entry
                if _paper_publisher_url(item.url) != item.url:
                    content_source["url"] = final_url
                item.metadata["publication_time_basis"] = "publisher"
                item.metadata["publication_time_missing"] = False
                if not uses_platform_publication_time(item.to_dict()):
                    item.published_at = original_publication_time(item.to_dict())
    return pages


def _safe_title(page: Page) -> str:
    """处理：读取页面标题；浏览器访问失败时返回空字符串。
    输入：已加载的 Playwright 页面。
    输出：“读取页面标题；浏览器访问失败时返回空字符串”得到的规范字符串，
      供调用方存储、比较或展示。
    """
    try:
        return page.title()
    except Exception:
        return ""


def collect_sources(
    config: AppConfig,
    data_dir: Path,
    edition: str,
    headed: bool,
    only_source_ids: set[str] | None = None,
    profile_dir: Path | None = None,
    browser_channel: str | None = None,
    revision: int | None = None,
    temporary: bool = False,
    *,
    date_value: str | None = None,
    collection_window: dict[str, str] | None = None,
    shared_listing_pages: dict[tuple[str, str], SourceResult] | None = None,
) -> Path:
    """处理：按并发预算采集选定来源，并为每个来源保留成功、空、失败或挑战状态。
    输入：已校验的采集和输出配置、本次运行的数据根、浏览器窗口显示选项、持久化浏览器配置目录、浏览器通道。
    - ``edition``：日报版本标识，daily 为默认值，morning/evening 兼容历史运行；参与窗口和产物命名。
    - ``only_source_ids``：调用方限定的来源 ID 集合；为空时处理配置选中的全部来源。
    - ``revision``：目标产物修订号；为空时由持久化层选择下一个不可变版本。
    - ``temporary``：是否生成重试或验证用的临时索引，而不是正式不可变索引。
    - ``date_value``：调用方冻结的日报日期；采集跨午夜时保持运行与索引日期一致。
    - ``collection_window``：本期冻结窗口；核心来源据此刷新缓存、优先新报道，发现池仅选窗内条目。
    - ``shared_listing_pages``：同轮监控用本配置取得的成功页面，按入口 URL 复用。
    输出：指向“按并发预算采集选定来源，
      并为每个来源保留成功、空、失败或挑战状态”所生成、定位或确认产物的本地路径。
    """
    date_value = date_value or today_str(config.timezone)
    selected = [
        replace(source, explore_urls=[
            f"https://huggingface.co/papers?date={date_value}", *source.explore_urls,
        ]) if source.id == "huggingface_papers" else source
        for source in config.report_sources
        if source.enabled and (not only_source_ids or source.id in only_source_ids)
    ]
    unknown_ids = (only_source_ids or set()) - {source.id for source in selected}
    if unknown_ids:
        raise ValueError(f"Unknown or disabled sources: {sorted(unknown_ids)}")

    profile = resolve_profile_dir(config, profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    channel = resolve_browser_channel(config, browser_channel)
    monitor_results = load_monitor_results(
        data_dir,
        selected,
        config.timezone,
        config.monitor.snapshot_max_age_minutes,
    )
    frozen = collection_window or {}
    end = datetime.fromisoformat(frozen.get("end") or now_iso(config.timezone))
    start = datetime.fromisoformat(frozen["start"]) if frozen.get("start") else (
        end - timedelta(hours=24)
    )
    window = (start, end)
    html_sources = [
        source
        for source in selected
        if not _monitor_sufficient(monitor_results.get(source.id), source, window, date_value)
    ]
    prefetched_pages = (
        {} if headed else prefetch_browser_pages(
            html_sources, config, data_dir, shared_listing_pages=shared_listing_pages,
        )
    )
    browser_sources = [
        replace(source, url=url)
        for source in html_sources
        for url in source_urls(source, data_dir)
        if page_needs_browser(prefetched_pages.get((source.id, url)))
    ]
    browser_results = asyncio.run(collect_browser_pages(
        browser_sources, config, profile, channel, headed,
    )) if browser_sources else {}
    results = [
        collect_source(
            None, source, config, data_dir, prefetched_pages,
            monitor_results.get(source.id), browser_results, window=window, date_value=date_value,
        )
        for source in selected
    ]
    prior_path = data_dir / "indexes" / "latest.json"
    previous = read_json(prior_path) if prior_path.exists() else {}
    pages = asyncio.run(_complete_publication_times(
        results, config, previous, date_value=date_value,
    ))
    # 索引保留实际采集结果；本版合格数量只控制下游写作计划。
    source_configs = {source.id: source for source in selected}
    counts = {}
    for result in results:
        eligible = select_brief_items(
            [item.to_dict() for item in result.items], source_configs,
            date_value=date_value, cutoff=end.isoformat(),
        )
        counts[result.source_id] = len(eligible)
        by_id = {item.item_id: item for item in result.items}
        for item in eligible:
            if (page := pages.get(item["url"])) is not None:
                prepared = prepare_publication_content(
                    item, page, source_configs[result.source_id], config, data_dir,
                )
                if prepared:
                    by_id[item["item_id"]].metadata["publication_probe_content"] = prepared
    return write_results_index(
        results,
        data_dir,
        edition,
        config.timezone,
        profile,
        source_policies={
            source.id: {
                "report_target": counts[source.id],
                "report_max": counts[source.id],
                "configured_report_target": source.report_target,
                "configured_report_max": source.report_max,
                "role": source.role,
                "tier": source.tier,
                "bundle": source.bundle,
                "item_order": source.item_order,
                "language": source.language,
                "region": source.region,
                **source.origin_metadata,
                "module": source.module,
                "category": source.category,
                "selection_scope": "latest_15_today",
            }
            for source in selected
        },
        revision=revision,
        temporary=temporary,
        date_value=date_value,
        collection_window={"start": start.isoformat(), "end": end.isoformat()},
    )


def write_results_index(
    results: list[SourceResult],
    data_dir: Path,
    edition: str,
    timezone: str,
    profile: Path,
    source_policies: dict[str, dict[str, Any]] | None = None,
    revision: int | None = None,
    temporary: bool = False,
    *,
    date_value: str | None = None,
    collection_window: dict[str, str] | None = None,
) -> Path:
    """处理：把来源结果和根级条目写成新的不可变索引修订。
    输入：本次运行的数据根、用于解释本地日期的 IANA 时区。
    - ``results``：本轮各来源的采集结果；每项含状态、错误、页面证据和规范文章条目。
    - ``edition``：日报版本标识，daily 为默认值，morning/evening 兼容历史运行；参与窗口和产物命名。
    - ``profile``：已经解析并创建的浏览器 Profile 绝对路径。
    - ``source_policies``：按来源 ID 记录报告目标数和上限的策略映射。
    - ``revision``：目标产物修订号；为空时由持久化层选择下一个不可变版本。
    - ``temporary``：是否生成重试或验证用的临时索引，而不是正式不可变索引。
    - ``date_value``：调用方冻结的日报日期；采集跨午夜时保持运行与索引日期一致。
    - ``collection_window``：实际筛选使用的时间窗口，供后续写作和图文沿用。
    输出：指向“把来源结果和根级条目写成新的不可变索引修订”所生成、定位或确认产物的本地路径。
    """
    date = date_value or today_str(timezone)
    generated_at = now_iso(timezone)
    index_dir = data_dir / "indexes" / date

    if temporary:
        resolved_revision = 0
        output = (
            data_dir
            / "runs"
            / "retries"
            / date
            / f"{edition}-{timestamp_slug(timezone)}.json"
        )
    else:
        resolved_revision = revision or next_revision(index_dir, edition)
        output = index_dir / f"{edition}-r{resolved_revision}.json"

    prior_path = data_dir / "monitor" / "snapshot.json"
    if not prior_path.exists():
        prior_path = data_dir / "indexes" / "latest.json"
    previous = read_json(prior_path) if prior_path.exists() else {}
    for result in results:
        rows = [item.to_dict() for item in result.items]
        observe_items(previous, rows, result.collected_at or generated_at, preserve_signals=True)
        for item, row in zip(result.items, rows, strict=True):
            item.published_at = row["published_at"]
            item.metadata.update(row["metadata"])
            if not item.published_at or item.metadata.get("published_precision") == "date":
                item.metadata.setdefault("suggested_status", "WATCH")
    payload = {
        "schema_version": "1.1",
        "index_id": (
            f"retry-{date}-{edition}-{timestamp_slug(timezone)}"
            if temporary
            else f"index-{date}-{edition}-r{resolved_revision}"
        ),
        "date": date,
        "edition": edition,
        "revision": resolved_revision,
        "generated_at": generated_at,
        "timezone": timezone,
        "browser_profile": str(profile),
        "temporary": temporary,
        "source_policies": source_policies or {},
        "sources": [result.to_dict() for result in results],
        "items": [item.to_dict() for result in results for item in result.items],
    }
    if collection_window is not None:
        payload["collection_window"] = collection_window
    # 正式索引与临时重试索引都不可覆盖；合并操作必须生成新的正式修订。
    write_immutable_json(output, payload)
    if not temporary:
        write_json(data_dir / "indexes" / "latest.json", payload)
    return output


def merge_resume_index(original_path: Path, retry_path: Path, data_dir: Path) -> Path:
    """处理：用重试来源替换原索引中的对应来源并生成新修订。
    输入：本次运行的数据根。
    - ``original_path``：原始不可变来源索引路径；合并时保留其未重试来源和历史证据。
    - ``retry_path``：仅包含失败来源重试结果的索引路径；成功结果覆盖同来源旧状态。
    输出：指向“用重试来源替换原索引中的对应来源并生成新修订”所生成、定位或确认产物的本地路径。
    """
    original = read_json(original_path)
    retry = read_json(retry_path)
    if not isinstance(original, dict) or not isinstance(retry, dict):
        raise ValueError("Both original and retry indexes must be JSON objects")
    retry_sources = {
        str(row["source_id"]): row
        for row in retry.get("sources", [])
        if isinstance(row, dict) and row.get("source_id")
    }
    merged_sources: list[dict[str, Any]] = []
    emitted_sources: set[str] = set()
    for row in original.get("sources", []):
        source_id = str(row.get("source_id") or "")
        replacement = retry_sources.get(source_id)
        merged_sources.append(replacement if replacement is not None else row)
        if replacement is not None:
            emitted_sources.add(source_id)
    for source_id, row in retry_sources.items():
        if source_id not in emitted_sources:
            merged_sources.append(row)

    retry_items: dict[str, list[dict[str, Any]]] = {}
    for item in retry.get("items", []):
        if isinstance(item, dict) and item.get("source_id"):
            retry_items.setdefault(str(item["source_id"]), []).append(item)
    merged_items: list[dict[str, Any]] = []
    emitted_item_sources: set[str] = set()
    for item in original.get("items", []):
        source_id = str(item.get("source_id") or "")
        replacement = retry_items.get(source_id)
        if source_id not in retry_sources:
            merged_items.append(item)
        elif source_id not in emitted_item_sources:
            merged_items.extend(replacement or [])
            emitted_item_sources.add(source_id)
    for source_id in retry_sources:
        if source_id not in emitted_item_sources:
            merged_items.extend(retry_items.get(source_id, []))

    date = str(original.get("date"))
    edition = str(original.get("edition"))
    index_dir = data_dir / "indexes" / date
    revision = next_revision(index_dir, edition)
    merged = dict(original)
    merged.update(
        {
            "schema_version": "1.1",
            "index_id": f"index-{date}-{edition}-r{revision}",
            "revision": revision,
            "generated_at": retry.get("generated_at"),
            "resumed_from": str(original_path.resolve()),
            "retry_artifact": str(retry_path.resolve()),
            "sources": merged_sources,
            "items": merged_items,
        }
    )
    output = index_dir / f"{edition}-r{revision}.json"
    write_immutable_json(output, merged)
    write_json(data_dir / "indexes" / "latest.json", merged)
    return output


def merge_verified_results(
    original_path: Path,
    captured: list[SourceResult],
    data_dir: Path,
) -> Path:
    """处理：把人工验证后采集的页面结果合并回原索引并生成新修订。
    输入：本次运行的数据根。
    - ``original_path``：原始不可变来源索引路径；合并时保留其未重试来源和历史证据。
    - ``captured``：人工验证后重新采集成功的来源结果；用于替换待验证状态。
    输出：指向“把人工验证后采集的页面结果合并回原索引并生成新修订”所生成、定位或确认产物的本地路
      径。
    """
    original = read_json(original_path)
    if not isinstance(original, dict):
        raise ValueError("Original index must be a JSON object")
    captured_by_source: dict[str, list[SourceResult]] = {}
    for result in captured:
        captured_by_source.setdefault(result.source_id, []).append(result)
    policies = (
        original.get("source_policies", {})
        if isinstance(original.get("source_policies"), dict)
        else {}
    )
    root_items_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in original.get("items", []):
        if isinstance(item, dict) and item.get("source_id"):
            root_items_by_source.setdefault(str(item["source_id"]), []).append(item)

    def merged_source_items(
        source_id: str,
        existing: list[dict[str, Any]],
        results: list[SourceResult],
    ) -> list[dict[str, Any]]:
        """处理：把验证页候选置于当前来源序列并按来源策略重建规范顺序。
        输入：
        - ``source_id``：正在修订的来源身份；用于读取原索引的 item_order 策略。
        - ``existing``：原根级规范条目；其 metadata.source_rank 保留旧来源顺序。
        - ``results``：本轮人工验证成功读取的一个或多个页面结果。
        输出：去重、重编号后按 source 或 published_at 排列的来源条目；根级与 legacy
          嵌套视图复用同一列表，避免验证新增 Top 条目被简单追加到末尾。
        """
        captured_rows: list[dict[str, Any]] = []
        position = 0
        while any(position < len(result.items) for result in results):
            for result in results:
                if position < len(result.items):
                    captured_rows.append(result.items[position].to_dict())
            position += 1
        source_order_existing = order_source_items(list(existing), "source")
        combined: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        for row in [*captured_rows, *source_order_existing]:
            item_id = str(row.get("item_id") or "")
            canonical_url = str(row.get("canonical_url") or row.get("url") or "")
            if not item_id or item_id in seen_ids or (
                canonical_url and canonical_url in seen_urls
            ):
                continue
            payload = dict(row)
            metadata = dict(payload.get("metadata") or {})
            metadata.pop("retained_from_previous_snapshot", None)
            payload["metadata"] = metadata
            combined.append(payload)
            seen_ids.add(item_id)
            if canonical_url:
                seen_urls.add(canonical_url)
        for rank, row in enumerate(combined, start=1):
            row["metadata"]["source_rank"] = rank
        policy = policies.get(source_id, {})
        item_order = (
            str(policy.get("item_order") or "source")
            if isinstance(policy, dict)
            else "source"
        )
        return order_source_items(combined, item_order)

    merged_sources: list[dict[str, Any]] = []
    merged_items_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in original.get("sources", []):
        source_id = str(row.get("source_id") or "")
        source_results = captured_by_source.get(source_id, [])
        if not source_results:
            merged_sources.append(row)
            continue
        updated = dict(row)
        page_results = list(updated.get("page_results", []))
        for result in source_results:
            page_results = [page for page in page_results if page.get("url") != result.source_url]
            page_results.append(
                {
                    "url": result.source_url,
                    "final_url": result.final_url,
                    "status": result.status,
                    "http_status": result.http_status,
                    "error": result.error,
                    "challenge": result.challenge,
                    "items_count": len(result.items),
                }
            )
        existing_items = root_items_by_source.get(source_id) or [
            item for item in updated.get("items", []) if isinstance(item, dict)
        ]
        ordered_items = merged_source_items(source_id, existing_items, source_results)
        nested_items = {
            str(item["item_id"]): item for item in ordered_items if item.get("item_id")
        }
        merged_items_by_source[source_id] = ordered_items
        updated["page_results"] = page_results
        updated["items"] = ordered_items
        updated["items_count"] = len(nested_items)
        for page in page_results:
            if page.get("status") == "no_items" and (
                page.get("error")
                or (
                    isinstance(page.get("http_status"), int)
                    and int(page["http_status"]) >= 400
                )
            ):
                page["status"] = "failed"
        effective_pages = effective_page_results(page_results)
        updated["error"] = (
            "; ".join(str(page["error"]) for page in effective_pages if page.get("error"))
            or None
        )
        statuses = {str(page.get("status")) for page in effective_pages}
        if nested_items and statuses <= {"success", "no_items"}:
            updated["status"] = SourceStatus.SUCCESS
        elif nested_items:
            updated["status"] = SourceStatus.PARTIAL
        elif "rate_limited" in statuses:
            updated["status"] = SourceStatus.RATE_LIMITED
        elif "verification_required" in statuses:
            updated["status"] = SourceStatus.VERIFICATION_REQUIRED
        elif "failed" in statuses:
            updated["status"] = SourceStatus.FAILED
        else:
            updated["status"] = SourceStatus.NO_ITEMS
        merged_sources.append(updated)

    root_items: list[dict[str, Any]] = []
    emitted_sources: set[str] = set()
    for item in original.get("items", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "")
        replacement = merged_items_by_source.get(source_id)
        if replacement is None:
            root_items.append(item)
        elif source_id not in emitted_sources:
            root_items.extend(replacement)
            emitted_sources.add(source_id)
    for source_id, replacement in merged_items_by_source.items():
        if source_id not in emitted_sources:
            root_items.extend(replacement)

    date = str(original["date"])
    edition = str(original["edition"])
    revision = next_revision(data_dir / "indexes" / date, edition)
    merged = dict(original)
    merged.update(
        {
            "index_id": f"index-{date}-{edition}-r{revision}",
            "revision": revision,
            "generated_at": now_iso(str(original.get("timezone", "Asia/Shanghai"))),
            "verified_from": str(original_path.resolve()),
            "sources": merged_sources,
            "items": root_items,
        }
    )
    output = data_dir / "indexes" / date / f"{edition}-r{revision}.json"
    write_immutable_json(output, merged)
    write_json(data_dir / "indexes" / "latest.json", merged)
    return output
