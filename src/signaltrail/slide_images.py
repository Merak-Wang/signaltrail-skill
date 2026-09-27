from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .config import MediaConfig
from .content_extraction import extract_document
from .content_images import article_image_candidates
from .image_policy import normalize_image_candidates
from .media import (
    DownloadedImage,
    ImageDownloadError,
    _cache_failure,
    _cache_success,
    _cached_download,
    _download_image_batch,
    _load_image_cache,
    _write_image_cache,
    assert_public_image_url,
    download_image,
)

_MAX_PAGE_BYTES = 2 * 1024 * 1024


class _ArxivFullTextFetchError(ImageDownloadError):
    """处理：保留摘要页图片并传递 arXiv 全文页访问失败。
    输入：失败说明、摘要页候选与摘要页最终 URL。
    输出：调用方可同时记录来源失败并继续合并摘要页图片。
    """

    def __init__(self, message: str, candidates: list[dict[str, Any]], page_url: str):
        """处理：在异常中保留摘要页候选和最终 URL。
        输入：全文失败说明、摘要候选和最终摘要页 URL。
        输出：调用方可记录失败并继续合并已找到的图片。
        """
        super().__init__(message)
        self.candidates = candidates
        self.page_url = page_url


def _arxiv_fulltext_link(soup: BeautifulSoup, page_url: str) -> str | None:
    """处理：从 arXiv 摘要页定位同论文的显式 HTML 全文链接。
    输入：已解析页面及最终 URL；仅接受 arXiv HTTPS 的 HTML 链接和相同论文 ID。
    输出：可信范围内的全文 URL；页面未明确提供时返回 None。
    """
    page = urlsplit(page_url)
    if page.hostname != "arxiv.org":
        return None
    match = re.fullmatch(r"/abs/(.+?)(?:v\d+)?/?", page.path)
    if not match:
        return None
    paper_id = match.group(1).rstrip("/")
    for anchor in soup.select("a[href]"):
        label = " ".join(anchor.get_text(" ", strip=True).casefold().split())
        if label not in {"html", "html (experimental)"}:
            continue
        target = urljoin(page_url, str(anchor.get("href") or ""))
        parsed = urlsplit(target)
        if parsed.scheme != "https" or parsed.hostname != "arxiv.org":
            continue
        target_match = re.fullmatch(r"/html/(.+?)(?:v\d+)?/?", parsed.path)
        if target_match and target_match.group(1).rstrip("/") == paper_id:
            return target
    return None


