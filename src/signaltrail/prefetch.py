from __future__ import annotations

import asyncio
import json
import re
import ssl
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from .access import classify_access_text, read_bounded_response
from .adapters import browser_items_from_rows, weibo_items_from_payload
from .config import AppConfig, SourceConfig, source_urls
from .image_policy import is_placeholder_image_url, srcset_candidates
from .models import SourceResult, SourceStatus
from .utils import now_iso

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Edg/131.0 Safari/537.36"
)


def html_index_rows(html: str) -> tuple[str, list[dict[str, Any]]]:
    """提取索引页标题和文章候选，交给来源适配器按规则筛选。"""
    _soup, title, rows = _html_index_document(html)
    return title, rows


def _html_index_document(
    html: str,
) -> tuple[BeautifulSoup, str, list[dict[str, Any]]]:
    """处理：解析索引页一次并提取可见标题与文章链接。
    输入：不可信的来源 HTML 文本；仅静态解析，不执行脚本。
    输出：BeautifulSoup DOM、页面标题和有序文章链接行，供索引和挑战检查复用。
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    rows: list[dict[str, Any]] = []
    for anchor in soup.select("a[href]"):
        heading = anchor.select_one("h1, h2, h3, h4")
        anchor_title = (
            heading.get_text(" ", strip=True)
            if heading
            else anchor.get("aria-label")
            or anchor.get("title")
            or anchor.get_text(" ", strip=True)
        )
        parent = anchor.find_parent(
            lambda tag: isinstance(tag, Tag)
            and (
                tag.name in {"article", "li"}
                or any(
                    marker in " ".join(tag.get("class", [])).lower()
                    for marker in ("card", "story")
                )
            )
        )
        time = parent.select_one("time") if isinstance(parent, Tag) else None
        images = list(anchor.select("picture source, img"))
        if isinstance(parent, Tag):
            images.extend(parent.select("picture source, img"))
        image_candidates: list[str] = []
        seen_images: set[str] = set()
        for image in images:
            raw_candidates = srcset_candidates(
                image.get("srcset") or image.get("data-srcset")
            ) + [
                str(image.get(attribute) or "")
                for attribute in (
                    "src",
                    "data-src",
                    "data-original",
                    "data-lazy-src",
                )
            ]
            for candidate in raw_candidates:
                candidate = candidate.strip()
                if (
                    not candidate
                    or candidate in seen_images
                    or is_placeholder_image_url(candidate)
                ):
                    continue
                seen_images.add(candidate)
                image_candidates.append(candidate)
        context = " ".join(
            part
            for part in (
                (
                    str(time.get("datetime") or time.get_text(" ", strip=True))
                    if time
                    else ""
                ),
                parent.get_text(" ", strip=True)[:500]
                if isinstance(parent, Tag)
                else "",
                anchor.get_text(" ", strip=True)[:500],
            )
            if part
        )
        cell = anchor.parent
        release_cell = cell.find_previous_sibling("td") if cell.name == "td" else None
        rows.append(
            {
                "title": str(anchor_title or ""),
                "href": str(anchor.get("href") or ""),
                "image_url": image_candidates[0] if image_candidates else "",
                "image_candidates": image_candidates,
                "context": context,
                "table_date": release_cell.get_text(" ", strip=True) if release_cell else "",
                "reuters_syndication": (
                    anchor.select("p")[-1].get_text(" ", strip=True)
                    if anchor.select_one('img[alt="Reuters"]') and anchor.select("p")
                    and any(p.get_text(" ", strip=True) == "Reuters" for p in anchor.select("p"))
                    else ""
                ),
            }
        )
    return soup, title, rows


def _yicai_publication_dates(
    soup: BeautifulSoup, rows: list[dict[str, Any]], base_url: str,
) -> None:
    """处理：按文章 URL 关联 firstlist 的 CreateDate。
    输入：解析后的页面、已有列表行和页面基准 URL。
    输出：原地为匹配的列表行添加原始发布时间。
    """
    dates = {}
    for script in soup.find_all("script"):
        match = re.search(r"\bvar\s+firstlist\s*=\s*", script.string or "")
        if not match:
            continue
        try:
            records, _ = json.JSONDecoder().raw_decode(script.string[match.end():])
        except (ValueError, TypeError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and record.get("url") and record.get("CreateDate"):
                dates[urljoin(base_url, str(record["url"]))] = str(record["CreateDate"])
    for row in rows:
        date = dates.get(urljoin(base_url, row["href"]))
        if date:
            row["yicai_create_date"] = date


async def _prefetch_one(
    client: httpx.AsyncClient,
    source: SourceConfig,
    url: str,
    config: AppConfig,
    global_limit: asyncio.Semaphore,
    domain_limits: defaultdict[str, asyncio.Semaphore],
) -> SourceResult:
    """处理：用有界 HTTP 请求预取单个来源页面并分类访问状态。
    输入：带入口与筛选规则的来源配置、待处理的 URL、已校验的采集和输出配置。
    - ``client``：已配置超时、重定向和连接池策略的 HTTP 客户端。
    - ``global_limit``：当前网络阶段共享的全局异步信号量。
    - ``domain_limits``：按主机名懒创建的异步信号量；限制同域并发请求数。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    collected_at = now_iso(config.timezone)
    domain = urlsplit(url).netloc.lower()
    first_transport_error = None
    async with domain_limits[domain], global_limit:
        for attempt in range(1, 3):
            try:
                async with client.stream("GET", url) as response:
                    limit = max(1, config.browser.http_prefetch_max_bytes)
                    if response.status_code >= 400:
                        limit = min(limit, 65536)
                    content, truncated = await read_bounded_response(response, limit)
                break
            except Exception as exc:
                error = f"HTTP prefetch {type(exc).__name__}: {exc}"
                cause = exc
                tls_error = False
                while cause is not None:
                    if isinstance(cause, ssl.SSLError) or (
                        "certificate verify failed" in str(cause).lower()
                    ):
                        tls_error = True
                        break
                    cause = cause.__cause__ or cause.__context__
                retryable = isinstance(exc, (
                    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError,
                    httpx.RemoteProtocolError,
                )) and not tls_error
                if attempt == 1 and retryable:
                    first_transport_error = error
                    continue
                return SourceResult(
                    source_id=source.id,
                    source_name=source.name,
                    source_url=url,
                    status=SourceStatus.FAILED,
                    collected_at=collected_at,
                    module=source.module,
                    category=source.category,
                    error=error,
                    challenge={"prefetch_error": True, "attempt_count": attempt,
                               "first_transport_error": first_transport_error},
                )

    encoding = response.encoding or "utf-8"
    body = content.decode(encoding, errors="replace")
    if source.adapter_name == "weibo_api" and response.status_code < 400 and not truncated:
        try:
            items = weibo_items_from_payload(json.loads(body), source, collected_at)
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            items = []
            status = SourceStatus.FAILED
            error = f"Invalid Weibo listing: {exc}"
        else:
            status = SourceStatus.SUCCESS if items else SourceStatus.NO_ITEMS
            error = None
            for item in items:
                item.metadata["listing_endpoint"] = str(response.url)
        return SourceResult(
            source_id=source.id, source_name=source.name, source_url=url,
            status=status, collected_at=collected_at, module=source.module,
            category=source.category, final_url=str(response.url),
            http_status=response.status_code, error=error, items=items,
        )
    soup, title, rows = _html_index_document(body)
    if source.id == "yicai_economy":
        _yicai_publication_dates(soup, rows, str(response.url))
    challenge = classify_access_text(
        response.status_code,
        title,
        soup.get_text(" ", strip=True)[:30000],
        iframe_detected=bool(soup.select_one(
            'iframe[src*="captcha"], iframe[src*="challenge"], '
            'iframe[title*="challenge" i]'
        )),
    )
    challenge["attempt_count"] = attempt
    if first_transport_error:
        challenge["first_transport_error"] = first_transport_error
    if truncated:
        challenge["response_truncated"] = True
    if any(
        "cookie" in hop.request.headers or "authorization" in hop.request.headers
        or "set-cookie" in hop.headers
        or any(value.strip().lower() in {"cookie", "authorization", "*"}
               for value in hop.headers.get("vary", "").split(","))
        for hop in (*response.history, response)
    ):
        # 不保留请求头值，仅标识另一个 HTTP 客户端不能复用的会话响应。
        challenge["session_dependent"] = True
    if challenge["rate_limited"]:
        status = SourceStatus.RATE_LIMITED
        items = []
    elif challenge["required"]:
        status = SourceStatus.VERIFICATION_REQUIRED
        items = []
    elif response.status_code >= 400:
        status = SourceStatus.FAILED
        items = []
    else:
        items = browser_items_from_rows(rows, source, collected_at, str(response.url))
        status = SourceStatus.SUCCESS if items else SourceStatus.NO_ITEMS
        if truncated:
            status = SourceStatus.PARTIAL if items else SourceStatus.FAILED
    return SourceResult(
        source_id=source.id,
        source_name=source.name,
        source_url=url,
        status=status,
        collected_at=collected_at,
        module=source.module,
        category=source.category,
        page_title=title,
        final_url=str(response.url),
        http_status=response.status_code,
        error=(f"HTTP {response.status_code}" if response.status_code >= 400 else
               f"Response truncated at {limit} bytes" if truncated else None),
        challenge=challenge,
        items=items,
    )


