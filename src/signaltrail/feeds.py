from __future__ import annotations

import hashlib
import math
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .access import classify_access_text
from .adapters import is_eligible
from .article_time import normalize_time
from .clustering import cosine_similarity, lexical_vector
from .config import SourceConfig
from .feed_content import entry_content, save_feed_content, xml_context
from .image_policy import normalize_image_candidates
from .models import ArticleItem, SourceStatus, order_source_items
from .utils import canonicalize_url, clean_title, item_id, read_json, write_json

_ARTICLE_FIELDS = {field.name for field in fields(ArticleItem)}
_FEED_ROOTS = {"feed", "rss", "rdf", "rdf:rdf"}
_SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
_IMAGE_EXTENSIONS = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")


def _remove_repeated_feed_templates(items: list[ArticleItem], records: dict[str, dict]) -> None:
    """处理：从同源不同新闻中剔除反复出现且无图注的固定配图。
    输入：单次Feed解析的文章和正文图片候选。
    输出：正文候选与首图同步更新；相近标题的同事件复用图保留。
    """
    occurrences = defaultdict(list)
    for item in items:
        for image in records.get(item.item_id, {}).get("images", []):
            occurrences[image["url"]].append((item, image))
    rejected = set()
    for url, rows in occurrences.items():
        if len({item.canonical_url for item, _ in rows}) < max(3, math.ceil(len(items) * 0.4)):
            continue
        if any(image.get("alt") or image.get("caption") for _, image in rows):
            continue
        titles = [lexical_vector(item.title) for item, _ in rows]
        if any(cosine_similarity(titles[0], title) < 0.35 for title in titles[1:]):
            rejected.add(url)
    for item in items:
        record = records.get(item.item_id)
        if record:
            record["images"] = [image for image in record["images"] if image["url"] not in rejected]
        candidates = [
            url
            for url in item.metadata.get("image_candidates", [item.image_url])
            if url and url not in rejected
        ]
        item.image_url = candidates[0] if candidates else None
        item.metadata["image_candidates"] = candidates


@dataclass(slots=True)
class FeedFetchResult:
    """一次 Feed 刷新的状态与规范文章，含下一次刷新时间和条件请求所需的缓存标识。
    过期结果单独标记，供监控器在刷新失败时降级使用。
    """

    source_id: str
    source_name: str
    feed_url: str
    status: str
    checked_at: str
    items: list[ArticleItem]
    http_status: int | None = None
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    cache_state: str = "miss"
    stale: bool = False
    latency_ms: int = 0
    next_refresh_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """处理：序列化 Feed 回执，每篇文章只展开一次。
        输入：本次抓取的来源状态、缓存观测和文章。
        输出：监控快照使用的回执字段、规范文章和文章数。
        """
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result["items"] = [item.to_dict() for item in self.items]
        result["items_count"] = len(self.items)
        return result


def _local_name(tag: str) -> str:
    """去除 XML 命名空间并返回元素的本地标签名。
    输入：``tag``：XML 元素的完整标签名；函数会移除命名空间前缀。
    """
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1].lower()


def _direct_elements(node: ET.Element, *names: str) -> list[ET.Element]:
    """处理：返回当前 XML 元素的指定直接子元素。
    输入：
    - ``node``：Feed 解析器当前处理的 RSS/Atom XML 元素。
    - ``*names``：允许匹配的直接子元素本地名称；按传入顺序查找。
    输出：按“返回当前 XML 元素的指定直接子元素”规则得到的 ``ET.Element`` 列表；
      列表顺序表达配置优先级、业务排名或稳定扫描顺序。
    """
    wanted = {name.lower() for name in names}
    return [child for child in list(node) if _local_name(child.tag) in wanted]


def _element_text(element: ET.Element | None) -> str:
    """合并 XML 元素及其后代的可见文本。
    输入：``element``：可能为空的 RSS/Atom XML 元素；读取其自身及后代可见文本。
    """
    if element is None:
        return ""
    return clean_title(" ".join(element.itertext()))


def _direct_text(node: ET.Element, *names: str) -> str:
    """读取指定直接子元素中的首个非空文本。
    输入：
    - ``node``：Feed 解析器当前处理的 RSS/Atom XML 元素。
    - ``*names``：允许匹配的直接子元素本地名称；按传入顺序查找。
    """
    for child in _direct_elements(node, *names):
        value = _element_text(child)
        if value:
            return value
    return ""


