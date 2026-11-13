from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import html
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, Page, async_playwright
from playwright.async_api import Error as PlaywrightError

from .access import classify_access_text, read_bounded_response
from .article_time import original_publication_time, uses_platform_publication_time
from .collection_diagnostics import content_gaps, has_local_content
from .config import AppConfig, SourceConfig, resolve_browser_channel, resolve_profile_dir
from .content_extraction import (
    ExtractedDocument,
    extract_with_fallback,
    input_fingerprint,
    is_navigation_only,
    observed_source_metadata,
)
from .content_images import article_image_candidates
from .image_policy import normalize_image_candidates
from .models import ContentStatus
from .pdf_content import extract_pdf
from .runtime import require_data_root_path
from .storage import next_revision, write_bytes_atomic, write_immutable_json, write_text_atomic
from .utils import now_iso, read_json, timestamp_slug, write_json

_MAX_CONTENT_BYTES = 4 * 1024 * 1024
_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Edg/131.0 Safari/537.36"
)
_HTTP_ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.8"


@dataclass(slots=True)
class PublicationPage:
    """处理：暂存可用于正文提取的完整公开响应。
    输入：日期探测取得的字节、编码、最终地址和访问方式。
    输出：仅在采集进程内传递的网页材料。
    """

    body: bytes
    encoding: str
    url: str
    status_code: int
    acquisition: str


def synchronize_nested_items(payload: dict[str, Any]) -> None:
    """处理：让旧版嵌套条目视图与规范根级条目数组保持一致。
    输入：
    - ``payload``：上游传入的结构化对象；函数只读取处理说明列出的受支持字段。
    输出：不返回新数据；完成“让旧版嵌套条目视图与规范根级条目数组保持一致”，
      副作用限于该处理声明的受控对象或产物。
    """
    # 根级 items 是规范记录；sources[].items[] 只是必须继续支持的旧版索引视图。
    root_items = {
        item.get("item_id"): item
        for item in payload.get("items", [])
        if isinstance(item, dict) and item.get("item_id")
    }
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        for nested in source.get("items", []):
            if not isinstance(nested, dict):
                continue
            canonical = root_items.get(nested.get("item_id"))
            if canonical is not None:
                nested.clear()
                nested.update(canonical)


async def meta_content(page: Page, selectors: list[str]) -> str:
    """处理：按选择器读取首个非空页面元数据值。
    输入：
    - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
    - ``selectors``：按优先级排列的 CSS 选择器；用于寻找元数据或正文区域。
    输出：“按选择器读取首个非空页面元数据值”得到的规范字符串，供调用方存储、比较或展示。
    """
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count():
            value = await locator.first.get_attribute("content")
            value = value or await locator.first.get_attribute("datetime")
            if value:
                return value.strip()
    return ""


def _apply_page_publication_time(item: dict[str, Any], published: str) -> None:
    """处理：把原网页日期写入直接来源，同时保留发现平台的发布时间。
    输入：规范索引条目和从原网页元数据读出的发布日期。
    输出：发布者日期按网页和Feed时区证据合并；真正平台保留提交时间。
    """
    if not published or uses_platform_publication_time(item):
        return
    metadata = item.get("metadata") or {}
    projected = {**item, "metadata": {**metadata, "content_source": {
        **(metadata.get("content_source") or {}), "published_at": published}}}
    resolved = original_publication_time(projected)
    if resolved:
        item["published_at"] = resolved


def _content_url(item: dict[str, Any]) -> str:
    """处理：正文抓取优先使用日期探测已解析的 Google News 发布者地址。
    输入：规范索引条目和已有原文地址。
    输出：供 HTTP 与浏览器共用的请求地址，条目标识继续使用索引 URL。
    """
    if item.get("source_id") == "google_news_china":
        source = (item.get("metadata") or {}).get("content_source") or {}
        if source.get("url"):
            return str(source["url"])
    return str(item["url"])


async def probe_publication_time(
    client: httpx.AsyncClient, url: str, *, max_bytes: int = 1024 * 1024,
    retain: Callable[[str, dict, PublicationPage], None] | None = None,
) -> dict[str, Any]:
    """处理：读取有界网页日期，并将完整 HTML 交给本轮采集器暂存。
    输入：HTTP 客户端、原文地址、响应上限和可选的暂存回调。
    输出：发布者原始日期及访问状态，正文响应留在内存中。
    """
    try:
        async with client.stream("GET", url) as response:
            content, truncated = await read_bounded_response(response, max_bytes)
    except httpx.HTTPError as exc:
        return {"status": "failed", "published_at": None,
                "error": f"{type(exc).__name__}: {exc}"}
    result = {
        **_publication_probe_result(content, response.status_code, str(response.url)),
        "bytes": len(content), "truncated": truncated,
    }
    if retain is not None and not truncated and result["status"] == "success":
        _retain_publication_page(url, result, content, response.headers, "http", retain,
                                 encoding=response.encoding)
    return result


def _retain_publication_page(
    url: str, result: dict, body: bytes, headers: Any, acquisition: str,
    retain: Callable[[str, dict, PublicationPage], None], *, encoding: str | None = None,
) -> None:
    """处理：将完整网页连同编码和最终地址交给本轮采集。
    输入：响应字节、HTTP 头、访问方式及暂存回调。
    输出：回调接收网页材料，非网页响应仅保留原日期回执。
    """
    content_type = headers.get("content-type", "").lower()
    if content_type and not any(kind in content_type for kind in (
            "text/html", "application/xhtml+xml", "text/plain")):
        return
    if encoding is None:
        encoding = httpx.Response(200, headers={"content-type": content_type}).encoding
    retain(url, result, PublicationPage(
        body, encoding or "utf-8", result["final_url"], result["http_status"], acquisition,
    ))


def _publication_probe_result(content: bytes, status_code: int, url: str) -> dict[str, Any]:
    """处理：从同一份发布者 HTML 识别访问状态和原始日期。
    输入：有界 HTTP 响应、状态码和最终页面地址。
    输出：保留验证、限流或失败语义的日期探测回执。
    """
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    access = classify_access_text(status_code, title, soup.get_text(" ", strip=True))
    status = ("rate_limited" if access["rate_limited"] else
              "verification_required" if access["required"] else
              "failed" if status_code >= 400 else "success")
    return {"status": status,
            "published_at": observed_source_metadata(soup, url)["published_at"]
            if status == "success" else None,
            "http_status": status_code, "final_url": url}


