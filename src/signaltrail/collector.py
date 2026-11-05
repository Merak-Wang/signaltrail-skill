from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page

from .access import CHALLENGE_TEXTS, classify_access_text
from .adapters import collect_candidates, is_eligible
from .article_time import in_window, observe_items
from .brief_selection import select_brief_items
from .browser_collection import collect_browser_pages
from .config import (
    AppConfig,
    SourceConfig,
    resolve_browser_channel,
    resolve_profile_dir,
    source_urls,
)
from .content_extraction import is_navigation_only
from .discovery_selection import select_discovery_items
from .models import SourceResult, SourceStatus, order_source_items
from .monitor import load_monitor_results
from .prefetch import page_needs_browser, prefetch_browser_pages
from .storage import next_revision, write_immutable_json
from .utils import canonicalize_url, now_iso, read_json, timestamp_slug, today_str, write_json

__all__ = ["CHALLENGE_TEXTS", "is_eligible"]


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


def _merge_monitor_evidence(item: Any, cached: Any, data_dir: Path) -> Any:
    """处理：用同源同文章的当前 Feed 补充实时条目。
    输入：实时条目、监控条目和内容文件所在数据根。
    输出：保留实时排名、日期和访问状态的条目副本。
    """
    if (item.source_id, item.item_id, item.canonical_url) != (
        cached.source_id, cached.item_id, cached.canonical_url
    ):
        return item
    metadata = dict(item.metadata)
    description = item.description
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
    return replace(item, description=description, metadata=metadata)


