from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Page

from .article_time import normalize_time
from .config import SourceConfig
from .image_policy import normalize_image_candidates, srcset_candidates
from .models import ArticleItem
from .utils import canonicalize_url, clean_title, item_id, url_for_source_filter

IndexAdapter = Callable[[Page, SourceConfig, str], list[ArticleItem]]
_RELATIVE_TIME = re.compile(r"\b\d+\s*(?:min(?:ute)?s?|hrs?|hours?|days?)\s+ago\b", re.I)
_LOW_INFORMATION_TITLES = {
    "abstract",
    "developers",
    "homepage",
    "latest news",
    "learn more",
    "publications",
    "read more",
    "view all comments",
    "overlay link",
    "about us",
    "who we are",
    "programs",
    "careers & culture",
    "nato headquarters",
    "français",
    "register",
    "media contacts",
    "catalyst lab",
    "microsoft teams",
}


def is_article_link(title: str, url: str) -> bool:
    """处理：排除导航标题、栏目入口和被当作标题的网址。
    输入：采集得到的链接标题与原始地址。
    输出：文章候选判断，供新采集和历史新闻展示共用。
    """
    title = clean_title(title)
    if title.casefold() in _LOW_INFORMATION_TITLES or title.startswith(("http://", "https://")):
        return False
    if re.fullmatch(r"(?:today|yesterday)?\s*\d{1,2}:\d{2}", title, re.I):
        return False
    path = urlsplit(url).path.lower().rstrip("/")
    return not (
        not path
        or re.search(
            r"/(?:programs|about|about-us|who-we-are|contact|contacts|careers|search|register)(?:/[^/]+)?$"
            r"|/(?:news|events)/all$|/(?:ext/en/home|ext/en/news|en/search)$"
            r"|/research-area/[^/]+$",
            path,
        )
    )


BROWSER_ROWS_JS = """anchors => anchors.map(a => ({
            title: (
                (a.querySelector('h1, h2, h3, h4') || {}).innerText ||
                a.getAttribute('aria-label') || a.getAttribute('title') ||
                a.innerText || ''
            ).trim(),
            href: a.href || '',
            table_date: a.closest('td')?.previousElementSibling?.textContent || '',
            reuters_syndication: (() => {
                const paragraphs = Array.from(a.querySelectorAll('p'));
                return a.querySelector('img[alt="Reuters"]') &&
                    paragraphs.some(p => p.textContent.trim() === 'Reuters')
                    ? paragraphs.at(-1).textContent.trim() : '';
            })(),
            image_sources: (() => {
                const card = a.closest('article, li, [class*="card"], [class*="story"]');
                const root = card || a;
                const images = Array.from(root.querySelectorAll('picture source, img'));
                return images.map(image => ({
                    srcset: image.getAttribute('srcset') || image.getAttribute('data-srcset') || '',
                    current_src: image.currentSrc || '',
                    natural_width: image.naturalWidth || null,
                    natural_height: image.naturalHeight || null,
                    src: image.getAttribute('src') || '',
                    data_src: image.getAttribute('data-src') || '',
                    data_original: image.getAttribute('data-original') || '',
                    data_lazy_src: image.getAttribute('data-lazy-src') || ''
                }));
            })(),
            context: (() => {
                const card = a.closest('article, li, [class*="card"], [class*="story"]');
                const time = card ? card.querySelector('time') : null;
                return [
                    time ? (time.getAttribute('datetime') || time.textContent || '') : '',
                    card ? (card.textContent || '').slice(0, 500) : '',
                    (a.innerText || '').slice(0, 500)
                ].join(' ');
            })()
        }))"""