async def probe_google_news_dates(
    urls: list[str], config: AppConfig, *,
    retain: Callable[[str, dict, PublicationPage], None] | None = None,
) -> dict[str, dict]:
    """处理：在无账号浏览器中等待 Google News 公开跳转，再读取发布者日期。
    输入：静态请求仍停在 Google News 的包装地址与浏览器并发配置。
    输出：各包装地址对应的原文日期、最终 URL 和实际访问状态。
    """
    limit = asyncio.Semaphore(config.browser.global_concurrency)
    timeout = min(config.browser.navigation_timeout_ms, 8000)
    results = {}
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, channel=resolve_browser_channel(config),
            )
            try:
                context = await browser.new_context()

                async def probe(url: str) -> None:
                    """处理：监听主框架的公开跳转并读取最终文档。
                    输入：一条待解析的 Google News 包装地址。
                    输出：把原文或访问失败的短回执写入对应地址的结果。
                    """
                    async with limit:
                        page = await context.new_page()
                        try:
                            await page.route(
                                "**/*", lambda route: route.abort()
                                if route.request.resource_type in {"image", "media", "font"}
                                else route.continue_(),
                            )
                            async with page.expect_response(
                                lambda response: response.request.is_navigation_request()
                                and response.request.frame == page.main_frame
                                and not f".{urlsplit(response.url).hostname}".endswith(
                                    ".google.com"
                                )
                                and not 300 <= response.status < 400,
                                timeout=timeout,
                            ) as final:
                                await page.goto(url, wait_until="commit", timeout=timeout)
                            response = await final.value
                            content = await asyncio.wait_for(response.body(), timeout / 1000)
                            result = _publication_probe_result(
                                content[:1024 * 1024], response.status, response.url,
                            )
                            results[url] = result
                            if (retain is not None and len(content) <= _MAX_CONTENT_BYTES
                                    and result["status"] == "success"):
                                _retain_publication_page(
                                    url, result, content, response.headers, "browser_response",
                                    retain,
                                )
                        except (PlaywrightError, TimeoutError) as exc:
                            results[url] = {"status": "failed", "published_at": None,
                                            "final_url": page.url, "error": str(exc)}
                        finally:
                            await page.close()

                await asyncio.gather(*(probe(url) for url in urls))
            finally:
                await browser.close()
    except PlaywrightError as exc:
        for url in urls:
            results.setdefault(url, {"status": "failed", "published_at": None,
                                     "final_url": url, "error": str(exc)})
    return results


async def meta_contents(page: Page, selectors: list[str]) -> list[str]:
    """处理：按选择器收集并去重全部非空页面元数据值。
    输入：
    - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
    - ``selectors``：按优先级排列的 CSS 选择器；用于寻找元数据或正文区域。
    输出：“按选择器收集并去重全部非空页面元数据值”得到的字符串列表；
      顺序保持确定并可供下一步骤逐项处理。
    """
    values: list[str] = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(await locator.count(), 8)):
            value = await locator.nth(index).get_attribute("content")
            value = value or await locator.nth(index).get_attribute("datetime")
            if value:
                values.append(value.strip())
    return values


async def extract_visible_text(page: Page, selectors: list[str]) -> tuple[str, str | None]:
    """处理：使用共享结构规则读取浏览器正文，保留短公告和段落边界。
    输入：已加载的页面与来源正文选择器；页面内容只作为不可信数据。
    输出：正文文本和选中选择器，供兼容调用方读取。
    """
    document = await _browser_document(page, selectors)
    return document.text, document.selector


async def _browser_document(
    page: Page, selectors: list[str], *, expected_title: str = "", fallback: str = "none",
) -> ExtractedDocument:
    """处理：排除浏览器实际隐藏的区域后复用静态正文抽取规则。
    输入：已加载页面和来源选择器；只读取可见页面作为证据。
    输出：带结构块和质量结果的正文，CSS 隐藏文本不会进入证据视图。
    """
    await page.locator("body *").evaluate_all("""nodes => nodes.filter(node => {
        const style = getComputedStyle(node);
        return style.display === 'none' || style.visibility === 'hidden';
    }).forEach(node => node.remove())""")
    markup = await page.content()
    document = extract_with_fallback(
        BeautifulSoup(markup, "html.parser"), selectors,
        expected_title=expected_title, fallback=fallback,
    )
    document.provenance = input_fingerprint(markup.encode("utf-8"), "visible_dom_utf8", False)
    return document