def fetch_article_page(
    url: str, config: MediaConfig, client: httpx.Client | None = None,
) -> tuple[BeautifulSoup, str]:
    """处理：限时读取并解析公开新闻页，供图片与发布日期提取共用。
    输入：公开文章 URL、媒体网络配置及可选共享连接池客户端；HTML最多读取 2 MiB。
    输出：解析后的页面与最终文章 URL；访问失败抛出请求或读取异常。
    """
    def fetch(session: httpx.Client) -> tuple[BeautifulSoup, str]:
        """处理：用共享客户端跟随逐跳校验的公开页面重定向并读取限长 HTML。
        输入：已配置的 HTTP 客户端；每个跳转地址都重新检查公网可访问性。
        输出：BeautifulSoup 页面与最后响应对应的 URL。
        """
        current = url
        for _ in range(config.max_redirects + 1):
            assert_public_image_url(current)
            with session.stream("GET", current) as response:
                if response.is_redirect:
                    if not response.headers.get("location"):
                        raise ImageDownloadError("article redirect has no location")
                    current = urljoin(current, response.headers["location"])
                    continue
                if response.status_code >= 400:
                    raise ImageDownloadError(f"article host returned HTTP {response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > _MAX_PAGE_BYTES:
                        raise ImageDownloadError("article HTML exceeds the 2 MiB limit")
                    chunks.append(chunk)
                break
        else:
            raise ImageDownloadError("article redirect limit was exceeded")
        return BeautifulSoup(b"".join(chunks), "html.parser"), current

    if client is not None:
        return fetch(client)
    with httpx.Client(
        timeout=config.request_timeout_seconds, follow_redirects=False, trust_env=False,
        headers={"User-Agent": "SignalTrail/1.0"},
    ) as session:
        return fetch(session)


def _read_page(
    url: str, title: str, config: MediaConfig, client: httpx.Client | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """处理：从已解析文章页提取正文图与发布者主图。
    输入：图文流来源 URL、新闻标题和媒体网络配置。
    输出：带原文图注的正文候选及页面元数据主图。
    """
    soup, current = fetch_article_page(url, config, client)
    # 正文抽取器负责选取具体正文区域并清理相关推荐等噪声；只取图片，不保存正文。
    document = extract_document(soup, [], expected_title=title)
    candidates = article_image_candidates(document, title, current)
    og = [
        node.get("content") for node in soup.select(
            'meta[property="og:image"], meta[name="og:image"], '
            'meta[name="twitter:image"], meta[property="twitter:image"]'
        ) if node.get("content")
    ]
    # 主图由发布者显式声明，正文配图仍由具体正文节点提供，不将头像和推荐图混入。
    for raw in og:
        for variant, image_url in enumerate(normalize_image_candidates([raw], current)):
            candidates.append({
                "url": image_url, "provenance": "page_metadata", "purpose": "publisher_selected",
                "caption": "", "position": -1, "variant": variant,
            })
    fulltext_url = _arxiv_fulltext_link(soup, current)
    if fulltext_url:
        try:
            fulltext, fulltext_current = fetch_article_page(fulltext_url, config, client)
        except (httpx.HTTPError, ImageDownloadError, OSError, ValueError) as exc:
            raise _ArxivFullTextFetchError(
                f"arXiv HTML full text failed: {type(exc).__name__}: {exc}",
                candidates, current,
            ) from exc
        fulltext_document = extract_document(fulltext, [], expected_title=title)
        candidates.extend(article_image_candidates(fulltext_document, title, fulltext_current))
    return candidates, current


def _attach_download(candidate: dict[str, Any], downloaded: DownloadedImage) -> dict[str, Any]:
    """处理：把下载器实测的本地文件信息写回候选。
    输入：HTML图片候选及媒体下载结果。
    输出：保留来源图注并补齐本地路径、哈希和实际像素尺寸的图片记录。
    """
    return {
        **candidate, "resolved_url": downloaded.resolved_url,
        "local_path": downloaded.local_path, "sha256": downloaded.sha256,
        "width": downloaded.width, "height": downloaded.height,
        "content_type": downloaded.content_type, "byte_size": downloaded.byte_size,
    }


def enrich_slide_images(
    news: list[dict], data_dir: Path, config: MediaConfig,
) -> tuple[list[dict], dict]:
    """处理：为日报当天入选新闻补抓发布页高清图片并复用媒体缓存。
    输入：候选新闻（event_id/title/sources/images）、数据根和媒体配置；不改动正文或事实。
    输出：图片候选合并后的新闻列表，以及抓取/下载计数和来源、图片失败摘要。
    """
    from copy import deepcopy

    from .news_slides import _image_identity, _news_images

    enriched = deepcopy(news)
    if not config.enabled:
        return enriched, {
            "sources_fetched": 0, "images_downloaded": 0, "images_reused": 0,
            "source_failures": [], "image_failures": [],
        }
    source_rows = {}
    for item in enriched:
        for source in item.get("sources", []):
            url = str(source.get("url") or "")
            if url:
                source_rows.setdefault(url, (item, source))
    page_results: dict[str, tuple[list[dict[str, Any]], str]] = {}
    source_failures: list[dict[str, str]] = []
    if source_rows:
        domain_queues: dict[str, list[tuple[str, dict]]] = {}
        for url, (item, _source) in source_rows.items():
            domain = (urlsplit(url).hostname or "unknown").casefold()
            domain_queues.setdefault(domain, []).append((url, item))
        domains = list(domain_queues)
        domain_active = dict.fromkeys(domains, 0)
        domain_cursor = dict.fromkeys(domains, 0)
        domain_index = 0
        with httpx.Client(
            timeout=config.request_timeout_seconds, follow_redirects=False, trust_env=False,
            headers={"User-Agent": "SignalTrail/1.0"},
        ) as client, ThreadPoolExecutor(max_workers=config.global_concurrency) as pool:
            def submit_ready(pending: dict) -> None:
                """处理：从有空位的域名队列提交请求，保持线程只运行可执行任务。
                输入：未完成 Future 映射及各域待抓文章；域内活动数受媒体配置限制。
                输出：补足全局并发槽位，不把等待同域限额的任务塞进线程池。
                """
                nonlocal domain_index
                while len(pending) < config.global_concurrency:
                    submitted = False
                    for _ in domains:
                        domain = domains[domain_index]
                        domain_index = (domain_index + 1) % len(domains)
                        cursor = domain_cursor[domain]
                        queue = domain_queues[domain]
                        if (cursor < len(queue)
                                and domain_active[domain] < config.per_domain_concurrency):
                            url, item = queue[cursor]
                            domain_cursor[domain] = cursor + 1
                            domain_active[domain] += 1
                            future = pool.submit(read_source, url, item)
                            pending[future] = (url, domain)
                            submitted = True
                            break
                    if not submitted:
                        break

            def read_source(url: str, item: dict) -> tuple[list[dict[str, Any]], str]:
                """处理：通过本轮共享 HTTP 客户端读取一篇来源文章的图片。
                输入：来源 URL、标题与共享客户端；任务提交前已取得对应域名并发名额。
                输出：正文图片候选与重定向后的文章 URL，供同一新闻合并使用。
                """
                return _read_page(url, str(item.get("title") or ""), config, client)

            pending: dict = {}
            submit_ready(pending)
            while pending:
                future = next(as_completed(tuple(pending)))
                url, domain = pending.pop(future)
                domain_active[domain] -= 1
                try:
                    page_results[url] = future.result()
                except _ArxivFullTextFetchError as exc:
                    page_results[url] = (exc.candidates, exc.page_url)
                    source_failures.append({"url": url, "reason": str(exc)})
                except (httpx.HTTPError, ImageDownloadError, OSError, ValueError) as exc:
                    source_failures.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})
                submit_ready(pending)

    # 用现有合并规则折叠原图、已缓存图与刚抽出的高清变体。
    all_urls: dict[str, tuple[dict[str, Any], str]] = {}
    fallbacks: dict[tuple[str, tuple], list[dict[str, Any]]] = {}
    for item in enriched:
        refs, indexed, briefs = [], {}, {}
        source_urls = [str(source.get("url") or "") for source in item.get("sources", [])]
        for image in item.get("images", []):
            if image.get("url") and image.get("local_path"):
                key = (item["event_id"], _image_identity(str(image["url"])))
                fallbacks.setdefault(key, []).append(image.copy())
        for index, source in enumerate(item.get("sources", [])):
            item_id = f"{item['event_id']}:{index}"
            source_url = str(source.get("url") or "")
            refs.append({"item_id": item_id, "url": source.get("url", ""),
                         "title": source.get("title", ""), "access": source.get("access")})
            page = page_results.get(source_url)
            details = [
                {**image, "url": image.get("url") or image.get("resolved_url")}
                for image in item.get("images", [])
                if (image.get("source_url") == source_url
                    or (index == 0 and image.get("source_url") not in source_urls))
                and (image.get("url") or image.get("resolved_url"))
            ]
            if page:
                details.extend(page[0])
            indexed[item_id] = {
                "url": source.get("url"), "source_name": source.get("name"),
                "metadata": {"image_candidate_details": details},
            }
            briefs[item_id] = {"primary_source": {"name": source.get("name", "")}}
        event = {"source_refs": refs}
        merged = _news_images(event, briefs, indexed)
        item["images"] = merged
        source_url = source_urls[0] if source_urls else ""
        for candidate in item["images"]:
            if candidate.get("url"):
                all_urls.setdefault(
                    candidate["url"], (candidate, candidate.get("source_url") or source_url)
                )

    cache = _load_image_cache(data_dir)
    resolved: dict[str, DownloadedImage | Exception] = {}
    download_rows = []
    used_bytes = 0
    used_images = 0
    counted_digests: set[str] = set()
    for url, (_candidate, referer) in all_urls.items():
        if _candidate.get("local_path"):
            digest = str(_candidate.get("sha256") or _candidate.get("local_path"))
            if digest not in counted_digests:
                used_bytes += int(_candidate.get("byte_size") or 0)
                counted_digests.add(digest)
                used_images += 1
            continue
        cached = _cached_download(url, cache["entries"].get(url), data_dir, config)
        if isinstance(cached, DownloadedImage):
            resolved[url] = cached
            if cached.sha256 not in counted_digests:
                used_bytes += cached.byte_size
                counted_digests.add(cached.sha256)
                used_images += 1
        elif cached is None:
            download_rows.append((url, referer))
        else:
            resolved[url] = cached
    cursor = 0
    with ExitStack() as resources:
        shared: dict[str, Any] = {}
        while cursor < len(download_rows):
            remaining = config.max_total_bytes - used_bytes
            available_images = config.max_images_per_report - used_images
            if remaining <= 0 or available_images <= 0:
                break
            available = len(download_rows) - cursor
            batch_limit = min(config.global_concurrency, available, available_images)
            # 每张候选按本批剩余额度均分，保证并行响应总量不越过报告预算。
            rows = download_rows[cursor:cursor + batch_limit]
            per_image_limit = min(config.max_image_bytes, remaining // len(rows))
            if per_image_limit <= 0:
                break
            batch_results = _download_image_batch(
                rows, data_dir, config, per_image_limit, download_image,
                resources=resources, shared=shared,
            )
            for url, _referer in rows:
                value = batch_results.get(
                    url, ImageDownloadError("image download produced no result")
                )
                resolved[url] = value
                cache["entries"][url] = (
                    _cache_success(value)
                    if isinstance(value, DownloadedImage) else _cache_failure(value, config)
                )
                if isinstance(value, DownloadedImage) and value.sha256 not in counted_digests:
                    used_bytes += value.byte_size
                    counted_digests.add(value.sha256)
                    used_images += 1
            _write_image_cache(data_dir, cache)
            cursor += len(rows)

    image_failures: list[dict[str, str]] = []
    downloaded_urls: set[str] = set()
    reused_urls: set[str] = set()
    failed_urls: set[str] = set()
    deduplicated = 0
    for item in enriched:
        kept: list[dict] = []
        seen_digests: set[str] = set()
        for candidate in item.get("images", []):
            url = candidate["url"]
            value = resolved.get(url)
            if isinstance(value, Exception):
                if url not in failed_urls:
                    image_failures.append({
                        "url": url, "reason": f"{type(value).__name__}: {value}"
                    })
                    failed_urls.add(url)
                alternatives = fallbacks.get(
                    (item["event_id"], _image_identity(url)), []
                )
                if alternatives:
                    # 高清变体下载失败时，以已缓存的同一原图变体继续展示。
                    candidate = max(
                        alternatives,
                        key=lambda image: int(image.get("width") or 0)
                        * int(image.get("height") or 0),
                    )
                    url = candidate["url"]
                    value = resolved.get(url)
            if isinstance(value, DownloadedImage):
                candidate.update(_attach_download(candidate, value))
                (reused_urls if value.reused else downloaded_urls).add(url)
            elif isinstance(value, Exception):
                pass
            else:
                # 超预算候选仍留在图集中；尺寸未知，由渲染器保留远端链接。
                candidate.setdefault("width", None)
                candidate.setdefault("height", None)
            # 同一新闻内不同 URL 可能返回同一图片内容；按实际哈希保留先出现的那张。
            digest = str(candidate.get("sha256") or "")
            if digest and digest in seen_digests:
                deduplicated += 1
                continue
            if digest:
                seen_digests.add(digest)
            kept.append(candidate)
        item["images"] = kept
    return enriched, {
        "sources_fetched": len(page_results), "images_downloaded": len(downloaded_urls),
        "images_reused": len(reused_urls), "images_deduplicated": deduplicated,
        "source_failures": source_failures, "image_failures": image_failures,
    }