ARXIV_ROWS_JS = """entries => entries.map(dt => {
            const details = dt.nextElementSibling;
            const link = dt.querySelector('a[href*="/abs/"]');
            const titleNode = details ? details.querySelector('.list-title') : null;
            const headings = Array.from(document.querySelectorAll('h3'));
            const dateHeading = headings.reverse().find(
                heading => Boolean(
                    heading.compareDocumentPosition(dt) & Node.DOCUMENT_POSITION_FOLLOWING
                )
            );
            const rawTitle = titleNode ? (titleNode.textContent || '') : '';
            return {
                title: rawTitle.replace(/^\\s*Title:\\s*/i, '').trim(),
                href: link ? link.href : '',
                date_text: dateHeading ? (dateHeading.textContent || '').trim() : ''
            };
        })"""


YEAR_ROWS_JS = """anchors => anchors.map(a => ({
            title: (a.innerText || a.getAttribute('title') || '').trim(),
            href: a.href || ''
        }))"""


TWZ_ROWS_JS = """headings => headings.map(heading => {
            const link = heading.closest('a[href]');
            const card = heading.closest('.card-post') || heading.closest('article');
            const descriptionNode = card ? card.querySelector('.card-post-dek') : null;
            const timeNode = card ? card.querySelector(
                'time, .byline-item-timestamp, [class*="timestamp"], [class*="date"]'
            ) : null;
            const timeText = timeNode
                ? `${timeNode.getAttribute('datetime') || ''} ${timeNode.textContent || ''}`
                : '';
            return {
                title: (heading.innerText || '').trim(),
                href: link ? link.href : '',
                card_text: timeText.trim(),
                description: descriptionNode ? (descriptionNode.textContent || '').trim() : ''
            };
        })"""


def is_eligible(source: SourceConfig, title: str, url: str) -> bool:
    """按来源的域名、文章路径和排除规则判断候选是否可采集。
    输入：带入口与筛选规则的来源配置、待处理的 URL。
    - ``title``：来源提供的标题文本；会清理空白，并用于过滤、身份或展示。
    """
    title = clean_title(title)
    if not is_article_link(title, url):
        return False
    if len(title) < 8 or not url.startswith(("http://", "https://")):
        return False
    filter_url = url_for_source_filter(url)
    if title.casefold() in _LOW_INFORMATION_TITLES or not re.search(
        r"[A-Za-z\u3400-\u9fff]", title
    ):
        return False
    if source.exclude_title_patterns and any(
        re.search(pattern, title, re.I) for pattern in source.exclude_title_patterns
    ):
        return False
    hostname = urlsplit(filter_url).netloc.lower().removeprefix("www.")
    if source.include_domains and not any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in source.include_domains
    ):
        return False
    if source.exclude_patterns and any(
        re.search(pattern, filter_url, re.I) for pattern in source.exclude_patterns
    ):
        return False
    return not (
        source.article_patterns
        and not any(re.search(pattern, filter_url, re.I) for pattern in source.article_patterns)
    )


def _article(source: SourceConfig, title: str, url: str, discovered_at: str) -> ArticleItem:
    """处理：根据来源、标题和 URL 构建具有稳定身份的规范文章条目。
    输入：带入口与筛选规则的来源配置、待处理的 URL、本轮发现时间。
    - ``title``：来源提供的标题文本；会清理空白，并用于过滤、身份或展示。
    输出：可进入规范来源索引的文章条目；包含稳定 ID、来源身份、规范 URL、时间和可用元数据。
    """
    canonical = canonicalize_url(url)
    return ArticleItem(
        item_id=item_id(source.id, canonical),
        source_id=source.id,
        source_name=source.name,
        title=title,
        url=url,
        canonical_url=canonical,
        discovered_at=discovered_at,
        module=source.module,
        category=source.category,
        metadata={
            "role": source.role,
            "language": source.language,
            "region": source.region,
            **source.origin_metadata,
        },
    )