def save_markdown(path: Path, item: dict[str, Any], body: str, retrieved_at: str) -> None:
    """处理：把规范条目元数据和提取正文写成带 YAML frontmatter 的 Markdown。
    输入：
    - ``path``：当前函数要读取、校验或写入的本地文件路径。
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``body``：正文或 HTML 文本；保存前只作为数据处理。
    - ``retrieved_at``：正文成功提取或确认的 ISO 时间；写入 Markdown frontmatter。
    输出：不返回新数据；完成“把规范条目元数据和提取正文写成带 YAML frontmatter 的 Markdown”，
      副作用限于该处理声明的受控对象或产物。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "title": item.get("title", ""),
        "source": item.get("source_name", ""),
        "url": item.get("url", ""),
        "retrieved_at": retrieved_at,
        "content_status": item.get("content_status", ""),
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(["---", "", body.strip(), ""])
    write_text_atomic(path, "\n".join(lines))


def _html_meta(soup: BeautifulSoup, selectors: list[str]) -> str:
    """处理：从静态 HTML 中读取首个非空元数据值。
    输入：
    - ``soup``：由不可信 HTML 构建的 BeautifulSoup 文档；不会执行任何脚本。
    - ``selectors``：按优先级排列的 CSS 选择器；用于寻找元数据或正文区域。
    输出：“从静态 HTML 中读取首个非空元数据值”得到的规范字符串，供调用方存储、比较或展示。
    """
    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        value = node.get("content") or node.get("datetime") or node.get_text(" ", strip=True)
        if value:
            return str(value).strip()
    return ""


def _html_meta_values(soup: BeautifulSoup, selectors: list[str]) -> list[str]:
    """处理：从静态 HTML 中收集全部匹配的元数据值。
    输入：
    - ``soup``：由不可信 HTML 构建的 BeautifulSoup 文档；不会执行任何脚本。
    - ``selectors``：按优先级排列的 CSS 选择器；用于寻找元数据或正文区域。
    输出：“从静态 HTML 中收集全部匹配的元数据值”得到的字符串列表；
      顺序保持确定并可供下一步骤逐项处理。
    """
    values: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            value = (
                node.get("content")
                or node.get("datetime")
                or node.get_text(" ", strip=True)
            )
            if value:
                values.append(str(value).strip())
    return values


def _apply_image_candidates(
    item: dict[str, Any],
    values: list[object],
    base_url: str,
    *,
    details: list[dict[str, Any]] | None = None,
) -> None:
    """处理：规范化图片候选，并同步主图片与候选元数据。
    输入：
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``values``：待规范化、匹配或渲染的一组输入值。
    - ``base_url``：解析相对链接时使用的最终页面或 Feed 基准 URL。
    输出：不返回新数据；完成“规范化图片候选，并同步主图片与候选元数据”，
      副作用限于该处理声明的受控对象或产物。
    """
    metadata = item.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        item["metadata"] = metadata
    stored_candidates = metadata.get("image_candidates")
    if not isinstance(stored_candidates, list):
        stored_candidates = []
    details = details or []
    contextual = [entry["url"] for entry in details if (
        entry.get("caption") or entry.get("relevance_score", 0) > 0
    )]
    candidates = normalize_image_candidates(
        [*contextual, *values, item.get("image_url"),
         *(entry["url"] for entry in details), *stored_candidates],
        base_url,
    )
    if not candidates:
        item.pop("image_url", None)
        metadata.pop("image_candidates", None)
        metadata.pop("image_candidate_details", None)
        return
    by_url = {entry["url"]: entry for entry in reversed(details)}
    page_urls = set(normalize_image_candidates(values, base_url))
    metadata["image_candidate_details"] = [
        by_url.get(url, {
            "url": url,
            "provenance": "page_metadata" if url in page_urls else "index_card",
            "purpose": "publisher_selected",
            "caption": "",
            "semantic_verification": "not_performed",
        }) for url in candidates
    ]
    item["image_url"] = candidates[0]
    if len(candidates) > 1:
        metadata["image_candidates"] = candidates
    else:
        metadata.pop("image_candidates", None)


def _content_output_path(
    data_dir: Path,
    source_id: str,
    item_id: object,
    timezone: str,
) -> Path:
    """处理：按来源、条目和采集时间生成正文 Markdown 路径。
    输入：
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``source_id``：来源的稳定 ID；用于配置查找、索引关联和状态分区。
    - ``item_id``：规范条目的稳定 ID；用于连接索引、正文、简报和图片。
    - ``timezone``：IANA 时区名称；用于解析无时区时间并生成日报时间边界。
    输出：指向“按来源、条目和采集时间生成正文 Markdown 路径”所生成、定位或确认产物的本地路径。
    """
    return (
        data_dir
        / "content"
        / source_id
        / str(item_id)
        / f"{timestamp_slug(timezone)}-{uuid4().hex}.md"
    )


def _save_document(
    item: dict[str, Any], document: ExtractedDocument, source: SourceConfig,
    config: AppConfig, data_dir: Path,
    *, raw_content: bytes | None = None,
) -> None:
    """处理：同步正文状态并保存同一抽取结果的结构 JSON 与 Markdown 视图。
    输入：当前条目、抽取结果、来源配置以及绑定的数据根。
    输出：条目获得质量记录及不可碰撞的正文路径；无有效正文时清除旧路径。
    """
    if is_navigation_only(document.text):
        document.text = ""
        document.blocks = []
        document.status = ContentStatus.METADATA_ONLY
        document.quality["navigation_only"] = True
    item["content_status"] = document.status
    item["content_characters"] = len(document.text)
    metadata = item["metadata"]
    metadata["content_needs_refresh"] = False
    metadata["content_selector"] = document.selector
    metadata["content_quality"] = document.quality
    metadata["content_input"] = document.provenance
    if item.get("source_id") == "google_news_china":
        previous_source = metadata.get("content_source") or {}
        for field in ("url", "published_at"):
            if previous_source.get(field) and not document.source_metadata.get(field):
                document.source_metadata[field] = previous_source[field]
    metadata["content_source"] = document.source_metadata
    metadata["content_text_sha256"] = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
    item.pop("content_path", None)
    metadata.pop("content_blocks_path", None)
    metadata.pop("content_artifacts", None)
    if document.status == ContentStatus.METADATA_ONLY:
        return
    output = _content_output_path(data_dir, source.id, item.get("item_id"), config.timezone)
    retrieved_at = now_iso(config.timezone)
    blocks_path = output.with_suffix(".json")
    write_immutable_json(blocks_path, {
        "schema_version": "1.1", "item_id": item.get("item_id"),
        "url": item.get("url"), "retrieved_at": retrieved_at,
        "acquisition": metadata.get("content_acquisition"),
        "selector": document.selector, "quality": document.quality,
        "input": document.provenance,
        "source_metadata": document.source_metadata,
        "text_sha256": hashlib.sha256(document.text.encode("utf-8")).hexdigest(),
        "blocks": document.blocks,
    })
    save_markdown(output, item, document.text, retrieved_at)
    item["content_path"] = str(output)
    metadata["content_blocks_path"] = str(blocks_path)
    manifest = {
        "markdown_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "blocks_sha256": hashlib.sha256(blocks_path.read_bytes()).hexdigest(),
        "raw_retained": False,
    }
    # 原响应只对显式启用的无登录 HTTP 抓取留存；浏览器会话永远不写原始 HTML。
    if config.collection.retain_public_html and raw_content is not None:
        raw_path = output.with_suffix(".response.bin")
        write_bytes_atomic(raw_path, raw_content)
        manifest.update(
            raw_retained=True, raw_path=str(raw_path),
            raw_sha256=hashlib.sha256(raw_content).hexdigest(),
        )
    metadata["content_artifacts"] = manifest


def _apply_http_document(
    item: dict[str, Any],
    source: SourceConfig,
    body_html: str,
    final_url: str,
    http_status: int | None,
    config: AppConfig,
    data_dir: Path,
    *,
    truncated: bool = False,
    raw_content: bytes | None = None,
    acquisition: str = "http",
    require_complete: bool = False,
) -> bool:
    """处理：应用惰性 HTTP 正文，并判断浏览器回退是否仍有价值。
    输入：
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``source``：来源配置；包含来源 ID、名称、入口 URL、分类、过滤规则、限额和可信层级。
    - ``body_html``：HTTP 响应中提取的静态 HTML；作为不可信数据解析元信息和正文。
    - ``final_url``：导航或重定向完成后的页面 URL。
    - ``http_status``：页面最近一次 HTTP 状态码；无网络响应时可为空。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``acquisition``：HTTP 或动态浏览器渠道；动态页面只保存抽取正文及指纹。
    - ``require_complete``：日期探测只保存可直接复用的全文，正文阶段负责处理其他证据。
    输出：布尔判断；True 表示满足处理说明中的条件，False 表示不满足且不产生该结果。
    """
    metadata = item.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        item["metadata"] = metadata
    soup = BeautifulSoup(body_html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    challenge = classify_access_text(
        http_status,
        page_title,
        soup.get_text(" ", strip=True)[:30000],
        iframe_detected=bool(soup.select_one(
            'iframe[src*="captcha"], iframe[src*="challenge"], '
            'iframe[title*="challenge" i]'
        )),
    )
    metadata["content_http_status"] = http_status
    metadata["content_http_final_url"] = final_url
    metadata["content_acquisition"] = acquisition
    metadata.pop("content_image_evidence", None)
    if challenge["required"] or challenge["rate_limited"]:
        item["content_status"] = ContentStatus.VERIFICATION_REQUIRED
        metadata["content_challenge"] = challenge
        return False
    if http_status is not None and http_status >= 400:
        item["content_status"] = ContentStatus.FAILED
        metadata["content_error"] = f"HTTP {http_status}"
        return False

    metadata.pop("content_challenge", None)
    metadata.pop("content_error", None)
    metadata.pop("content_http_error", None)
    metadata.setdefault("discovered_title", item.get("title"))

    title = _html_meta(
        soup,
        ['meta[property="og:title"]', 'meta[name="twitter:title"]'],
    )
    if title:
        item["title"] = html.unescape(title)
    description = _html_meta(
        soup,
        ['meta[name="description"]', 'meta[property="og:description"]'],
    )
    if description:
        item["description"] = html.unescape(description)
    image_candidates = _html_meta_values(
        soup,
        ['meta[property="og:image"]', 'meta[name="og:image"]',
         'meta[name="twitter:image"]', 'meta[property="twitter:image"]'],
    )
    input_bytes = body_html.encode("utf-8") if raw_content is None else raw_content
    document = extract_with_fallback(
        soup, source.content_selectors, truncated=truncated,
        expected_title=str(metadata.get("discovered_title") or ""),
        fallback=config.collection.fallback_extractor,
    )
    if require_complete and (document.status != ContentStatus.FULL_TEXT
                             or document.quality.get("numeric_tables_without_headers")):
        return True
    _apply_page_publication_time(
        item, str(document.source_metadata.get("published_at") or "")
    )
    document.provenance = input_fingerprint(
        input_bytes,
        "visible_dom_utf8" if acquisition == "crawl4ai" else
        "browser_response_body" if acquisition == "browser_response" else
        "decoded_html_utf8" if raw_content is None else "http_response_body",
        truncated,
    )
    _apply_image_candidates(
        item, image_candidates, final_url,
        details=article_image_candidates(document, str(item.get("title") or ""), final_url),
    )
    _save_document(
        item, document, source, config, data_dir,
        raw_content=input_bytes if acquisition == "http" else None,
    )
    article_url = urldefrag(item["url"]).url
    if (
        acquisition == "http" and raw_content is not None and not truncated
        and item["content_status"] == ContentStatus.FULL_TEXT
        and article_url == urldefrag(final_url).url
        and set(source.content_selectors) <= {"article", "main", "body", "html"}
        and any(image.get("provenance") == "article_body"
                for image in metadata.get("image_candidate_details", []))
    ):
        metadata["content_image_evidence"] = {
            "url": article_url, "input_sha256": document.provenance["sha256"],
        }
    # 已明确截断的传输和订阅提示不会靠重开浏览器消除；其他正文缺口最多升级一次。
    return document.status != ContentStatus.FULL_TEXT and not truncated and not (
        document.quality.get("incomplete_marker") and document.status == ContentStatus.PARTIAL
    )


def prepare_publication_content(
    item: dict, page: PublicationPage, source: SourceConfig, config: AppConfig, data_dir: Path,
) -> dict | None:
    """处理：用完整日期探测响应执行标准正文提取。
    输入：通过当日筛选的条目、网页材料及正文存储配置。
    输出：可供选中正文任务复用的快照，包含全文和图片引用。
    """
    enriched = copy.deepcopy(item)
    _apply_http_document(
        enriched, source, page.body.decode(page.encoding, errors="replace"),
        page.url, page.status_code, config, data_dir, raw_content=page.body,
        acquisition=page.acquisition, require_complete=True,
    )
    if not _has_reusable_content(enriched, data_dir):
        return None
    # 日期与来源原始字段留在采集索引；正文阶段再应用网页标题、图片和证据。
    metadata = enriched["metadata"]
    return {
        "image_url": enriched.get("image_url"),
        **{key: enriched[key] for key in (
            "title", "description", "content_status", "content_path",
            "content_characters",
        ) if key in enriched},
        "metadata": {key: value for key, value in metadata.items()
                     if key.startswith("content_") or key in {
                         "discovered_title", "image_candidates", "image_candidate_details",
                     }},
    }


async def _read_bounded_html(
    response: httpx.Response,
    max_bytes: int = _MAX_CONTENT_BYTES,
) -> tuple[bytes, bool]:
    """处理：流式读取 HTTP 正文并在字节上限处停止。
    输入：
    - ``response``：已建立的 HTTP 流式响应；函数负责读取上限和错误语义。
    - ``max_bytes``：允许读取或下载的最大字节数；达到上限后停止或报错。
    输出：受字节上限约束的正文和截断标记，防止截断响应被称为完整正文。
    """
    return await read_bounded_response(response, max_bytes)


async def _extract_http_one(
    client: httpx.AsyncClient,
    item: dict[str, Any],
    config: AppConfig,
    data_dir: Path,
) -> bool:
    """处理：执行有界无脚本抓取，仅在 Edge 仍可能补充内容时返回真。
    输入：
    - ``client``：已配置超时、重定向和连接池策略的 HTTP 客户端。
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：布尔判断；True 表示满足处理说明中的条件，False 表示不满足且不产生该结果。
    """
    source = config.source_by_id(str(item["source_id"]))
    metadata = item.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        item["metadata"] = metadata
    try:
        async with client.stream("GET", _content_url(item)) as response:
            # 外部响应始终只按不可信数据解析；不会执行页面脚本或其中的文字指令。
            content_type = response.headers.get("content-type", "").casefold()
            if response.status_code < 400 and "application/pdf" in content_type:
                content, truncated = await _read_bounded_html(response)
                document = extract_pdf(content, str(response.url), truncated=truncated)
                metadata.update(
                    content_acquisition="http", content_http_status=response.status_code,
                    content_http_final_url=str(response.url),
                )
                _save_document(item, document, source, config, data_dir)
                if document.quality.get("pdf_error"):
                    metadata["content_error"] = document.quality["pdf_error"]
                return False
            if response.status_code < 400 and content_type and not any(
                marker in content_type
                for marker in ("text/html", "application/xhtml+xml", "text/plain")
            ):
                item["content_status"] = ContentStatus.METADATA_ONLY
                metadata["content_http_status"] = response.status_code
                metadata["content_error"] = (
                    f"unsupported content type {content_type.split(';', 1)[0]}"
                )
                metadata["content_acquisition"] = "http"
                return False
            content, truncated = await _read_bounded_html(response)
            encoding = response.encoding or "utf-8"
            body_html = content.decode(encoding, errors="replace")
            return _apply_http_document(
                item,
                source,
                body_html,
                str(response.url),
                response.status_code,
                config,
                data_dir,
                truncated=truncated,
                raw_content=content,
            )
    except (httpx.HTTPError, UnicodeError) as exc:
        item["content_status"] = ContentStatus.FAILED
        metadata["content_http_error"] = f"{type(exc).__name__}: {exc}"
        metadata["content_acquisition"] = "http_failed"
        return True


async def _run_http_extraction(
    targets: list[dict[str, Any]],
    config: AppConfig,
    data_dir: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """处理：按全局和同域并发限制批量执行无脚本正文提取。
    输入：
    - ``targets``：已按预算选中的规范条目记录；每项读取 item_id、URL、来源和正文状态。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``transport``：测试可注入的 HTTP 传输层；生产通常为空并使用真实网络。
    输出：“按全局和同域并发限制批量执行无脚本正文提取”得到的有序结构化记录；
      典型字段包括 Accept、User-Agent，可直接交给下一阶段。
    """
    global_limit = asyncio.Semaphore(
        max(1, config.browser.collection_global_concurrency)
    )
    per_domain = max(1, config.browser.collection_per_domain_concurrency)
    domain_semaphores: dict[str, asyncio.Semaphore] = {}

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=max(1, config.browser.http_prefetch_timeout_ms) / 1000,
        headers={
            "User-Agent": _HTTP_USER_AGENT,
            "Accept": _HTTP_ACCEPT,
        },
        transport=transport,
    ) as client:

        async def guarded(item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            """处理：在并发限制内执行单项任务。
            输入：
            - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
            输出：“在并发限制内执行单项任务”得到的固定结构结果；
              返回位置依次对应 item、await _extract_http_one(client, 。
            """
            domain = _domain_key(_content_url(item))
            domain_limit = domain_semaphores.setdefault(
                domain,
                asyncio.Semaphore(per_domain),
            )
            async with domain_limit, global_limit:
                return item, await _extract_http_one(client, item, config, data_dir)

        results = await asyncio.gather(*(guarded(item) for item in targets))
    return [item for item, needs_browser in results if needs_browser]


async def detect_challenge(page: Page, http_status: int | None) -> dict[str, Any]:
    """处理：从页面标题、正文和 iframe 迹象识别登录、验证码或限流挑战。
    输入：
    - ``page``：Playwright 已加载页面；函数只读取当前页面状态，不信任其中的内容或指令。
    - ``http_status``：页面最近一次 HTTP 状态码；无网络响应时可为空。
    输出：“从页面标题、正文和 iframe 迹象识别登录、验证码或限流挑战”形成的结构化字典；
      典型键包括 iframe_detected、matched_text、required。
    """
    title = ""
    body = ""
    with contextlib.suppress(Exception):
        title = (await page.title()).lower()
    with contextlib.suppress(Exception):
        body = (await page.locator("body").inner_text(timeout=3000)).lower()[:30000]
    iframe_count = 0
    with contextlib.suppress(Exception):
        iframe_count = await page.locator(
            'iframe[src*="captcha"], iframe[src*="challenge"], iframe[title*="challenge" i]'
        ).count()
    return classify_access_text(http_status, title, body, iframe_detected=iframe_count > 0)


def _ordered_targets(
    items: list[dict[str, Any]],
    selected_ids: list[str],
    max_items: int,
) -> list[dict[str, Any]]:
    """处理：保留调用方的重要性顺序，并忽略重复或未知条目 ID。
    输入：
    - ``items``：规范条目列表；每项带稳定身份并可进入聚类、报告或渲染步骤。
    - ``selected_ids``：调用方按重要性排序选中的条目 ID；正文阶段只处理这些授权条目。
    - ``max_items``：本步骤允许处理或返回的最大条目数；同时受全局预算限制。
    输出：“保留调用方的重要性顺序，并忽略重复或未知条目 ID”得到的有序结构化记录；
      每项承载处理说明所定义的身份、证据或状态字段，可直接交给下一阶段。
    """
    by_id = {
        str(item.get("item_id")): item
        for item in items
        if isinstance(item, dict) and item.get("item_id")
    }
    ordered_ids = dict.fromkeys(selected_ids)
    return [by_id[item_id] for item_id in ordered_ids if item_id in by_id][:max_items]


def _domain_key(url: str) -> str:
    """处理：从 URL 提取用于同域并发限制的规范主机键。
    输入：
    - ``url``：调用方提供的 URL；当前函数按处理说明进行规范化、过滤或访问。
    输出：可跨修订关联的稳定字符串标识，供索引、状态或发布记录使用。
    """
    return urlsplit(url).netloc.lower().removeprefix("www.") or "unknown"


async def _extract_one(
    context: BrowserContext,
    item: dict[str, Any],
    config: AppConfig,
    data_dir: Path,
) -> None:
    """处理：在浏览器中提取单篇文章的元数据、正文和访问状态。
    输入：
    - ``context``：浏览器、写作或报告上下文对象；包含当前阶段已经绑定的受控状态。
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：不返回新数据；完成“在浏览器中提取单篇文章的元数据、正文和访问状态”，
      副作用限于该处理声明的受控对象或产物。
    """
    source = config.source_by_id(str(item["source_id"]))
    metadata = item.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        item["metadata"] = metadata
    page = await context.new_page()
    response = None
    try:
        response = await page.goto(
            _content_url(item),
            wait_until="domcontentloaded",
            timeout=config.browser.navigation_timeout_ms,
        )
        wait_ms = source.wait_ms or min(config.browser.default_wait_ms, 1000)
        http_status = response.status if response else None
        if http_status is None or http_status < 400:
            await _wait_for_article_text(page, source.content_selectors, wait_ms)
        metadata["content_acquisition"] = "browser"
        metadata["content_http_status"] = http_status
        metadata["content_http_final_url"] = page.url
        challenge = await detect_challenge(page, http_status)
        if challenge["required"] or challenge["rate_limited"]:
            item["content_status"] = ContentStatus.VERIFICATION_REQUIRED
            metadata["content_challenge"] = challenge
            return
        if http_status is not None and http_status >= 400:
            item["content_status"] = ContentStatus.FAILED
            metadata["content_http_status"] = http_status
            metadata["content_error"] = f"HTTP {http_status}"
            return
        metadata.pop("content_challenge", None)
        metadata.pop("content_error", None)
        metadata.pop("content_http_error", None)
        metadata.setdefault("discovered_title", item.get("title"))
        title = await meta_content(
            page, ['meta[property="og:title"]', 'meta[name="twitter:title"]']
        )
        if title:
            item["title"] = html.unescape(title)
        description = await meta_content(
            page,
            ['meta[name="description"]', 'meta[property="og:description"]'],
        )
        if description:
            item["description"] = html.unescape(description)
        image_candidates = await meta_contents(
            page,
            ['meta[property="og:image"]', 'meta[name="twitter:image"]'],
        )
        document = await _browser_document(
            page, source.content_selectors,
            expected_title=str(metadata.get("discovered_title") or ""),
            fallback=config.collection.fallback_extractor,
        )
        _apply_page_publication_time(
            item, str(document.source_metadata.get("published_at") or "")
        )
        _apply_image_candidates(
            item, image_candidates, page.url,
            details=article_image_candidates(document, str(item.get("title") or ""), page.url),
        )
        metadata["content_http_status"] = http_status
        _save_document(item, document, source, config, data_dir)
    except Exception as exc:
        item["content_status"] = ContentStatus.FAILED
        metadata["content_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with contextlib.suppress(Exception):
            await page.close()


async def _wait_for_article_text(page: Page, selectors: list[str], timeout_ms: int) -> None:
    """处理：在配置时限内等待可见正文文字，而非仅等待空容器挂载。
    输入：已加载页面、可信配置选择器和来源等待上限。
    输出：不改变页面；超时仍交给抽取器记录不足，不点击或绕过访问限制。
    """
    with contextlib.suppress(Exception):
        await page.wait_for_function(
            """selectors => selectors.some(selector => {
                try {
                    return Array.from(document.querySelectorAll(selector)).some(node => {
                        const text = (node.innerText || '').trim();
                        return text.length >= 20;
                    });
                } catch { return false; }
            })""",
            arg=list(dict.fromkeys([*selectors, "article", "main"])),
            timeout=max(1, timeout_ms),
        )


async def _run_parallel_extraction(
    context: BrowserContext,
    targets: list[dict[str, Any]],
    config: AppConfig,
    data_dir: Path,
) -> None:
    """处理：执行有界正文提取，跨域并行且同域保持礼貌限流。
    输入：
    - ``context``：浏览器、写作或报告上下文对象；包含当前阶段已经绑定的受控状态。
    - ``targets``：已按预算选中的规范条目记录；每项读取 item_id、URL、来源和正文状态。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：不返回新数据；完成“执行有界正文提取，跨域并行且同域保持礼貌限流”，
      副作用限于该处理声明的受控对象或产物。
    """
    global_limit = max(1, config.browser.global_concurrency)
    domain_limit = max(1, config.browser.per_domain_concurrency)
    global_semaphore = asyncio.Semaphore(global_limit)
    domain_semaphores: dict[str, asyncio.Semaphore] = {}

    async def guarded(item: dict[str, Any]) -> None:
        """处理：在并发限制内执行单项任务。
        输入：
        - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
        输出：不返回新数据；完成“在并发限制内执行单项任务”，
          副作用限于该处理声明的受控对象或产物。
        """
        domain = _domain_key(_content_url(item))
        domain_semaphore = domain_semaphores.setdefault(
            domain, asyncio.Semaphore(domain_limit)
        )
        # 先取得同域名配额，避免同域等待者占满全局配额并阻塞无关来源。
        async with domain_semaphore, global_semaphore:
            await _extract_one(context, item, config, data_dir)

    await asyncio.gather(*(guarded(item) for item in targets))


async def _extract_with_browser(
    targets: list[dict[str, Any]],
    config: AppConfig,
    data_dir: Path,
    headed: bool,
    profile: Path,
    channel: str | None,
) -> None:
    """处理：启动持久化浏览器上下文并批量处理 HTTP 回退条目。
    输入：
    - ``targets``：已按预算选中的规范条目记录；每项读取 item_id、URL、来源和正文状态。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``headed``：是否显示真实浏览器窗口；人工登录或验证场景需要开启。
    - ``profile``：已经解析并创建的浏览器 Profile 绝对路径。
    - ``channel``：Playwright 浏览器通道；为空时使用配置解析出的默认浏览器。
    输出：不返回新数据；完成“启动持久化浏览器上下文并批量处理 HTTP 回退条目”，
      副作用限于该处理声明的受控对象或产物。
    """
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
        try:
            await _run_parallel_extraction(context, targets, config, data_dir)
        finally:
            await context.close()


async def _extract_with_crawl4ai(
    targets: list[dict[str, Any]], config: AppConfig, data_dir: Path, headed: bool,
) -> None:
    """处理：将动态页面交给可选浏览器后端，再复用现有正文质量和保存逻辑。
    输入：HTTP 未补全的条目、并发配置与绑定数据根。
    输出：原条目获得正文、图片和视频候选；访问失败继续保留明确状态。
    """
    from .crawl4ai_adapter import crawl_pages

    pages = await crawl_pages(
        [_content_url(item) for item in targets],
        timeout_ms=config.browser.navigation_timeout_ms,
        concurrency=config.browser.global_concurrency,
        per_domain_concurrency=config.browser.per_domain_concurrency,
        headless=not headed,
    )
    for item, page in zip(targets, pages, strict=True):
        source = config.source_by_id(str(item["source_id"]))
        metadata = item.setdefault("metadata", {})
        if not page["success"] and not page["html"]:
            item["content_status"] = ContentStatus.FAILED
            metadata.update(
                content_acquisition="crawl4ai", content_http_status=page["status_code"],
                content_error=page["error"] or "Dynamic page extraction failed",
            )
            continue
        _apply_http_document(
            item, source, page["html"], page["url"], page["status_code"],
            config, data_dir, acquisition="crawl4ai",
        )
        # SDK 失败或访问受限的页面不提供媒体候选，避免把挑战页装饰图展示成新闻图。
        if not page["success"] or item["content_status"] in {
            ContentStatus.FAILED, ContentStatus.VERIFICATION_REQUIRED,
        }:
            if (not page["success"]
                    and item["content_status"] != ContentStatus.VERIFICATION_REQUIRED):
                item["content_status"] = ContentStatus.FAILED
                metadata["content_error"] = page["error"] or "Dynamic page extraction failed"
            continue
        media = page["media"]
        _apply_image_candidates(
            item, [entry["src"] for entry in media.get("images", []) if entry.get("src")],
            page["url"], details=metadata.get("image_candidate_details", []),
        )
        videos = [
            {"url": urljoin(page["url"], entry["src"]), "source_url": page["url"]}
            for entry in media.get("videos", []) if entry.get("src")
            and urlsplit(urljoin(page["url"], entry["src"])).scheme in {"http", "https"}
        ]
        if videos:
            metadata["video_candidates"] = videos


def _has_reusable_content(item: dict[str, Any], data_dir: Path) -> bool:
    """处理：验证条目正文状态和数据根内文件，判断能否安全复用。
    输入：
    - ``item``：单个规范条目对象；通常包含 item_id、来源、标题、URL、时间和元数据。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：布尔判断；True 表示满足处理说明中的条件，False 表示不满足且不产生该结果。
    """
    return (
        item.get("content_status") == ContentStatus.FULL_TEXT
        and not content_gaps(item, data_dir)
    )


def _resolve_browser_extractor(mode: str, headed: bool) -> str:
    """处理：只在需要动态正文时选择已安装 SDK，交互窗口继续使用 Playwright。
    输入：显式后端或 auto，以及是否要求可见浏览器。
    输出：单次浏览器尝试的后端；不启动浏览器或读取远程内容。
    """
    if mode != "auto":
        return mode
    if headed:
        return "playwright"
    try:
        import_module("crawl4ai")
    except ImportError:
        return "playwright"
    return "crawl4ai"


async def _extract_pipeline(
    targets: list[dict[str, Any]],
    config: AppConfig,
    data_dir: Path,
    headed: bool,
    profile: Path,
    channel: str | None,
) -> dict[str, Any]:
    """处理：复用有效正文，先执行 HTTP 提取，再对必要条目进行浏览器回退。
    输入：
    - ``targets``：已按预算选中的规范条目记录；每项读取 item_id、URL、来源和正文状态。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``headed``：是否显示真实浏览器窗口；人工登录或验证场景需要开启。
    - ``profile``：已经解析并创建的浏览器 Profile 绝对路径。
    - ``channel``：Playwright 浏览器通道；为空时使用配置解析出的默认浏览器。
    输出：“复用有效正文，先执行 HTTP 提取，再对必要条目进行浏览器回退”形成的结构化字典；
      典型键包括 browser_fallback、browser_seconds、cache_hits、http_attempted、http_seconds、ht
      tp_successful、selected、successful、total_seconds。
    """
    started = time.perf_counter()
    probe_hits = set()
    for item in targets:
        metadata = item.setdefault("metadata", {})
        prepared = metadata.pop("publication_probe_content", None)
        if prepared and not headed and _has_reusable_content(prepared, data_dir):
            item.update({key: value for key, value in prepared.items() if key != "metadata"})
            metadata.pop("image_candidates", None)
            metadata.pop("image_candidate_details", None)
            metadata.update(prepared["metadata"])
            probe_hits.add(id(item))
        else:
            _reuse_feed_content(item, config, data_dir)
    reusable = [item for item in targets if _has_reusable_content(item, data_dir)]
    for item in reusable:
        metadata = item.setdefault("metadata", {})
        if isinstance(metadata, dict) and id(item) not in probe_hits:
            metadata["content_acquisition"] = "cache"
    reusable_ids = {id(item) for item in reusable}
    pending = [item for item in targets if id(item) not in reusable_ids]
    previous = {id(item): copy.deepcopy(item) for item in pending}
    attempts: dict[int, list[dict[str, Any]]] = {id(item): [] for item in targets}
    for item in pending:
        _clear_content_attempt(item)

    http_started = time.perf_counter()
    # 先走无脚本 HTTP 快路径；只有失败或内容不足的条目才进入真实浏览器。
    browser_targets = (
        await _run_http_extraction(pending, config, data_dir) if pending else []
    )
    for item in pending:
        attempts[id(item)].append(_content_attempt(item, "http", data_dir))
        _retain_better_content(item, previous[id(item)], data_dir)
    http_seconds = time.perf_counter() - http_started
    browser_started = time.perf_counter()
    browser_extractor = config.collection.browser_extractor
    if browser_targets:
        browser_extractor = _resolve_browser_extractor(browser_extractor, headed)
        previous = {id(item): copy.deepcopy(item) for item in browser_targets}
        for item in browser_targets:
            _clear_content_attempt(item)
        try:
            if browser_extractor == "crawl4ai":
                await _extract_with_crawl4ai(browser_targets, config, data_dir, headed)
            else:
                await _extract_with_browser(
                    browser_targets, config, data_dir, headed, profile, channel,
                )
        except Exception as exc:
            # 浏览器启动失败不得撤销 HTTP 已保存的证据；保留失败尝试并继续产生索引。
            for item in browser_targets:
                item["content_status"] = ContentStatus.FAILED
                item.setdefault("metadata", {})["content_error"] = f"{type(exc).__name__}: {exc}"
        for item in browser_targets:
            attempts[id(item)].append(_content_attempt(
                item, "crawl4ai" if browser_extractor == "crawl4ai" else "browser", data_dir,
            ))
            _retain_better_content(item, previous[id(item)], data_dir)
    browser_seconds = time.perf_counter() - browser_started
    for item in targets:
        metadata = item.setdefault("metadata", {})
        metadata["content_attempts"] = attempts[id(item)]
        gaps = content_gaps(item, data_dir)
        latest = attempts[id(item)][-1] if attempts[id(item)] else None
        access_gaps = [gap for gap in (latest or {}).get("gaps", []) if gap in {
            "rate_limited", "verification_required", "access_failed", "unsupported_content_type",
        }]
        unresolved = list(dict.fromkeys([*gaps, *access_gaps]))
        metadata["content_completion"] = {
            "status": "complete" if not unresolved else "with_gaps",
            "unresolved": unresolved,
            "stop_reason": (
                "evidence_sufficient" if not unresolved else
                access_gaps[0] if access_gaps else
                "bounded_attempts_exhausted" if any(
                    attempt["channel"] in {"browser", "crawl4ai"}
                    for attempt in attempts[id(item)]
                ) else "no_permitted_escalation"
            ),
            "claim_sufficiency": "not_assessed",
        }
    return {
        "selected": len(targets),
        "cache_hits": len(reusable),
        "publication_probe_hits": len(probe_hits),
        "http_attempted": len(pending),
        "http_successful": sum(
            attempt["channel"] == "http" and attempt["status"] in {"full_text", "partial"}
            for records in attempts.values() for attempt in records
        ),
        "browser_fallback": len(browser_targets),
        "browser_extractor": browser_extractor,
        "complete": sum(
            item["metadata"]["content_completion"]["status"] == "complete" for item in targets
        ),
        "with_gaps": sum(
            item["metadata"]["content_completion"]["status"] == "with_gaps" for item in targets
        ),
        "successful": sum(
            has_local_content(item, data_dir) for item in targets
        ),
        "http_seconds": round(http_seconds, 3),
        "browser_seconds": round(browser_seconds, 3),
        "total_seconds": round(time.perf_counter() - started, 3),
    }


def _reuse_feed_content(item: dict[str, Any], config: AppConfig, data_dir: Path) -> None:
    """处理：只为已选正文条目加载 Feed 长内容，作为网页补全失败时的证据底稿。
    输入：已选条目、来源配置与数据根中的 Feed 内容路径。
    输出：条目获得部分正文和原图注；未选候选保持短摘要，Feed 不升格全文。
    """
    metadata = item.setdefault("metadata", {})
    raw_path = metadata.get("feed_content_path")
    if not raw_path or has_local_content(item, data_dir):
        return
    path = require_data_root_path(Path(raw_path), data_dir, "Feed content")
    if not path.exists():
        return
    record = read_json(path)
    if is_navigation_only(record["text"]):
        metadata["feed_navigation_only"] = True
        return
    document = ExtractedDocument(
        text=record["text"], selector="feed_content", blocks=record["blocks"],
        status=ContentStatus.PARTIAL, quality=record["quality"],
        provenance={"kind": "feed_field", "sha256": metadata["feed_content_sha256"],
                    "truncated": record["truncated"]},
        source_metadata={"feed_url": record["feed_url"], "language": record["language"],
                         "mime_type": record["mime_type"], "source_field": record["source_field"]},
    )
    source = config.source_by_id(str(item["source_id"]))
    metadata["content_acquisition"] = "feed"
    _apply_image_candidates(item, [], record["url"], details=record["images"])
    _save_document(item, document, source, config, data_dir)


def _clear_content_attempt(item: dict[str, Any]) -> None:
    """处理：清除上次采集字段，避免新访问失败被错误绑定到旧输入。
    输入：已由流水线另存快照的当前条目。
    输出：保留发现身份与元数据，正文尝试从未知状态重新开始。
    """
    item["content_status"] = ContentStatus.NOT_FETCHED
    item.pop("content_path", None)
    item.pop("content_characters", None)
    metadata = item.setdefault("metadata", {})
    for key in list(metadata):
        if key.startswith("content_"):
            metadata.pop(key)


def _content_attempt(item: dict[str, Any], channel: str, data_dir: Path) -> dict[str, Any]:
    """处理：在回退覆盖条目前记录实际尝试的状态与缺口。
    输入：单次 HTTP 或浏览器处理后的条目、通道和当前数据根。
    输出：不包含页面正文的尝试记录，使保留旧证据时仍能看见新访问失败。
    """
    metadata = item.get("metadata") or {}
    return {
        "channel": channel, "status": item.get("content_status"),
        "http_status": metadata.get("content_http_status"),
        "gaps": content_gaps(item, data_dir),
        "input": metadata.get("content_input"),
        "content_path": item.get("content_path"),
        "blocks_path": metadata.get("content_blocks_path"),
    }


def _retain_better_content(
    item: dict[str, Any], previous: dict[str, Any], data_dir: Path,
) -> None:
    """处理：回退失败或未减少缺口时恢复已经保存的正文证据。
    输入：当前尝试与此前条目的独立快照；比较文件有效性和显式结构缺口。
    输出：就地保留较可用的条目，失败尝试由流水线另行记录。
    """
    # 同 URL 已更新时，新取得的部分正文也优先于旧版完整正文。
    if ((previous.get("metadata") or {}).get("content_needs_refresh")
            and has_local_content(item, data_dir)):
        return
    # Feed 仅是源提供的片段；网页取得更多正文时，不能因结构缺口相同而退回短片段。
    if ((previous.get("metadata") or {}).get("content_acquisition") == "feed"
            and has_local_content(item, data_dir)
            and item.get("content_characters", 0) > previous.get("content_characters", 0)):
        return
    if has_local_content(previous, data_dir) and (
        not has_local_content(item, data_dir)
        or len(content_gaps(item, data_dir)) >= len(content_gaps(previous, data_dir))
    ):
        item.clear()
        item.update(previous)


def extract_content(
    index_path: Path,
    config: AppConfig,
    data_dir: Path,
    selected_ids: list[str],
    max_items: int | None,
    headed: bool,
    profile_dir: Path | None = None,
    browser_channel: str | None = None,
    checkpoint_path: Path | None = None,
) -> Path:
    """处理：按选中条目和全文预算复用已有正文，再执行 HTTP 与浏览器分层提取。
    输入：
    - ``index_path``：版本化来源索引 JSON 路径；包含根级规范 items 和来源采集状态。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``selected_ids``：调用方按重要性排序选中的条目 ID；正文阶段只处理这些授权条目。
    - ``max_items``：本步骤允许处理或返回的最大条目数；同时受全局预算限制。
    - ``headed``：是否显示真实浏览器窗口；人工登录或验证场景需要开启。
    - ``profile_dir``：持久化浏览器 Profile 目录；保存用户已授权的浏览器会话。
    - ``browser_channel``：Playwright 浏览器通道名称；为空时使用配置或默认 Chromium。
    - ``checkpoint_path``：运行专属恢复记录；绑定输入索引与选中条目，复用已经完成的提取。
    输出：指向“按选中条目和全文预算复用已有正文，
      再执行 HTTP 与浏览器分层提取”所生成、定位或确认产物的本地路径。
    """
    payload = read_json(index_path)
    if not isinstance(payload, dict):
        raise ValueError("Index must be a JSON object")
    items = payload.get("items", [])
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1")
    effective_limit = min(
        max_items if max_items is not None else config.budget.max_fulltext_per_run,
        config.budget.max_fulltext_per_run,
    )
    targets = _ordered_targets(items, selected_ids, effective_limit)
    if not targets:
        raise ValueError("No selected item IDs were found in the index")
    binding = {
        "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "selected_ids": [item["item_id"] for item in targets],
    }
    if checkpoint_path is not None:
        checkpoint_path = require_data_root_path(checkpoint_path, data_dir, "Content checkpoint")
        if checkpoint_path.is_file():
            saved = read_json(checkpoint_path)
            if not isinstance(saved, dict) or saved.get("binding") != binding:
                raise ValueError("Content checkpoint does not match the input index and selection")
            return _commit_extraction_checkpoint(saved, data_dir)
    profile = resolve_profile_dir(config, profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    channel = resolve_browser_channel(config, browser_channel)
    content_metrics = asyncio.run(
        _extract_pipeline(
            targets,
            config,
            data_dir,
            headed,
            profile,
            channel,
        )
    )
    synchronize_nested_items(payload)
    payload["content_updated_at"] = now_iso(config.timezone)
    payload["content_metrics"] = content_metrics
    payload["derived_from"] = str(index_path.resolve())
    date = str(payload.get("date"))
    edition = str(payload.get("edition"))
    index_dir = data_dir / "indexes" / date
    revision = next_revision(index_dir, edition)
    payload["revision"] = revision
    payload["index_id"] = f"index-{date}-{edition}-r{revision}"
    output = index_dir / f"{edition}-r{revision}.json"
    if checkpoint_path is not None:
        # 先保存完整提取结果；索引或上下文提交失败后无需重新访问来源。
        saved = {"binding": binding, "output_path": str(output.resolve()), "payload": payload}
        write_immutable_json(checkpoint_path, saved)
        return _commit_extraction_checkpoint(saved, data_dir)
    # 修订产物不可覆盖；latest.json 只是可重建的便利指针。
    write_immutable_json(output, payload)
    write_json(data_dir / "indexes" / "latest.json", payload)
    return output


def _commit_extraction_checkpoint(saved: dict[str, Any], data_dir: Path) -> Path:
    """处理：从已绑定检查点提交不可变索引，或核对上次已完成的同一提交。
    输入：提取完成后保存的索引对象、目标路径和当前数据根。
    输出：同一索引修订的路径；目标冲突时拒绝覆盖，latest 保持可重建。
    """
    output = require_data_root_path(Path(saved["output_path"]), data_dir, "Enriched index")
    payload = saved["payload"]
    if not isinstance(payload, dict):
        raise ValueError("Content checkpoint payload must be an object")
    if output.exists():
        if read_json(output) != payload:
            raise ValueError("Enriched index conflicts with the content checkpoint")
    else:
        write_immutable_json(output, payload)
    write_json(data_dir / "indexes" / "latest.json", payload)
    return output