def _parse_datetime(value: str, timezone: str) -> datetime | None:
    """把 Feed 日期文本解析并统一到配置时区。
    输入：待解析的值、用于解释本地日期的 IANA 时区。
    """
    normalized = normalize_time(clean_title(value), timezone)
    if normalized is None:
        return None
    parsed = datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=parsed.tzinfo or ZoneInfo(timezone))


def _entry_link(node: ET.Element, feed_url: str) -> str:
    """从 Atom/RSS 条目中选择规范文章链接。
    输入：用于抓取与缓存的 Feed URL。
    - ``node``：Feed 解析器当前处理的 RSS/Atom XML 元素。
    """
    links = _direct_elements(node, "link")
    for link in links:
        href = clean_title(str(link.attrib.get("href") or ""))
        rel = clean_title(str(link.attrib.get("rel") or "alternate")).lower()
        if href and rel in {"", "alternate"}:
            base = link.get("{http://www.w3.org/XML/1998/namespace}base", "")
            return urljoin(urljoin(feed_url, base), href)
    for link in links:
        value = _element_text(link)
        if value:
            return urljoin(feed_url, value)
    guid = _direct_text(node, "guid", "id")
    return guid if guid.startswith(("http://", "https://")) else ""


def _entry_image_candidates(
    node: ET.Element,
    contexts: dict[ET.Element, tuple[str, str]],
    article_url: str,
    feed_url: str,
) -> list[str]:
    """处理：读取 Feed 媒体附件，按节点继承的 base 解析图片地址。
    输入：条目 XML、继承上下文、文章与订阅地址；正文配图由内容结构器处理。
    输出：按来源顺序去重的有效媒体图片地址。
    """
    candidates = []
    for child in node.iter():
        name = _local_name(child.tag)
        url = str(child.get("url") or child.get("href") or "").strip()
        media_type = child.get("type", "").lower()
        medium = child.get("medium", "").lower()
        if url and (
            name in {"thumbnail", "image"}
            or (
                name in {"content", "enclosure"}
                and (
                    media_type.startswith("image/")
                    or medium == "image"
                    or url.lower().split("?", 1)[0].endswith(_IMAGE_EXTENSIONS)
                )
            )
        ):
            base = urljoin(feed_url, contexts[child][0]) if contexts[child][0] else article_url
            candidates.append(urljoin(base, url))
    return normalize_image_candidates(candidates, article_url)


def _provider(node: ET.Element) -> tuple[str | None, str | None]:
    """从 Feed 条目提取原始出版方名称和链接。缺少的字段保留为空。"""
    for child in _direct_elements(node, "source"):
        name = _direct_text(child, "title") or _element_text(child)
        url = str(child.attrib.get("url") or "").strip()
        if not url:
            link = next(iter(_direct_elements(child, "link")), None)
            url = str(link.attrib.get("href") or "") if link is not None else ""
        return name or None, url or None
    return None, None


def looks_like_feed(content: bytes | str, content_type: str = "") -> bool:
    """识别 RSS、Atom 与声明新闻命名空间的出版方新闻目录。
    输入：
    - ``content``：待编码、解析或写入的原始内容；边界和可信级别由当前函数说明。
    - ``content_type``：HTTP 内容类型或待上传文件 MIME 类型；用于解析、校验和响应头。
    """
    if isinstance(content, bytes):
        prefix = content[:4096].decode("utf-8", errors="replace")
    else:
        prefix = content[:4096]
    normalized = prefix.lstrip("\ufeff \t\r\n").lower()
    if normalized.startswith(("<!doctype html", "<html")):
        return False
    if any(marker in normalized for marker in ("<rss", "<feed", "<rdf:rdf")):
        return True
    if "<urlset" in normalized and _NEWS[1:-1] in normalized:
        return True
    return any(
        marker in content_type.lower() for marker in ("application/rss+xml", "application/atom+xml")
    )