def _published_at(value: str, url: str, discovered_at: str | None = None) -> str | None:
    """从文本、URL 或相对时间中解析文章发布日期。"""
    text = clean_title(value)
    normalized = normalize_time(text)
    if normalized:
        return normalized
    for candidate in (text, url):
        for pattern in (
            r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b",
            r"\b(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b",
        ):
            match = re.search(pattern, candidate)
            if not match:
                continue
            try:
                return (
                    datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                    .date()
                    .isoformat()
                )
            except ValueError:
                continue
    url_date = re.search(r"/(20\d{2}/[a-z]{3}/\d{1,2})/", url, re.I)
    if url_date:
        try:
            return datetime.strptime(url_date[1], "%Y/%b/%d").date().isoformat()
        except ValueError:
            pass
    relative = re.search(
        r"\b(\d+)\s*(min(?:ute)?s?|hr|hrs|hour|hours|day|days)\s+ago\b",
        text,
        re.I,
    )
    if relative and discovered_at:
        try:
            observed = datetime.fromisoformat(discovered_at.replace("Z", "+00:00"))
            amount = int(relative.group(1))
            unit = relative.group(2).lower()
            delta = (
                timedelta(minutes=amount)
                if unit.startswith("min")
                else timedelta(hours=amount)
                if unit.startswith(("hr", "hour"))
                else timedelta(days=amount)
            )
            return (observed - delta).isoformat(timespec="seconds")
        except ValueError:
            pass
    for pattern, date_format in (
        (r"\b([A-Z][a-z]{2,8} \d{1,2}, 20\d{2})\b", "%B %d, %Y"),
        (r"\b([A-Z][a-z]{2} \d{1,2}, 20\d{2})\b", "%b %d, %Y"),
        (r"\b(\d{1,2} [A-Z][a-z]{2} 20\d{2})\b", "%d %b %Y"),
        (r"\b(\d{1,2} [A-Z][a-z]{2,8} 20\d{2})\b", "%d %B %Y"),
    ):
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(1), date_format).date().isoformat()
            except ValueError:
                continue
    return None


def _distinct_index_articles(
    rows: list[dict[str, Any]], source: SourceConfig, discovered_at: str,
    *, mode: str, base_url: str = "",
) -> Iterator[tuple[dict[str, Any], ArticleItem, bool]]:
    """处理：按网页顺序筛掉无效和重复链接，执行来源上限。
    输入：浏览器列表行、专用解析模式、来源策略和发现时间。
    输出：原始列表行、文章条目和转载标记，供日期与摘要解析。
    """
    seen: set[str] = set()
    for row in rows:
        title = clean_title(row.get("title", ""))
        url = row.get("href", "")
        reuters_reprint = False
        if mode == "browser_index":
            url = urljoin(base_url, url)
            reuters_reprint = source.id == "reuters" and urlsplit(url).hostname == "www.aol.com"
            if reuters_reprint:
                title = clean_title(row.get("reuters_syndication", ""))
        elif mode == "arxiv_index":
            title = re.sub(r"^\s*Title:\s*", "", title, flags=re.I)
            url = urljoin(source.url, url)
        if not is_eligible(source, title, url):
            continue
        article = _article(source, title, url, discovered_at)
        if article.canonical_url in seen:
            continue
        seen.add(article.canonical_url)
        yield row, article, reuters_reprint
        limit = reuters_reprint or mode != "browser_index" or source.item_order != "published_at"
        if limit and not source.collect_all_items and len(seen) >= source.max_items:
            break