def detect_challenge(page: Page, http_status: int | None) -> dict[str, Any]:
    """处理：从页面标题、正文和 iframe 迹象识别登录、验证码或限流挑战。
    输入：
    - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
    - ``http_status``：页面最近一次 HTTP 状态码；无网络响应时可为空。
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


def classify_source_status(
    http_status: int | None,
    challenge_required: bool,
    has_items: bool,
    rate_limited: bool = False,
) -> SourceStatus:
    """处理：结合条目数量、访问挑战、限流和错误信息确定显式来源状态。
    输入：
    - ``http_status``：页面最近一次 HTTP 状态码；无网络响应时可为空。
    - ``challenge_required``：是否检测到登录、验证码或其他人工验证挑战。
    - ``has_items``：本次来源采集是否产生至少一个规范条目。
    - ``rate_limited``：是否检测到服务端限流；为真时不得改写为正常无条目。
    输出：封装“结合条目数量、访问挑战、限流和错误信息确定显式来源状态”业务结果的 ``SourceStatus`
      ` 对象；调用方据此继续相邻阶段或识别无结果状态。
    """
    if rate_limited:
        return SourceStatus.RATE_LIMITED
    if challenge_required:
        return SourceStatus.VERIFICATION_REQUIRED
    if http_status is not None and http_status >= 400:
        return SourceStatus.FAILED
    return SourceStatus.SUCCESS if has_items else SourceStatus.NO_ITEMS


def collect_one(
    context: BrowserContext,
    source: SourceConfig,
    config: AppConfig,
    data_dir: Path,
) -> SourceResult:
    """处理：打开单个来源页面，等待加载后返回带状态和条目的采集结果。
    输入：
    - ``context``：浏览器、写作或报告上下文对象；包含当前阶段已经绑定的受控状态。
    - ``source``：来源配置；包含来源 ID、名称、入口 URL、分类、过滤规则、限额和可信层级。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
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
    输入：
    - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
    - ``source``：来源配置；包含来源 ID、名称、入口 URL、分类、过滤规则、限额和可信层级。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``http_status``：页面最近一次 HTTP 状态码；无网络响应时可为空。
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
    *, window: tuple[datetime, datetime] | None = None,
) -> SourceResult:
    """处理：采集单个来源的主页和扩展页，并合并预取、监控或浏览器结果。
    输入：
    - ``context``：浏览器、写作或报告上下文对象；包含当前阶段已经绑定的受控状态。
    - ``source``：来源配置；包含来源 ID、名称、入口 URL、分类、过滤规则、限额和可信层级。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``prefetched_pages``：HTTP 预取阶段按来源与 URL 保存的页面结果；可避免再次导航。
    - ``monitor_result``：零模型监控器为同一来源生成的结果；采集阶段可复用其条目和状态。
    - ``window``：本期冻结窗口；用于缓存刷新判断和候选的新鲜度分区。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    prefetch_supplied = prefetched_pages is not None
    prefetched_pages = prefetched_pages or {}
    cache_result = replace(
        monitor_result, items=_current_monitor_items(monitor_result.items),
    ) if monitor_result is not None else None
    if monitor_result is not None:
        # 监控快照会为仪表盘保留历史项；日报只能复用本轮刷新仍实际可见的候选。
        monitor_result = replace(
            monitor_result,
            items=_current_monitor_items(monitor_result.items, source, window),
        )
    target = max(1, min(source.report_target, source.max_items))
    monitor_sufficient = bool(
        monitor_result and monitor_result.status in {SourceStatus.SUCCESS, SourceStatus.PARTIAL}
        and len(monitor_result.items) >= target
    )
    page_results: list[SourceResult] = [monitor_result] if monitor_result else []
    urls = [] if monitor_sufficient else source_urls(source, data_dir)
    for url in urls:
        if browser_results is not None and (source.id, url) in browser_results:
            page_results.append(browser_results[(source.id, url)])
            continue
        prefetched = prefetched_pages.get((source.id, url))
        if not page_needs_browser(prefetched):
            page_results.append(prefetched)
            continue
        if context is None and prefetch_supplied:
            raise RuntimeError(
                f"Edge fallback required for source {source.id!r} page {url}, "
                "but no browser context is available"
            )
        page_results.append(
            collect_one(context, replace(source, url=url), config, data_dir)
        )
    for result in page_results:
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
    collect_all_ranked_candidates = source.item_order == "published_at" or window is not None
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
        error="; ".join(result.error for result in page_results if result.error) or None,
        page_results=[
            {
                "url": result.source_url,
                "final_url": result.final_url,
                "status": result.status,
                "http_status": result.http_status,
                "error": result.error,
                "challenge": result.challenge,
                "items_count": len(result.items),
                "acquisition_method": (
                    "monitor_cache"
                    if result.challenge.get("monitor_cache")
                    else "browser_or_http"
                ),
            }
            for result in page_results
        ],
        items=items,
    )


def _safe_title(page: Page) -> str:
    """处理：读取页面标题；浏览器访问失败时返回空字符串。
    输入：
    - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
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
) -> Path:
    """处理：按并发预算采集选定来源，并为每个来源保留成功、空、失败或挑战状态。
    输入：
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``edition``：日报版本标识，daily 为默认值，morning/evening 兼容历史运行；参与窗口和产物命名。
    - ``headed``：是否显示真实浏览器窗口；人工登录或验证场景需要开启。
    - ``only_source_ids``：调用方限定的来源 ID 集合；为空时处理配置选中的全部来源。
    - ``profile_dir``：持久化浏览器 Profile 目录；保存用户已授权的浏览器会话。
    - ``browser_channel``：Playwright 浏览器通道名称；为空时使用配置或默认 Chromium。
    - ``revision``：目标产物修订号；为空时由持久化层选择下一个不可变版本。
    - ``temporary``：是否生成重试或验证用的临时索引，而不是正式不可变索引。
    - ``date_value``：调用方冻结的日报日期；采集跨午夜时保持运行与索引日期一致。
    - ``collection_window``：本期冻结窗口；核心来源据此刷新缓存、优先新报道，发现池仅选窗内条目。
    输出：指向“按并发预算采集选定来源，
      并为每个来源保留成功、空、失败或挑战状态”所生成、定位或确认产物的本地路径。
    """
    date_value = date_value or today_str(config.timezone)
    selected = [
        source
        for source in config.sources
        if source.enabled and (not only_source_ids or source.id in only_source_ids)
    ]
    unknown_ids = (only_source_ids or set()) - {source.id for source in selected}
    if unknown_ids:
        raise ValueError(f"Unknown or disabled sources: {sorted(unknown_ids)}")

    profile = resolve_profile_dir(config, profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    channel = resolve_browser_channel(config, browser_channel)
    discovery_sources = [
        source for source in config.monitor_sources if source.enabled
    ] if not only_source_ids and config.collection.discovery_brief_limit else []
    monitor_results = load_monitor_results(
        data_dir,
        [*selected, *discovery_sources],
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
        if (
            len(_current_monitor_items(monitor_results[source.id].items, source, window))
            if source.id in monitor_results
            and monitor_results[source.id].status in {SourceStatus.SUCCESS, SourceStatus.PARTIAL}
            else 0
        )
        < max(1, min(source.report_target, source.max_items))
    ]
    prefetched_pages = (
        {} if headed else prefetch_browser_pages(html_sources, config, data_dir)
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
            monitor_results.get(source.id), browser_results, window=window,
        )
        for source in selected
    ]
    core_items = [item for result in results for item in result.items]
    core_brief_ids = {item["item_id"] for item in select_brief_items(
        [item.to_dict() for item in core_items], {source.id: source for source in selected},
    )}
    allocations = select_discovery_items(
        monitor_results, discovery_sources,
        [item for item in core_items if item.item_id in core_brief_ids],
        limit=config.collection.discovery_brief_limit, start=start, end=end,
    )
    allocated_sources = []
    for source in discovery_sources:
        items = allocations.get(source.id)
        if items:
            results.append(replace(monitor_results[source.id], items=items))
            allocated_sources.append(replace(
                source, report_target=len(items), report_max=len(items),
            ))

    return write_results_index(
        results,
        data_dir,
        edition,
        config.timezone,
        profile,
        source_policies={
            source.id: {
                "report_target": source.report_target,
                "report_max": source.report_max,
                "role": source.role,
                "tier": source.tier,
                "bundle": source.bundle,
                "item_order": source.item_order,
                "language": source.language,
                "region": source.region,
                **source.origin_metadata,
                "module": source.module,
                "category": source.category,
                **({"selection_scope": "discovery_shared"} if source.id in allocations else {}),
            }
            for source in [*selected, *allocated_sources]
        },
        revision=revision,
        temporary=temporary,
        date_value=date_value,
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
) -> Path:
    """处理：把来源结果和根级条目写成新的不可变索引修订。
    输入：
    - ``results``：本轮各来源的采集结果；每项含状态、错误、页面证据和规范文章条目。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``edition``：日报版本标识，daily 为默认值，morning/evening 兼容历史运行；参与窗口和产物命名。
    - ``timezone``：IANA 时区名称；用于解析无时区时间并生成日报时间边界。
    - ``profile``：已经解析并创建的浏览器 Profile 绝对路径。
    - ``source_policies``：按来源 ID 记录报告目标数和上限的策略映射。
    - ``revision``：目标产物修订号；为空时由持久化层选择下一个不可变版本。
    - ``temporary``：是否生成重试或验证用的临时索引，而不是正式不可变索引。
    - ``date_value``：调用方冻结的日报日期；采集跨午夜时保持运行与索引日期一致。
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
    # 正式索引与临时重试索引都不可覆盖；合并操作必须生成新的正式修订。
    write_immutable_json(output, payload)
    if not temporary:
        write_json(data_dir / "indexes" / "latest.json", payload)
    return output


def merge_resume_index(original_path: Path, retry_path: Path, data_dir: Path) -> Path:
    """处理：用重试来源替换原索引中的对应来源并生成新修订。
    输入：
    - ``original_path``：原始不可变来源索引路径；合并时保留其未重试来源和历史证据。
    - ``retry_path``：仅包含失败来源重试结果的索引路径；成功结果覆盖同来源旧状态。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
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
    输入：
    - ``original_path``：原始不可变来源索引路径；合并时保留其未重试来源和历史证据。
    - ``captured``：人工验证后重新采集成功的来源结果；用于替换待验证状态。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
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
        updated["error"] = (
            "; ".join(str(page["error"]) for page in page_results if page.get("error"))
            or None
        )
        statuses = {str(page.get("status")) for page in page_results}
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