def parse_feed_document(
    content: bytes | str,
    source: SourceConfig,
    feed_url: str,
    collected_at: str,
    timezone: str,
    *,
    max_items: int,
    data_dir: Path | None = None,
) -> list[ArticleItem]:
    """处理：从 RSS、Atom 或新闻站点地图提取原文链接、标题和原发时间。
    输入：用于抓取与缓存的 Feed URL、用于解释本地日期的 IANA 时区、本阶段条目上限。
    - ``content``：RSS/Atom HTTP 响应的原始 XML 字节或文本；按不可信输入和大小边界解析。
    - ``source``：当前 Feed 所属来源配置；提供来源身份、栏目、过滤规则和条目上限。
    - ``collected_at``：页面或 Feed 的采集时间；用于状态记录和时间回退，不冒充发布时间。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    raw = content.encode("utf-8") if isinstance(content, str) else content
    root = ET.fromstring(raw)
    news_map = root.tag == f"{_SITEMAP}urlset"
    if not news_map and _local_name(root.tag) not in _FEED_ROOTS:
        raise ValueError(f"Unsupported feed root element: {_local_name(root.tag)!r}")
    contexts = xml_context(root)
    entry_nodes = (root.iterfind(f"{_SITEMAP}url") if news_map else
                   (node for node in root.iter() if _local_name(node.tag) in {"entry", "item"}))
    observed = _parse_datetime(collected_at, timezone) or datetime.now(ZoneInfo(timezone))
    future_cutoff = observed + timedelta(hours=1)

    items: list[ArticleItem] = []
    seen: set[str] = set()
    content_records: dict[str, dict[str, Any]] = {}
    for node in entry_nodes:
        if news_map:
            news = node.find(f"{_NEWS}news")
            if news is None:
                continue
            title = clean_title(news.findtext(f"{_NEWS}title", ""))
            url = _direct_text(node, "loc")
            published_text = clean_title(news.findtext(f"{_NEWS}publication_date", ""))
            if not published_text:
                continue
        else:
            title = _direct_text(node, "title")
            url = _entry_link(node, urljoin(feed_url, contexts[node][0]))
            published_text = next((value for name in ("pubdate", "published", "issued", "date")
                                   if (value := _direct_text(node, name))), "")
        if not is_eligible(source, title, url):
            continue
        published_value = normalize_time(published_text, timezone)
        published = _parse_datetime(published_text, timezone)
        if published is not None and published > future_cutoff:
            continue
        canonical = canonicalize_url(url)
        if canonical in seen:
            continue
        content_record = entry_content(node, contexts, url, feed_url)
        filing_date: dict[str, str] = {}
        if (source.id == "sec_edgar_latest" and content_record
                and urlsplit(feed_url).hostname == "www.sec.gov"):
            # EDGAR 的 Filed 是纽约记账日；原发时间须另有受理时刻的证据。
            filing_day = re.match(r"Filed:\s*(\d{4}-\d{2}-\d{2})\b", content_record["text"])
            if filing_day:
                filing_date["sec_filing_date"] = filing_day[1]
        image_candidates = normalize_image_candidates(
            [
                *(image["url"] for image in (content_record or {}).get("images", [])),
                *_entry_image_candidates(node, contexts, url, feed_url),
            ],
            url,
        )
        provider_name, provider_url = _provider(node)
        article = ArticleItem(
            item_id=item_id(source.id, canonical),
            source_id=source.id,
            source_name=source.name,
            title=title,
            url=url,
            canonical_url=canonical,
            discovered_at=collected_at,
            module=source.module,
            category=source.category,
            description=clean_title(content_record["text"])[:600] if content_record else "",
            published_at=published_value,
            original_provider=provider_name,
            image_url=image_candidates[0] if image_candidates else None,
            metadata={
                "role": source.role,
                "tier": source.tier,
                "bundle": source.bundle,
                "language": source.language,
                "region": source.region,
                **source.origin_metadata,
                **filing_date,
                "acquisition_method": "feed",
                "feed_url": feed_url,
                **({"feed_format": "news_sitemap"} if news_map else {}),
                "publication_time_missing": published is None,
                "published_raw": published_text,
                "published_precision": (
                    "date" if published_value and len(published_value) == 10
                    else "datetime" if published_value else None
                ),
                "updated_at": normalize_time(_direct_text(node, "updated", "modified"), timezone),
                **({"feed_navigation_only": True}
                   if (content_record or {}).get("quality", {}).get("navigation_only") else {}),
                **({"original_provider_url": provider_url} if provider_url else {}),
                **({"image_candidates": image_candidates} if len(image_candidates) > 1 else {}),
            },
        )
        if content_record and content_record["text"]:
            content_record["language"] = content_record["language"] or source.language
            content_records[article.item_id] = content_record
        seen.add(canonical)
        items.append(article)
        if (not source.collect_all_items and source.item_order != "published_at"
                and len(items) >= max_items):
            break
    for source_rank, item in enumerate(items, start=1):
        item.metadata["source_rank"] = source_rank
    selected = order_source_items(items, source.item_order)
    if not source.collect_all_items:
        selected = selected[:max_items]
    _remove_repeated_feed_templates(selected, content_records)
    if data_dir is not None:
        for article in selected:
            if article.item_id in content_records:
                article.metadata.update(
                    save_feed_content(
                        content_records[article.item_id],
                        data_dir,
                        source.id,
                        article.item_id,
                        article.url,
                        feed_url,
                    )
                )
    return selected


def discover_feed_urls(html: str, base_url: str) -> list[str]:
    """在不执行页面脚本的前提下发现声明的 RSS/Atom 地址。
    输入：
    - ``html``：HTTP 或浏览器取得的不可信 HTML 文本；只执行静态解析。
    - ``base_url``：解析相对链接时使用的最终页面或 Feed 基准 URL。
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    for link in soup.select("link[href], a[href]"):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        media_type = str(link.get("type") or "").lower()
        rel_value = link.get("rel") or []
        rel = " ".join(rel_value if isinstance(rel_value, list) else [str(rel_value)]).lower()
        resolved = urljoin(base_url, href)
        parsed = urlsplit(resolved)
        path = parsed.path.lower().rstrip("/")
        anchor_hint = any(
            marker in link.get_text(" ", strip=True).lower() for marker in ("rss", "atom", "feed")
        )
        declared = "alternate" in rel and media_type in {
            "application/rss+xml",
            "application/atom+xml",
        }
        endpoint_shape = (
            path.endswith(("/feed", "/rss", ".atom", ".rss", ".xml"))
            or "/rss/" in path
            or parsed.netloc.lower().startswith("rss.")
        )
        heuristic = endpoint_shape and (link.name == "link" or anchor_hint)
        if not (declared or heuristic):
            continue
        if resolved.startswith(("http://", "https://")):
            candidates.append(resolved)
    return list(dict.fromkeys(candidates))[:8]