def browser_items_from_rows(
    rows: list[dict[str, Any]],
    source: SourceConfig,
    discovered_at: str,
    base_url: str,
) -> list[ArticleItem]:
    """处理：规范化不可信索引页行数据，且不执行页面中的任何指令。
    输入：带入口与筛选规则的来源配置、本轮发现时间。
    - ``rows``：浏览器 DOM 解析器产生的候选记录；每行含标题、链接、摘要和图片候选。
    - ``base_url``：解析相对链接时使用的最终页面或 Feed 基准 URL。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    items: list[ArticleItem] = []
    for row, article, reuters_reprint in _distinct_index_articles(
        rows, source, discovered_at, mode="browser_index", base_url=base_url,
    ):
        url, title = article.url, article.title
        items.append(article)
        if reuters_reprint:
            # 转载入口的发布时间由文章页确认，头像不作为新闻配图。
            article.metadata.update(syndication_provider="Reuters", syndication_publisher="AOL")
            continue
        # 从卡片上下文移除标题，避免把标题中的会议日等事件日期当作发布日期。
        context = clean_title(row.get("context", "")).replace(title, "")
        article.published_at = _published_at(context, url)
        if not article.published_at and _RELATIVE_TIME.search(context):
            # 卡片相对时间可能是更新时刻，保留原文并交由原文日期探测确认。
            article.metadata.update(publication_time_basis="relative", published_raw=context,
                                    published_precision="relative")
        if source.id == "boj_news" and "/en/statistics/market/" in urlsplit(url).path:
            # 日本银行表格首列是发布日期；终值文件名和标题写的是上一交易日。
            label = clean_title(row.get("table_date", "")).replace(".", "")
            article.published_at = normalize_time(label) or article.published_at
        if source.id == "china_mfa":
            date_match = re.search(r"/t(20\d{6})_\d+\.html$", url)
            if date_match:
                article.published_at = _published_at("", "/" + date_match[1])
        if source.publisher_group == "cna_taiwan":
            date_match = re.search(r"/news/[a-z]+/(20\d{6})\d+\.aspx$", url)
            if date_match:
                article.published_at = article.published_at or _published_at(
                    "", "/" + date_match[1],
                )
        if source.id == "yicai_economy" and row.get("yicai_create_date"):
            raw_date = row["yicai_create_date"]
            article.published_at = normalize_time(raw_date, "Asia/Shanghai")
            article.metadata["yicai_create_date"] = raw_date
            if (article.published_at
                    and article.metadata.get("publication_time_basis") == "relative"):
                article.metadata["publication_time_basis"] = "publisher"
        raw_candidates = row.get("image_candidates")
        if not isinstance(raw_candidates, list):
            raw_candidates = []
        image_sources = row.get("image_sources")
        if isinstance(image_sources, list):
            raw_candidates = list(raw_candidates)
            for image in image_sources:
                if isinstance(image, dict):
                    raw_candidates.extend(
                        [
                            *srcset_candidates(image.get("srcset")),
                            image.get("current_src"),
                            image.get("data_original"),
                            image.get("data_src"),
                            image.get("data_lazy_src"),
                            image.get("src"),
                        ]
                    )
            article.metadata["image_source_observations"] = [
                {
                    key: image.get(key)
                    for key in (
                        "current_src",
                        "natural_width",
                        "natural_height",
                        "srcset",
                    )
                }
                for image in image_sources
                if isinstance(image, dict)
            ]
        image_candidates = normalize_image_candidates(
            [*raw_candidates, row.get("image_url")],
            base_url,
        )
        if image_candidates:
            article.image_url = image_candidates[0]
            if len(image_candidates) > 1:
                article.metadata["image_candidates"] = image_candidates
    return items


def arxiv_items_from_rows(
    rows: list[dict[str, str]],
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """处理：把 arXiv 索引页解析记录转换为符合来源策略的文章条目。
    输入：带入口与筛选规则的来源配置、本轮发现时间。
    - ``rows``：arXiv 索引页解析得到的论文记录；每行读取 title、href、date_text 和 description。
    输出：可写入来源索引的 arXiv 文章条目列表；每项含稳定 ID、规范摘要页 URL、发布日期和摘要，
      并已按来源规则过滤、去重和限量。
    """
    items: list[ArticleItem] = []
    for row, article, _ in _distinct_index_articles(
        rows, source, discovered_at, mode="arxiv_index",
    ):
        article.published_at = _published_at(row.get("date_text", ""), article.url, discovered_at)
        article.description = clean_title(row.get("description", ""))
        items.append(article)
    return items


def latest_year_url(rows: list[dict[str, str]], source_url: str = "") -> str:
    """处理：从当前栏目内的年份导航选择最新年度，排除全站其他栏目。
    输入：
    - ``rows``：年度归档页解析得到的链接记录；每行读取 title 与 href，并从标题中提取四位年份。
    - ``source_url``：当前栏目入口，限定年度链接所在的主机及目录。
    输出：经过选择、规范化或安全处理的 URL 字符串，供后续访问或渲染使用。
    """
    candidates: list[tuple[int, str]] = []
    source = urlsplit(source_url)
    directory = source.path.rsplit("/", 1)[0] + "/"
    for row in rows:
        title = clean_title(row.get("title", ""))
        href = row.get("href", "")
        target = urlsplit(href)
        if source_url and (
            target.netloc != source.netloc or not target.path.startswith(directory)
        ):
            continue
        if re.fullmatch(r"20\d{2}", title) and href.startswith(("http://", "https://")):
            candidates.append((int(title), href))
    if not candidates:
        raise RuntimeError("No year links found on the source index")
    return max(candidates)[1]


def collect_latest_year_index(
    page: Page,
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """从当前索引页选择最新年份并采集该年份的文章记录。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    rows = page.locator("a[href]").evaluate_all(YEAR_ROWS_JS)
    year_url = latest_year_url(rows, source.url)
    response = page.goto(year_url, wait_until="domcontentloaded", timeout=45_000)
    if response is None or not response.ok:
        status = response.status if response else "no response"
        raise RuntimeError(f"Latest year index returned HTTP {status}")
    return collect_browser_index(page, source, discovered_at)