async def _prefetch_all(
    sources: list[SourceConfig],
    config: AppConfig,
    data_dir: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    shared_listing_pages: dict[tuple[str, str], SourceResult] | None = None,
) -> dict[tuple[str, str], SourceResult]:
    """处理：按全局和同域并发限制预取全部来源页面。
    输入：已校验的采集和输出配置、本次运行的数据根。
    - ``sources``：本轮选择的来源配置列表；每项定义采集入口、策略和身份信息。
    - ``transport``：测试可注入的 HTTP 传输层；生产通常为空并使用真实网络。
    - ``shared_listing_pages``：同轮监控保留的完整 HTTP 页面，按来源及原始 URL 匹配。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    requested = [
        (source, url)
        for source in sources
        if source.adapter_name in {"browser_index", "weibo_api"}
        for url in source_urls(source, data_dir)
    ]
    shared_listing_pages = shared_listing_pages or {}
    reused = {
        (source.id, url): shared_listing_pages[(source.id, url)]
        for source, url in requested
        if (source.id, url) in shared_listing_pages
    }
    jobs = [(source, url) for source, url in requested if (source.id, url) not in reused]
    if not jobs:
        return reused
    global_limit = asyncio.Semaphore(
        max(1, config.browser.collection_global_concurrency)
    )
    per_domain = max(1, config.browser.collection_per_domain_concurrency)
    domain_limits: defaultdict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(per_domain)
    )
    timeout = max(1, config.browser.http_prefetch_timeout_ms) / 1000
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        transport=transport,
    ) as client:
        results = await asyncio.gather(
            *(
                _prefetch_one(
                    client,
                    source,
                    url,
                    config,
                    global_limit,
                    domain_limits,
                )
                for source, url in jobs
            )
        )
    reused.update({
        (source.id, url): result
        for (source, url), result in zip(jobs, results, strict=True)
    })
    return reused


def prefetch_browser_pages(
    sources: list[SourceConfig],
    config: AppConfig,
    data_dir: Path,
    *,
    shared_listing_pages: dict[tuple[str, str], SourceResult] | None = None,
) -> dict[tuple[str, str], SourceResult]:
    """处理：按全局与同域并发限制预取来源页面，供后续采集判断是否需要浏览器。
    输入：已校验的采集和输出配置、本次运行的数据根。
    - ``sources``：本轮选择的来源配置列表；每项定义采集入口、策略和身份信息。
    - ``shared_listing_pages``：可选的同轮、同配置完整 HTML 预取结果。
    输出：供索引汇总的来源采集结果；包含明确状态、错误或挑战信息、页面元数据和规范文章条目。
    """
    return asyncio.run(_prefetch_all(
        sources, config, data_dir, shared_listing_pages=shared_listing_pages,
    ))


def page_needs_browser(result: SourceResult | None) -> bool:
    """判断 HTTP 预取之后 Edge 是否仍能增加有效信息。
    输入：``result``：上游 HTTP 预取或来源采集结果；读取状态、响应类型和页面证据决定后续路径。
    """
    if result is None:
        return True
    status = SourceStatus(result.status)
    if status == SourceStatus.RATE_LIMITED:
        return False
    if result.challenge.get("response_truncated"):
        return True
    if status == SourceStatus.SUCCESS and result.items:
        return False
    return not (
        status == SourceStatus.FAILED
        and result.http_status not in {None, 401, 403}
    )
