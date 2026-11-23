from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .access import classify_access_text
from .config import MediaConfig
from .content_extraction import extract_document
from .content_images import article_image_candidates, publisher_image_urls
from .image_policy import (
    filter_editorial_templates,
    image_resolution_candidates,
    image_variant_groups,
    image_variant_key,
    select_image_variants,
)
from .media import (
    DownloadedImage,
    ImageDownloadError,
    _cache_failure,
    _cache_success,
    _cached_download,
    _domain_tasks,
    _download_image_batch,
    _load_image_cache,
    _write_image_cache,
    assert_public_image_url,
    download_image,
)

_MAX_PAGE_BYTES = 2 * 1024 * 1024
_ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org"}
_IMAGE_FILE_FIELDS = ("url", "resolved_url", "local_path", "sha256", "width", "height",
                      "content_type", "byte_size")


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
    if page.hostname not in _ARXIV_HOSTS:
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
        if parsed.scheme != "https" or parsed.hostname not in _ARXIV_HOSTS:
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
        soup = BeautifulSoup(b"".join(chunks), "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        access = classify_access_text(response.status_code, title, soup.get_text(" ", strip=True))
        if access["required"]:
            reason = access["matched_text"] or f"HTTP {response.status_code}"
            raise ImageDownloadError(f"article page access challenge: {reason}")
        return soup, current

    if client is not None:
        return fetch(client)
    with httpx.Client(
        timeout=config.request_timeout_seconds, follow_redirects=False, trust_env=True,
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
    selectors = ["#detailContent"] if urlsplit(current).hostname == "english.news.cn" else []
    document = extract_document(soup, selectors, expected_title=title)
    candidates = article_image_candidates(document, title, current)
    candidates.extend({
        "url": image_url, "provenance": "page_metadata", "purpose": "publisher_selected",
        "caption": "", "position": -1, "variant": variant,
    } for variant, image_url in enumerate(publisher_image_urls(soup, current)))
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
    news: list[dict], data_dir: Path, config: MediaConfig, *, refresh: bool = False,
) -> tuple[list[dict], dict]:
    """处理：为日报入选新闻补抓发布页高清图片并复用媒体缓存。
    输入：候选新闻、正文阶段的发布页图片、数据根和媒体配置；显式刷新重新读取网页。
    输出：图片候选合并后的新闻列表，以及抓取、复用、下载计数和失败摘要。
    """
    from .news_slides import _source_image_candidates

    enriched = [item.copy() for item in news]
    if not config.enabled:
        deduplicated = 0
        for item in enriched:
            images = item.get("images", [])
            item["images"] = select_image_variants(images, data_dir=data_dir)
            deduplicated += len(images) - len(item["images"])
        return enriched, {
            "sources_fetched": 0, "source_pages_reused": 0,
            "images_downloaded": 0, "images_reused": 0,
            "images_deduplicated": deduplicated,
            "source_failures": [], "image_failures": [],
        }
    source_rows = {}
    for item in enriched:
        for source in item.get("sources", []):
            url = str(source.get("url") or "")
            if url:
                source_rows.setdefault(url, (item, source))
    page_results: dict[str, tuple[list[dict[str, Any]], str]] = {}
    if not refresh:
        for item in enriched:
            for url, candidates in item.get("image_source_pages", {}).items():
                parsed = urlsplit(url)
                # 摘要页仍需读取同篇 arXiv HTML 全文链接。
                if (url in source_rows and candidates and not (
                        parsed.hostname in _ARXIV_HOSTS and parsed.path.startswith("/abs/")
                )):
                    page_results.setdefault(url, (candidates, url))
    source_pages_reused = len(page_results)
    source_failures: list[dict[str, str]] = []
    if len(source_rows) > source_pages_reused:
        rows = [
            (url, str(source.get("title") or item.get("title") or ""))
            for url, (item, source) in source_rows.items() if url not in page_results
        ]
        with httpx.Client(
            timeout=config.request_timeout_seconds, follow_redirects=False, trust_env=True,
            headers={"User-Agent": "SignalTrail/1.0"},
        ) as client, ThreadPoolExecutor(max_workers=config.global_concurrency) as pool:
            for url, future in _domain_tasks(
                rows, partial(_read_page, config=config, client=client), pool, config,
            ):
                try:
                    page_results[url] = future.result()
                except _ArxivFullTextFetchError as exc:
                    page_results[url] = (exc.candidates, exc.page_url)
                    source_failures.append({"url": url, "reason": str(exc)})
                except (httpx.HTTPError, ImageDownloadError, OSError, ValueError) as exc:
                    source_failures.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})

    # 用现有合并规则折叠原图、已缓存图与刚抽出的高清变体。
    all_urls: dict[str, tuple[dict[str, Any], str]] = {}
    failed_sources = {failure["url"] for failure in source_failures}
    for item in enriched:
        merged = {}
        source_urls = [str(source.get("url") or "") for source in item.get("sources", [])]
        for index, source in enumerate(item.get("sources", [])):
            source_url = str(source.get("url") or "")
            page = page_results.get(source_url)
            details = [
                {**image, "url": image.get("url") or image.get("resolved_url")}
                for image in item.get("images", [])
                if (image.get("source_url") == source_url
                    or (index == 0 and image.get("source_url") not in source_urls))
                and (image.get("url") or image.get("resolved_url"))
            ]
            if page:
                if source_url not in failed_sources:
                    confirmed = {image_variant_key(image["url"]) for image in page[0]}
                    details = [
                        image for image in details
                        if image.get("provenance") not in {"page_metadata", "article_body"}
                        or image_variant_key(image["url"]) in confirmed
                    ]
                details.extend(page[0])
            article = {
                "url": source.get("url"), "source_name": source.get("name"),
                "metadata": {"image_candidate_details": details},
            }
            for candidate in _source_image_candidates(
                article, {}, source.get("url"), preserve_variants=True,
            ):
                merged.setdefault(candidate["url"], candidate)
        candidates = []
        for candidate in filter_editorial_templates(list(merged.values())):
            for url in image_resolution_candidates(candidate["url"]):
                # 新尺寸地址只有来源元数据；像素和缓存路径必须来自该地址的实际下载。
                detail = (candidate if url == candidate["url"] else
                          {key: value for key, value in candidate.items()
                           if key not in {"width", "height", "local_path", "sha256",
                                          "byte_size", "resolved_url"}})
                candidates.append({**detail, "url": url})
        item["images"] = candidates
        source_url = source_urls[0] if source_urls else ""
        for candidate in item["images"]:
            if candidate.get("url"):
                all_urls.setdefault(
                    candidate["url"], (candidate, candidate.get("source_url") or source_url)
                )

    cache = _load_image_cache(data_dir)
    resolved: dict[str, DownloadedImage | Exception] = {}
    # 缩略图单独出现在本轮页面时，按原图身份查找先前已下载的高清版本。
    known_assets = {
        image_variant_key(url): (candidate, referer)
        for url, (candidate, referer) in all_urls.items()
    }
    for url, entry in cache["entries"].items():
        if url in all_urls or not isinstance(entry, dict) or entry.get("status") != "success":
            continue
        related = known_assets.get(image_variant_key(url))
        if related is None:
            continue
        cached = _cached_download(url, entry, data_dir, config)
        if isinstance(cached, DownloadedImage):
            candidate, referer = related
            all_urls[url] = (_attach_download({**candidate, "url": url}, cached), referer)
            resolved[url] = cached
    groups = image_variant_groups([candidate for candidate, _ in all_urls.values()])
    pending_groups = list(enumerate(groups))
    selected: dict[int, dict] = {}
    used_bytes = used_images = 0
    counted_digests: set[str] = set()
    with ExitStack() as resources:
        shared: dict[str, Any] = {}
        while pending_groups:
            download_rows = []
            retry_groups = []
            for group_id, candidates in pending_groups:
                candidate = candidates[0]
                url = candidate["url"]
                cached = (None if candidate.get("local_path") else
                          _cached_download(url, cache["entries"].get(url), data_dir, config))
                if candidate.get("local_path") or isinstance(cached, DownloadedImage):
                    if isinstance(cached, DownloadedImage):
                        resolved[url] = cached
                        candidate = _attach_download(candidate, cached)
                        digest, size = cached.sha256, cached.byte_size
                    else:
                        digest = str(candidate.get("sha256") or candidate["local_path"])
                        size = int(candidate.get("byte_size") or 0)
                    selected[group_id] = select_image_variants([candidate, *candidates[1:]])[0]
                    if digest not in counted_digests:
                        used_bytes += size
                        used_images += 1
                        counted_digests.add(digest)
                elif cached is None:
                    download_rows.append((group_id, candidates))
                else:
                    resolved[url] = cached
                    if len(candidates) > 1:
                        retry_groups.append((group_id, candidates[1:]))
            cursor = 0
            while cursor < len(download_rows):
                remaining = config.max_total_bytes - used_bytes
                available_images = config.max_images_per_report - used_images
                if remaining <= 0 or available_images <= 0:
                    break
                batch_limit = min(config.global_concurrency,
                                  len(download_rows) - cursor, available_images)
                batch = download_rows[cursor:cursor + batch_limit]
                rows = [(candidates[0]["url"], all_urls[candidates[0]["url"]][1])
                        for _, candidates in batch]
                per_image_limit = min(config.max_image_bytes, remaining // len(rows))
                if per_image_limit <= 0:
                    break
                # 每族本轮只下载最高一档，不同原图继续并发；失败族下一轮再尝试低一档。
                batch_results = _download_image_batch(
                    rows, data_dir, config, per_image_limit, download_image,
                    resources=resources, shared=shared,
                )
                for group_id, candidates in batch:
                    url = candidates[0]["url"]
                    value = batch_results.get(
                        url, ImageDownloadError("image download produced no result")
                    )
                    resolved[url] = value
                    cache["entries"][url] = (
                        _cache_success(value)
                        if isinstance(value, DownloadedImage) else _cache_failure(value, config)
                    )
                    if isinstance(value, DownloadedImage):
                        candidate = _attach_download(candidates[0], value)
                        selected[group_id] = select_image_variants([candidate, *candidates[1:]])[0]
                        if value.sha256 not in counted_digests:
                            used_bytes += value.byte_size
                            used_images += 1
                            counted_digests.add(value.sha256)
                    elif len(candidates) > 1:
                        retry_groups.append((group_id, candidates[1:]))
                _write_image_cache(data_dir, cache)
                cursor += len(batch)
            pending_groups = retry_groups
    chosen_by_url = {
        image["url"]: selected.get(group_id, group[0])
        for group_id, group in enumerate(groups) for image in group
    }

    image_failures = [
        {"url": url, "reason": f"{type(value).__name__}: {value}"}
        for url, value in resolved.items() if isinstance(value, Exception)
    ]
    downloaded_urls: set[str] = set()
    reused_urls: set[str] = set()
    deduplicated = 0
    for item in enriched:
        kept: list[dict] = []
        seen_digests: set[str] = set()
        for source_image in item.get("images", []):
            chosen = chosen_by_url.get(source_image["url"], source_image)
            candidate = chosen.copy()
            if chosen.get("source_url") != source_image.get("source_url"):
                # 共用下载后的文件，图注、署名等仍取自当前报道。
                candidate = {
                    **source_image,
                    **{key: chosen[key] for key in _IMAGE_FILE_FIELDS if key in chosen},
                }
            url = candidate["url"]
            value = resolved.get(url)
            if isinstance(value, DownloadedImage):
                candidate.update(_attach_download(candidate, value))
                (reused_urls if value.reused else downloaded_urls).add(url)
            elif isinstance(value, Exception):
                pass
            else:
                # 超预算候选保留未知尺寸，最终选择只展示已验证的图片。
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
        has_article_image = any(
            image.get("provenance") == "article_body"
            and image.get("local_path")
            for image in kept
        )
        if has_article_image:
            kept = [image for image in kept if not (
                image.get("provenance") == "page_metadata"
                and 0 < int(image.get("width") or 0) <= 128
                and 0 < int(image.get("height") or 0) <= 128
            )]
        item["images"] = select_image_variants(kept, data_dir=data_dir)
        deduplicated += len(kept) - len(item["images"])
    return enriched, {
        "sources_fetched": len(page_results) - source_pages_reused,
        "source_pages_reused": source_pages_reused, "images_downloaded": len(downloaded_urls),
        "images_reused": len(reused_urls), "images_deduplicated": deduplicated,
        "source_failures": source_failures, "image_failures": image_failures,
    }