def twz_items_from_rows(
    rows: list[dict[str, str]],
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """处理：把 TWZ 页面行转换为去重后的文章条目。
    输入：带入口与筛选规则的来源配置、本轮发现时间。
    - ``rows``：The War Zone 列表页解析记录；每行读取 title、href、card_text 和 description。
    输出：可写入来源索引的 The War Zone 文章条目列表；包含稳定身份、发布日期和清理后的摘要。
    """
    items: list[ArticleItem] = []
    for row, article, _ in _distinct_index_articles(rows, source, discovered_at, mode="twz_index"):
        posted = re.search(
            r"Posted on ([A-Z][a-z]{2} \d{1,2}, \d{4})",
            row.get("card_text", ""),
        )
        if posted:
            article.published_at = (
                datetime.strptime(posted.group(1), "%b %d, %Y").date().isoformat()
            )
        else:
            article.published_at = _published_at(row.get("card_text", ""), article.url)
            if not article.published_at and _RELATIVE_TIME.search(row.get("card_text", "")):
                article.metadata["publication_time_basis"] = "relative"
                article.metadata["published_raw"] = row["card_text"]
                article.metadata["published_precision"] = "relative"
        article.description = clean_title(row.get("description", ""))
        items.append(article)
    return _clear_misattributed_descriptions(items)


def collect_weibo_api(
    page: Page,
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """处理：解析微博热搜接口中的词条、跳转链接、热度和排名。
    输入：带入口与筛选规则的来源配置、本轮发现时间。
    - ``page``：Playwright 已加载且可执行同源请求的微博页面；用于调用公开热搜接口。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    body = page.locator("body").inner_text(timeout=10000)
    payload = json.loads(body)
    return weibo_items_from_payload(payload, source, discovered_at)


def weibo_items_from_payload(
    payload: dict,
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """处理：将微博公开接口的词条转换为有序候选，保留热度和置顶信息。
    输入：页面 JSON、来源配置和观察时间。
    输出：去掉推广条目的热搜列表，供同步和异步浏览器入口共用。
    """
    if isinstance(payload.get("data"), list):
        if payload.get("code") != 200:
            raise RuntimeError(f"Weibo listing provider returned code={payload.get('code')!r}")
        group = [
            {"desc": row["title"], "scheme": row["link"],
             "desc_extr": row.get("hot_value"), "realpos": rank}
            for rank, row in enumerate(payload["data"], start=1)
        ]
    else:
        if payload.get("ok") != 1:
            raise RuntimeError(f"Weibo API returned ok={payload.get('ok')!r}")
        cards = payload.get("data", {}).get("cards", [])
        group = cards[0].get("card_group", []) if cards else []
    items: list[ArticleItem] = []
    for list_position, row in enumerate(group, start=1):
        title = clean_title(row.get("desc", ""))
        url = row.get("scheme", "")
        if not title or not url or row.get("promotion"):
            continue
        hot_raw = row.get("desc_extr", "")
        hot_value = None
        hot_label = ""
        if isinstance(hot_raw, int):
            hot_value = hot_raw
        elif isinstance(hot_raw, str):
            match = re.search(r"(\d+)$", hot_raw.strip())
            if match:
                hot_value = int(match.group(1))
                hot_label = hot_raw[: match.start()].strip()
        article = _article(source, title, url, discovered_at)
        article.metadata.update(
            {
                "list_position": list_position,
                "hot_rank": row.get("realpos") or row.get("band_rank"),
                "hot_value": hot_value,
                "hot_label": hot_label,
                "is_pinned": not bool(row.get("realpos") or row.get("band_rank")),
            }
        )
        items.append(article)
        if not source.collect_all_items and len(items) >= source.max_items:
            break
    return items


def seed_items_from_payload(
    payload: dict,
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """处理：把 ByteDance Seed 页面状态转换为规范论文条目。
    输入：
    - ``payload``：ByteDance Seed 页面状态对象；
      读取 sub_article_list 中的中英文标题、摘要、作者、期刊、研究领域和发布时间。
    - ``source``：来源配置；包含来源 ID、名称、入口 URL、分类、过滤规则、限额和可信层级。
    - ``discovered_at``：本轮发现时间的 ISO 字符串；在缺少发布时间时作为可追溯时间。
    输出：可写入来源索引的 Seed 论文条目列表；
      保留稳定身份、摘要、作者、期刊、研究领域和发布时间。
    """
    items: list[ArticleItem] = []
    for row in payload.get("sub_article_list", []):
        metadata = row.get("ArticleMeta", {})
        content_zh = row.get("ArticleSubContentZh", {})
        content_en = row.get("ArticleSubContentEn", {})
        content = content_zh if content_zh.get("Title") else content_en
        title = clean_title(content.get("Title", ""))
        links = metadata.get("ExternalLinks", [])
        url = next((link.get("Link") for link in links if link.get("Link")), "")
        if "/pdf/" in url:
            url = url.replace("/pdf/", "/abs/").removesuffix(".pdf")
        if not title or not url:
            continue
        article = _article(source, title, url, discovered_at)
        article.description = content.get("Abstract", "")
        publish_ms = metadata.get("PublishDate")
        if isinstance(publish_ms, (int, float)):
            article.published_at = datetime.fromtimestamp(publish_ms / 1000, UTC).isoformat()
        article.original_provider = "ByteDance Seed"
        article.metadata.update(
            {
                "article_id": metadata.get("ArticleID"),
                "authors": metadata.get("Author", ""),
                "journal": metadata.get("Journal", ""),
                "research_areas": [
                    area.get("ResearchAreaNameZh") or area.get("ResearchAreaName")
                    for area in metadata.get("ResearchArea", [])
                ],
            }
        )
        items.append(article)
        if not source.collect_all_items and len(items) >= source.max_items:
            break
    return items


def collect_seed_papers(
    page: Page,
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """处理：从 ByteDance Seed 页面状态中读取论文元数据并规范化。
    输入：带入口与筛选规则的来源配置、本轮发现时间。
    - ``page``：Playwright 已加载的 Seed 论文页；从页面脚本状态中取得结构化论文列表。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    with page.expect_response(
        lambda response: "get_article_list_v2" in response.url,
        timeout=30_000,
    ) as response_info:
        page.reload(wait_until="domcontentloaded", timeout=45_000)
    response = response_info.value
    if not response.ok:
        raise RuntimeError(f"ByteDance Seed papers API returned HTTP {response.status}")
    return seed_items_from_payload(response.json(), source, discovered_at)


DOM_INDEX_ROWS = {
    "browser_index": ("a[href]", BROWSER_ROWS_JS),
    "arxiv_index": ("dl#articles dt, dl dt", ARXIV_ROWS_JS),
    "twz_index": ("h3", TWZ_ROWS_JS),
}


def dom_index_items(
    mode: str, rows: list[dict], source: SourceConfig, discovered_at: str, url: str,
) -> list[ArticleItem]:
    """处理：让手动验证和定时采集使用同一套 DOM 条目转换。
    输入：专用索引模式、已读取列表行与本次页面地址。
    输出：按来源规则规范化的文章。
    """
    if mode == "browser_index":
        return browser_items_from_rows(rows, source, discovered_at, url)
    parser = {"arxiv_index": arxiv_items_from_rows, "twz_index": twz_items_from_rows}[mode]
    return parser(rows, source, discovered_at)


def _collect_dom_index(page: Page, source: SourceConfig, discovered_at: str, mode: str
                       ) -> list[ArticleItem]:
    """处理：读取同步 Playwright 的已加载列表页。
    输入：人工验证后保留的浏览器页面与专用 DOM 模式。
    输出：与异步采集共用同一规范化规则的候选。
    """
    selector, script = DOM_INDEX_ROWS[mode]
    return dom_index_items(mode, page.locator(selector).evaluate_all(script),
                           source, discovered_at, page.url)


collect_browser_index = partial(_collect_dom_index, mode="browser_index")
collect_arxiv_index = partial(_collect_dom_index, mode="arxiv_index")
collect_twz_index = partial(_collect_dom_index, mode="twz_index")


_ADAPTERS: dict[str, IndexAdapter] = {
    "arxiv_index": collect_arxiv_index,
    "browser_index": collect_browser_index,
    "latest_year_index": collect_latest_year_index,
    "seed_papers": collect_seed_papers,
    "twz_index": collect_twz_index,
    "weibo_api": collect_weibo_api,
}


def collect_candidates(
    page: Page,
    source: SourceConfig,
    discovered_at: str,
) -> list[ArticleItem]:
    """调用来源专用适配器采集候选，并清理跨链接误归属的重复长摘要。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    try:
        adapter = _ADAPTERS[source.adapter_name]
    except KeyError as exc:
        available = ", ".join(sorted(_ADAPTERS))
        raise ValueError(
            f"Unknown source adapter {source.adapter_name!r}; available: {available}"
        ) from exc
    items = adapter(page, source, discovered_at)
    return items if source.adapter_name == "twz_index" else _clear_misattributed_descriptions(items)


def _clear_misattributed_descriptions(items: list[ArticleItem]) -> list[ArticleItem]:
    """处理：移除被多个不同链接复用的长描述，避免错误归属。
    输入：有序索引条目。
    输出：经筛选和排序的来源索引条目，含稳定 ID、规范 URL、时间及元数据。
    """
    counts: dict[str, int] = {}
    for item in items:
        description = clean_title(item.description)
        if len(description) >= 60:
            key = description.casefold()
            counts[key] = counts.get(key, 0) + 1
    duplicated = {key for key, count in counts.items() if count > 1}
    if not duplicated:
        return items
    for item in items:
        if clean_title(item.description).casefold() in duplicated:
            item.description = ""
    return items