def article_from_dict(payload: dict[str, Any]) -> ArticleItem:
    """从缓存字典恢复包含来源身份、正文状态和元数据的文章对象。
    输入：``payload``：上游传入的结构化对象；函数只读取处理说明列出的受支持字段。
    输出：可进入规范来源索引的文章条目；包含稳定 ID、来源身份、规范 URL、时间和可用元数据。
    """
    article = ArticleItem(
        **{key: value for key, value in payload.items() if key in _ARTICLE_FIELDS}
    )
    candidates = normalize_image_candidates(
        [
            article.image_url,
            *article.metadata.get("image_candidates", []),
        ],
        article.url,
    )
    article.image_url = candidates[0] if candidates else None
    if "image_candidates" in article.metadata:
        article.metadata["image_candidates"] = candidates
    return article


def _cache_path(data_dir: Path, feed_url: str) -> Path:
    """根据 Feed URL 哈希生成隔离且稳定的缓存文件路径。
    输入：本次运行的数据根、用于抓取与缓存的 Feed URL。
    """
    digest = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()
    return data_dir / "monitor" / "feed-cache" / f"{digest}.json"


def _load_cache(path: Path) -> dict[str, Any]:
    """处理：读取单个 Feed 的本地缓存。
    输入：由 Feed URL 确定的缓存路径。
    输出：缓存映射；文件缺失或不是对象时为空。
    """
    if not path.exists():
        return {}
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {}


def _cached_items(cache: dict[str, Any]) -> list[ArticleItem]:
    """从有效 Feed 缓存恢复文章条目列表。
    输入：``cache``：本地持久化缓存对象；包含状态、时间、响应元数据和可复用结果。
    输出：可写入规范来源索引的文章条目列表；
      每项包含稳定 ID、来源身份、规范 URL、时间和可用元数据，
      并保持当前处理定义的筛选与排序语义。
    """
    rows = cache.get("items", [])
    return [article_from_dict(row) for row in rows if isinstance(row, dict) and row.get("item_id")]


def _retry_after_seconds(value: str | None) -> int | None:
    """把 Retry-After 响应头解析为有界等待秒数。"""
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0, math.ceil((retry_at - datetime.now(UTC)).total_seconds()))


def _next_refresh(
    checked_at: datetime,
    interval_minutes: int,
    failures: int,
    retry_after: int | None = None,
) -> str:
    """根据最近检查时间和刷新间隔计算下次刷新时间。
    输入：
    - ``checked_at``：本次来源或缓存检查时间；用于刷新计划和健康状态。
    - ``interval_minutes``：正常成功后到下一次允许刷新之间的分钟数。
    - ``failures``：该 Feed 连续失败次数；用于指数退避且设有 24 小时上限。
    - ``retry_after``：服务端 Retry-After 解析出的秒数；存在时优先于指数退避。
    """
    if retry_after is not None:
        delay = max(60, retry_after)
    else:
        delay = interval_minutes * 60 * (2 ** min(failures, 5))
    delay = min(delay, 24 * 60 * 60)
    return (checked_at + timedelta(seconds=delay)).isoformat(timespec="seconds")


async def fetch_feed(
    client: httpx.AsyncClient,
    source: SourceConfig,
    feed_url: str,
    data_dir: Path,
    timezone: str,
    *,
    max_bytes: int,
    max_items: int,
    refresh_interval_minutes: int,
    force: bool = False,
) -> FeedFetchResult:
    """处理：使用条件请求、缓存和刷新策略抓取并解析单个 RSS/Atom Feed。
    输入：带入口与筛选规则的来源配置、用于抓取与缓存的 Feed URL、
      本次运行的数据根、用于解释本地日期的 IANA 时区、本阶段条目上限。
    - ``client``：已配置超时、重定向和连接池策略的 HTTP 客户端。
    - ``max_bytes``：允许读取或下载的最大字节数；达到上限后停止或报错。
    - ``refresh_interval_minutes``：来源或 Feed 的最小刷新间隔；未到期时可复用缓存。
    - ``force``：是否忽略正常缓存或重复保护并显式重新执行允许的步骤。
    输出：单个 Feed 的抓取结果；包含访问状态、缓存信息、错误、刷新时间和规范文章条目。
    """
    cache_path = _cache_path(data_dir, feed_url)
    cache = _load_cache(cache_path)
    scope_changed = source.collect_all_items and not cache.get("collect_all_items")
    checked_at = datetime.now(ZoneInfo(timezone))
    checked_iso = checked_at.isoformat(timespec="seconds")

    def result(
        status: str, items: list[ArticleItem], cache_state: str, **details: Any,
    ) -> FeedFetchResult:
        """处理：按已判定的状态组装统一抓取结果。
        输入：文章、状态、缓存命中类型及可选响应观测。
        输出：供采集和监控使用的 Feed 结果。
        """
        return FeedFetchResult(source.id, source.name, feed_url, status, checked_iso, items,
                               cache_state=cache_state, **details)

    validators = {key: cache.get(key) for key in ("etag", "last_modified")}
    next_refresh_raw = str(cache.get("next_refresh_at") or "")
    if cache and not force and not scope_changed and next_refresh_raw:
        next_refresh = _parse_datetime(next_refresh_raw, timezone)
        if next_refresh is not None and checked_at < next_refresh:
            cached = _cached_items(cache)
            return result(
                str(cache.get("status", SourceStatus.NO_ITEMS)), cached, "fresh",
                http_status=cache.get("http_status"), error=cache.get("error"),
                stale=bool(cached) and bool(cache.get("consecutive_failures")),
                next_refresh_at=next_refresh_raw, **validators,
            )

    headers = {
        "Accept": (
            "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.1"
        ),
        "User-Agent": "DailyIntelligenceMonitor/2.0 (+local feed reader)",
    }
    if cache.get("etag") and not scope_changed:
        headers["If-None-Match"] = str(cache["etag"])
    if cache.get("last_modified") and not scope_changed:
        headers["If-Modified-Since"] = str(cache["last_modified"])
    started = time.perf_counter()
    response: httpx.Response | None = None
    try:
        async with client.stream("GET", feed_url, headers=headers) as response:
            status_code = response.status_code
            if status_code in {304, 401, 403, 429}:
                content = b""
            else:
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Feed exceeds configured {max_bytes}-byte safety limit")
                    chunks.append(chunk)
                content = b"".join(chunks)
    except Exception as exc:
        cached = _cached_items(cache)
        failures = int(cache.get("consecutive_failures", 0)) + 1
        next_refresh_at = _next_refresh(checked_at, refresh_interval_minutes, failures)
        error = f"{type(exc).__name__}: {exc}"
        write_json(
            cache_path,
            {
                **cache,
                "feed_url": feed_url,
                "source_id": source.id,
                "status": SourceStatus.PARTIAL if cached else SourceStatus.FAILED,
                "error": error,
                "checked_at": checked_iso,
                "next_refresh_at": next_refresh_at,
                "consecutive_failures": failures,
            },
        )
        return result(
            SourceStatus.PARTIAL if cached else SourceStatus.FAILED,
            cached, "stale" if cached else "miss",
            error=error, stale=bool(cached),
            latency_ms=round((time.perf_counter() - started) * 1000),
            next_refresh_at=next_refresh_at, **validators,
        )

    assert response is not None
    latency_ms = round((time.perf_counter() - started) * 1000)
    status_code = response.status_code
    validators = {key: response.headers.get(key.replace("_", "-")) or value
                  for key, value in validators.items()}
    if status_code == 304:
        items = _cached_items(cache)
        status = SourceStatus.SUCCESS if items else SourceStatus.NO_ITEMS
        next_refresh_at = _next_refresh(checked_at, refresh_interval_minutes, 0)
        write_json(
            cache_path,
            {
                **cache,
                "status": status,
                "error": None,
                "http_status": status_code,
                "checked_at": checked_iso,
                "next_refresh_at": next_refresh_at,
                "consecutive_failures": 0,
                "last_success_at": checked_iso,
            },
        )
        return result(
            status, items, "not_modified",
            http_status=status_code, latency_ms=latency_ms,
            next_refresh_at=next_refresh_at, **validators,
        )

    challenge = classify_access_text(
        status_code,
        "",
        content[:30000].decode("utf-8", errors="replace"),
    )
    retry_after = _retry_after_seconds(response.headers.get("retry-after"))
    if status_code == 429 or challenge.get("rate_limited"):
        status = SourceStatus.RATE_LIMITED
        error = f"HTTP {status_code}: feed rate limited"
        items = _cached_items(cache)
    elif status_code >= 400:
        status = (
            SourceStatus.VERIFICATION_REQUIRED if challenge.get("required") else SourceStatus.FAILED
        )
        error = f"HTTP {status_code}"
        items = _cached_items(cache)
    elif challenge.get("required") or not looks_like_feed(
        content, response.headers.get("content-type", "")
    ):
        status = (
            SourceStatus.VERIFICATION_REQUIRED if challenge.get("required") else SourceStatus.FAILED
        )
        error = "Expected a publisher feed or news sitemap"
        items = _cached_items(cache)
    else:
        try:
            items = parse_feed_document(
                content,
                source,
                feed_url,
                checked_iso,
                timezone,
                max_items=max_items,
                data_dir=data_dir,
            )
        except (ET.ParseError, ValueError) as exc:
            status = SourceStatus.FAILED
            error = f"{type(exc).__name__}: {exc}"
            items = _cached_items(cache)
        else:
            status = SourceStatus.SUCCESS if items else SourceStatus.NO_ITEMS
            error = None

    failed = status in {
        SourceStatus.FAILED,
        SourceStatus.RATE_LIMITED,
        SourceStatus.VERIFICATION_REQUIRED,
    }
    stale = bool(items) and failed
    if stale:
        status = SourceStatus.PARTIAL
    failures = int(cache.get("consecutive_failures", 0)) + 1 if failed else 0
    next_refresh_at = _next_refresh(
        checked_at,
        refresh_interval_minutes,
        failures,
        retry_after if failed else None,
    )
    record = {
        "schema_version": "1.0",
        "feed_url": feed_url,
        "source_id": source.id,
        "status": status,
        "error": error,
        "http_status": status_code,
        **validators,
        "checked_at": checked_iso,
        "last_success_at": (checked_iso if not failed else cache.get("last_success_at")),
        "next_refresh_at": next_refresh_at,
        "consecutive_failures": failures,
        "items": [item.to_dict() for item in items],
        "collect_all_items": source.collect_all_items if not failed else bool(
            cache.get("collect_all_items")),
    }
    write_json(cache_path, record)
    return result(
        status, items, "stale" if stale else "updated",
        http_status=status_code, error=error, stale=stale, latency_ms=latency_ms,
        next_refresh_at=next_refresh_at, **validators,
    )
