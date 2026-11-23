from __future__ import annotations

import hashlib
import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .article_time import abc_live_entry_id, normalize_time
from .models import ContentStatus

NOISE_SELECTORS = [
    "script", "style", "noscript", "nav", "footer", "aside", "[hidden]",
    '[aria-hidden="true"]', '[aria-label*="advert" i]', '[class*="advert" i]',
    '[class*="cookie" i]', '[class*="newsletter" i]',
    '[class*="related" i]', '[class*="recommend" i]',
    '[style*="display:none" i]', '[style*="display: none" i]',
]
_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "body", "blockquote", "pre", "li",
    "ul", "ol", "dl", "dt", "dd", "figure", "figcaption", "table",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_INCOMPLETE = re.compile(
    r"\b(?:loading|enable javascript|subscribe to (?:read|continue)|sign in to (?:read|continue)"
    r"|continue reading|read (?:the )?full (?:article|story))\b"
    r"|加载中|订阅后阅读|登录后阅读|展开全文|阅读全文", re.I,
)
_VIDEO_DURATION = re.compile(
    r"(?:video duration (?:\d{1,2} hours? )?\d{1,2} minutes? \d{1,2} seconds? )?"
    r"(?:\d{1,2}:)?\d{1,2}:[0-5]\d",
    re.I,
)


def strip_content_frontmatter(text: str) -> str:
    """处理：去掉本地正文 Markdown 的 YAML 头，保留完整文章文本。
    输入：保存的正文视图或普通文本。
    输出：正文部分；普通文本保持原样。
    """
    newline = "\r\n" if text.startswith("---\r\n") else "\n"
    boundary = newline + "---" + newline
    if text.startswith("---" + newline) and boundary in text[3 + len(newline):]:
        return text.split(boundary, 1)[1].lstrip("\r\n")
    return text


def is_navigation_only(text: str) -> bool:
    """处理：识别只有评论入口、原文链接和榜单评分的 Feed 字段。
    输入：Feed 文本、压缩描述或历史正文 Markdown。
    输出：纯导航返回真；含实质短句的文本继续保留。
    """
    text = strip_content_frontmatter(text).strip()
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    remaining = re.sub(
        r"(?:Article|Comments)\s+URL:\s*https?://\S+"
        r"|Points:\s*\d+|#\s*Comments:\s*\d+|\bComments\b",
        "", text, flags=re.I,
    )
    return bool(text) and not remaining.strip(" \t\r\n|-")


def is_video_player_only(text: str) -> bool:
    """处理：识别只包含播放标签、时长和单条标题的播放器卡片。
    输入：抽取文本或历史正文 Markdown。
    输出：片段独立构成播放器卡片时返回真，供正文过滤与复用校验使用。
    """
    body = strip_content_frontmatter(text).strip()
    if len(body) > 240:
        return False
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return (2 <= len(lines) <= 3 and lines[0].casefold() in {"now playing", "正在播放"}
            and any(_VIDEO_DURATION.fullmatch(line) for line in lines[1:]))


@dataclass
class ExtractedDocument:
    """处理：承载选中正文、结构块和抽取质量，隔离访问结果与完整性推断。
    输入：已清理的正文节点、选择器、结构块及候选检查记录。
    输出：供正文持久化和配图选择共享的抽取结果；不声称完成事实核验。
    """

    text: str = ""
    selector: str | None = None
    blocks: list[dict[str, Any]] = field(default_factory=list)
    status: ContentStatus = ContentStatus.METADATA_ONLY
    quality: dict[str, Any] = field(default_factory=dict)
    node: Tag | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)


def _inline_text(node: Tag) -> str:
    """处理：拼接行内标记而保留原有词间空白和显式换行。
    输入：已去除脚本与噪声的正文节点。
    输出：不会在中文或拆分的英文单词中插入空格的文本。
    """
    parts = []
    for child in node.descendants:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name == "br":
            parts.append("\n")
    return "\n".join(
        re.sub(r"[^\S\n]+", " ", line).strip()
        for line in "".join(parts).splitlines()
    ).strip()


def document_blocks(root: Tag) -> list[dict[str, Any]]:
    """处理：把正文 DOM 转成有序标题、段落、列表、引文和表格块。
    输入：选中的无脚本正文区域；表格原始单元格和跨行跨列声明来自页面。
    输出：可存入证据 JSON 的结构块；纯文本由这些块派生。
    """
    blocks: list[dict[str, Any]] = []

    def visit(node: Tag) -> None:
        """处理：递归输出块，避免容器与子块重复计入正文。
        输入：当前正文节点和外层块列表。
        输出：按页面顺序追加带类型的正文块。
        """
        if node.name == "table":
            rows = [
                [
                    {
                        "text": _inline_text(cell),
                        "header": (cell.name == "th" or cell.find_parent("thead") is not None
                                   or cell.get("scope") in {"row", "col", "rowgroup", "colgroup"}
                                   or cell.get("role") in {"columnheader", "rowheader"}),
                        "rowspan": str(cell.get("rowspan", "1")),
                        "colspan": str(cell.get("colspan", "1")),
                    }
                    for cell in row.find_all(["th", "td"], recursive=False)
                ]
                for row in node.find_all("tr") if row.find_parent("table") is node
            ]
            caption = node.find("caption", recursive=False)
            table_text = "\n".join(" | ".join(cell["text"] for cell in row) for row in rows)
            if caption:
                table_text = _inline_text(caption) + "\n" + table_text
            if table_text.strip():
                blocks.append({"type": "table", "text": table_text, "rows": rows})
            return
        if not any(child.name in _BLOCK_TAGS for child in node.find_all(recursive=False)):
            value = node.get_text() if node.name == "pre" else _inline_text(node)
            if value:
                kind = {
                    "li": "list_item", "blockquote": "quote", "pre": "preformatted",
                    "figcaption": "caption", "dt": "term", "dd": "definition",
                }.get(node.name, "paragraph")
                block: dict[str, Any] = {"type": kind, "text": value}
                if re.fullmatch(r"h[1-6]", node.name):
                    block.update(type="heading", level=int(node.name[1]))
                list_item = node if node.name == "li" else node.find_parent("li")
                if list_item is not None:
                    if kind == "paragraph":
                        block["type"] = "list_item"
                    block["ordered"] = bool(list_item.parent and list_item.parent.name == "ol")
                    block["list_depth"] = len(list_item.find_parents(["ul", "ol"]))
                if node.name == "blockquote" or node.find_parent("blockquote") is not None:
                    block["type"] = "quote"
                blocks.append(block)
            return
        pending: list[str] = []

        def flush() -> None:
            """处理：保存块之间的行内文字，避免容器直接文本丢失。
            输入：当前容器累积的行内内容。
            输出：追加段落并清空缓存。
            """
            value = re.sub(r"\s+", " ", "".join(pending)).strip()
            if value:
                blocks.append({"type": "paragraph", "text": value})
            pending.clear()

        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, Tag) and child.name in _BLOCK_TAGS:
                flush()
                visit(child)
            elif isinstance(child, Tag):
                pending.append(_inline_text(child))
            else:
                pending.append(str(child))
        flush()

    visit(root)
    # 发布商推广可能是直接文本或嵌套行内节点，统一在块边界去除精确 CTA。
    blocks = [block for block in blocks if not re.match(
        r"^Choose CNBC as your preferred source on Google\b", block["text"],
    )]
    for position, block in enumerate(blocks, 1):
        block["block_id"] = f"block-{position}"
    return blocks


def extract_document(
    soup: BeautifulSoup, selectors: list[str], *, truncated: bool = False,
    expected_title: str = "",
) -> ExtractedDocument:
    """处理：按正文范围、链接密度和截断信号评估候选，允许短公告完整入库。
    输入：不可信 HTML、来源配置选择器以及 HTTP 字节上限是否截断响应。
    输出：选中正文和可审计质量；宽泛 body 或截断内容最多标为 partial。
    """
    for node in soup.select(",".join(NOISE_SELECTORS)):
        node.decompose()
    candidates = []
    seen: set[int] = set()
    # body/main 是宽泛兜底；配置中提前列出它们也不能压过实际 article。
    ordered = list(dict.fromkeys([
        *(selector for selector in selectors if selector not in {"body", "main", "html"}),
        "article", '[itemprop="articleBody"]', ".ArticleBody-articleBody", ".group#article-body",
        "#article", "div.article", "#blogpage .content",
        "main", "body",
    ]))
    for priority, selector in enumerate(ordered):
        try:
            nodes = soup.select(selector)
        except Exception:
            continue
        for node in nodes:
            if id(node) in seen:
                continue
            seen.add(id(node))
            blocks = document_blocks(node)
            text = "\n\n".join(block["text"] for block in blocks)
            if not text:
                continue
            characters = len(text)
            linked = sum(len(_inline_text(link)) for link in node.select("a"))
            link_density = min(1.0, linked / max(characters, 1))
            specific = node.name not in {"body", "main", "html"}
            substantive = any(
                block["type"] != "heading" and len(block["text"].strip()) >= 20
                for block in blocks
            )
            incomplete = bool(_INCOMPLETE.search(text))
            table_gaps = [
                block["block_id"] for block in blocks
                if block["type"] == "table" and any(
                    re.search(r"\d", cell["text"])
                    for row in block["rows"] for cell in row
                ) and not any(
                    cell["header"] and cell["text"].strip()
                    for row in block["rows"] for cell in row
                )
            ]
            video_player_only = is_video_player_only(text) or (
                blocks[0]["type"] == "heading"
                and is_video_player_only("\n\n".join(block["text"] for block in blocks[1:]))
            )
            usable = substantive and link_density < 0.5 and not video_player_only
            complete = usable and specific and not incomplete and not truncated and not table_gaps
            quality = {
                "extractor": "builtin", "extractor_version": "2",
                "region": "specific" if specific else "broad",
                "characters": characters, "block_count": len(blocks),
                "link_density": round(link_density, 4),
                "incomplete_marker": incomplete, "response_truncated": truncated,
                "video_player_only": video_player_only,
                "extraction_status": (
                    "short_complete" if complete and characters < 1500 else
                    "complete" if complete else "partial" if usable else "insufficient"
                ),
                "completeness_basis": "structural_heuristic",
                "fact_verification": "not_performed",
                "title_overlap": title_overlap(expected_title, text),
                "numeric_tables_without_headers": table_gaps,
                "key_fields_verified": None,
                "media_verified": None,
            }
            status = (
                ContentStatus.FULL_TEXT if complete else
                ContentStatus.PARTIAL if usable else ContentStatus.METADATA_ONLY
            )
            result = ExtractedDocument(text, selector, blocks, status, quality, node)
            rank = (usable, specific, not incomplete, -priority, -link_density, characters)
            candidates.append((rank, result))
    if not candidates:
        return ExtractedDocument(quality={"extraction_status": "insufficient"})
    result = max(candidates, key=lambda entry: entry[0])[1]
    result.quality["candidates"] = [
        {"selector": candidate.selector, **candidate.quality} for _rank, candidate in candidates
    ]
    return result


def title_overlap(title: str, text: str) -> float | None:
    """处理：计算标题词和中文二元组在正文中的可见覆盖比例。
    输入：索引原题和已抽取正文；只作词面观测，不判定语义真假。
    输出：零到一的词面覆盖率；没有可比较标题时返回未知。
    """
    tokens = set(re.findall(r"[a-z0-9]{2,}", title.casefold()))
    for run in re.findall(r"[\u3400-\u9fff]+", title):
        tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    if not tokens:
        return None
    normalized_text = text.casefold()
    return round(sum(token in normalized_text for token in tokens) / len(tokens), 4)


def extract_with_fallback(
    soup: BeautifulSoup, selectors: list[str], *, truncated: bool = False,
    expected_title: str = "", fallback: str = "none", page_url: str = "",
) -> ExtractedDocument:
    """处理：保留具体正文基线，仅在内容不足时比较可选本地抽取器。
    输入：已获准读取的 HTML、来源选择器和显式配置的候选抽取器。
    输出：带选择理由的正文；供应器失败不丢失基线，供应器输出不自动升级为全文。
    """
    source_metadata = observed_source_metadata(soup, page_url)
    baseline = extract_document(
        soup, selectors, truncated=truncated, expected_title=expected_title,
    )
    baseline.source_metadata = source_metadata
    if fallback == "none" or baseline.status == ContentStatus.FULL_TEXT:
        return baseline
    if fallback != "trafilatura":
        raise ValueError(f"Unsupported fallback extractor: {fallback}")
    attempt: dict[str, Any] = {"extractor": "trafilatura"}
    baseline.quality["fallback"] = attempt
    try:
        import trafilatura

        # 输入已去掉脚本、隐藏区及相关推荐；不让备用库从脚本恢复未可见的正文。
        markup = trafilatura.extract(
            str(soup), output_format="html", include_comments=False, include_tables=True,
            include_formatting=True, include_links=True, favor_precision=True,
        )
        attempt["version"] = version("trafilatura")
    except ImportError:
        attempt["status"] = "unavailable"
        return baseline
    except Exception as exc:
        attempt.update(status="failed", error_type=type(exc).__name__)
        return baseline
    if not markup:
        attempt["status"] = "no_content"
        return baseline
    candidate = extract_document(
        BeautifulSoup(markup, "html.parser"), [], truncated=truncated,
        expected_title=expected_title,
    )
    attempt.update(status="not_selected", characters=len(candidate.text))
    # 具体正文中的表格或限定条件不能因备用抽取器删掉它们而消除缺口。
    if baseline.quality.get("region") == "specific":
        attempt["reason"] = "preserve_specific_region"
        return baseline
    if candidate.status == ContentStatus.METADATA_ONLY:
        return baseline
    if any(
        block["type"] == "table" and not any(
            candidate_block["type"] == "table" and candidate_block["text"] == block["text"]
            for candidate_block in candidate.blocks
        ) for block in baseline.blocks
    ):
        attempt["reason"] = "table_retention_unconfirmed"
        return baseline
    if baseline.status != ContentStatus.METADATA_ONLY:
        candidate_text = re.sub(r"\s+", " ", candidate.text).strip().casefold()
        paragraphs = [
            re.sub(r"\s+", " ", block["text"]).strip().casefold()
            for block in baseline.blocks
            if block["type"] not in {"heading", "table"} and len(block["text"]) >= 40
        ]
        total = sum(map(len, paragraphs))
        retained = sum(len(text) for text in paragraphs if text in candidate_text)
        retention = retained / total if total else 1.0
        attempt["body_block_retention"] = round(retention, 4)
        # 备用器可补出更多文字，但不能靠删掉大半正文把 liveblog 压成短摘要。
        if retention < 0.7:
            attempt["reason"] = "body_blocks_lost"
            return baseline
        old_density = baseline.quality.get("link_density", 0)
        new_density = candidate.quality.get("link_density", 1)
        if new_density > old_density + 0.05:
            attempt["reason"] = "increased_link_noise"
            return baseline
        if len(candidate.text) == len(baseline.text) and new_density >= old_density:
            attempt["reason"] = "no_observed_gain"
            return baseline
    candidate.status = ContentStatus.PARTIAL
    candidate.source_metadata = source_metadata
    candidate.quality.update(
        extractor="trafilatura", extractor_version=attempt["version"],
        extraction_status="partial", region="provider_candidate",
        response_truncated=truncated,
        incomplete_marker=baseline.quality.get("incomplete_marker", False),
        numeric_tables_without_headers=list(dict.fromkeys([
            *baseline.quality.get("numeric_tables_without_headers", []),
            *candidate.quality.get("numeric_tables_without_headers", []),
        ])),
        fallback={**attempt, "status": "selected"},
        baseline_quality=baseline.quality,
    )
    return candidate


def publisher_dom_publication_date(soup: BeautifulSoup, page_url: str) -> str | None:
    """处理：按已核验的来源发布栏读取日期，避开正文与推荐文章。
    输入：原网页 DOM 和最终文章地址，地址缺失时使用网页声明的规范地址。
    输出：上海时区的明确发布时间或日精度日期，未出现发布栏时为空。
    """
    if not page_url:
        canonical = soup.select_one(
            'link[rel="canonical"], meta[property="og:url"], meta[name="og:url"]',
        )
        page_url = (str(canonical.get("href") or canonical.get("content") or "")
                    if canonical else "")
    host = (urlsplit(page_url).hostname or "").removeprefix("www.")
    if host == "sec.gov" and urlsplit(page_url).path.startswith("/Archives/edgar/data/"):
        for label in soup.select(".infoHead"):
            if label.get_text(" ", strip=True) == "Accepted":
                value = label.find_next_sibling(class_="info")
                if value:
                    text = value.get_text(" ", strip=True)
                    if re.fullmatch(r"20\d{2}-\d\d-\d\d \d\d:\d\d:\d\d", text):
                        return normalize_time(text, "America/New_York")
        return None
    selectors = {
        "ithome.com": "#pubtime_baidu",
        "ithome.com.tw": ".submitted .created",
        "tmtpost.com": ".post_author_infor .time",
        "geekpark.net": ".user-info .release-date",
        "qbitai.com": ".article_info",
        "solidot.org": ".talk_time",
        "pansci.asia": ".stript > section .row.align-items-center .post-text-light",
        "cnbeta.com.tw": ".cnbeta-article > header.title .meta > span:first-child",
        "yicai.com": ".m-text > .title em.f-fl",
        "news.rthk.hk": ".createddate",
    }
    selector = selectors.get(host)
    node = soup.select_one(selector) if selector else None
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    text = re.sub(r"[年/月.]", "-", text).replace("日", " ")
    text = text.replace("时", ":").replace("分", "").replace("HKT", "")
    match = re.search(
        r"20\d{2}-\d{1,2}-\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", text,
    )
    if not match:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(" ".join(match[0].split()), pattern)
        except ValueError:
            continue
        return (parsed.date().isoformat() if pattern == "%Y-%m-%d" else
                normalize_time(parsed.isoformat(), "Asia/Shanghai"))
    return None


def _abc_entry_publication(soup: BeautifulSoup, entry_id: str) -> str | None:
    """处理：在 ABC 直播渲染数据中按条目编号读取公开卡片的发稿时间。
    输入：原网页 DOM、来自文章 URL 的独立更新编号。
    输出：与该编号唯一匹配的时间，避免使用母页或其他更新的时间。
    """
    marker = "window['__abcnews__']="
    stamps: set[str] = set()
    for script in soup.find_all("script"):
        _, found, raw = (script.string or "").partition(marker)
        if not found:
            continue
        try:
            state, _ = json.JSONDecoder().raw_decode(raw.lstrip())
            components = state["page"]["content"]["data"]["mainComponents"]
        except (KeyError, TypeError, ValueError):
            continue
        for component in components:
            entries = (component.get("props") or {}).get("entries") or []
            for entry in entries:
                if str(entry.get("id") or "") != entry_id:
                    continue
                published = (entry.get("issued") or
                             ((entry.get("shareBylineData") or {}).get("publishedDate") or {})
                             .get("date"))
                if isinstance(published, str) and (value := normalize_time(published)):
                    stamps.add(value)
    return next(iter(stamps)) if len(stamps) == 1 else None


def observed_source_metadata(soup: BeautifulSoup, page_url: str = "") -> dict[str, Any]:
    """处理：记录页面明确声明的作者、发布者、发布日期与语言。
    输入：清洗之前的页面 DOM；只接受发布语义元数据，不把更新时间当发布日期。
    输出：供出处和当天新闻筛选使用的有限字段；没有明确发布日期时保留未知。
    """
    values: dict[str, Any] = {}
    for key, selector in (
        ("author", 'meta[name="author"], meta[property="article:author"]'),
        ("publisher", 'meta[property="og:site_name"]'),
    ):
        node = soup.select_one(selector)
        values[key] = str(node.get("content") or "").strip()[:500] or None if node else None
    if abc_entry := abc_live_entry_id(page_url):
        return {
            **values, "published_at": _abc_entry_publication(soup, abc_entry),
            "publication_entry_id": abc_entry,
            "language": str(soup.html.get("lang") or "")[:80] or None if soup.html else None,
            "basis": "page_declared", "independent_origin": None,
        }
    published_at = None
    for node in soup.select(
        'meta[property="article:published_time"], meta[name="article:published_time"]'
    ):
        published_at = str(node.get("content") or "").strip()
        if published_at:
            break
    if not published_at:
        for node in soup.select('[itemprop="datePublished"]'):
            published_at = str(
                node.get("content") or node.get("datetime") or node.get_text(" ", strip=True)
            ).strip()
            if published_at:
                break
    if not published_at:
        article_types = {
            "article", "newsarticle", "analysisnewsarticle", "reportagenewsarticle",
            "blogposting", "scholarlyarticle",
        }

        def article_dates(value: Any) -> list[str]:
            """处理：遍历 JSON-LD 数据图并提取指定文章类型的原始发布日期。
            输入：解析后的 JSON-LD 列表或对象。
            输出：仅包含明确文章类型 datePublished 的原始时间字符串。
            """
            if isinstance(value, list):
                return [date for entry in value for date in article_dates(entry)]
            if not isinstance(value, dict):
                return []
            types = value.get("@type", [])
            if isinstance(types, str):
                types = [types]
            dates = []
            if any(str(kind).rsplit("/", 1)[-1].casefold() in article_types for kind in types):
                date = value.get("datePublished")
                if isinstance(date, str) and date.strip():
                    dates.append(date.strip())
            return dates + [date for entry in value.values() for date in article_dates(entry)]

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            dates = article_dates(payload)
            if dates:
                published_at = dates[0]
                break
    if not published_at:
        social_date = soup.select_one('meta[property="og:published_time"]')
        if social_date:
            published_at = str(social_date.get("content") or "").strip()
    if not published_at:
        node = soup.select_one('[data-target="PaperContent"][data-props]')
        if node:
            try:
                paper = json.loads(node["data-props"]).get("paper", {})
            except (json.JSONDecodeError, TypeError):
                paper = {}
            # Hugging Face 分别声明论文发表与日榜提交日期，这里只读取原始发表。
            date = paper.get("publishedAt")
            if isinstance(date, str) and date.strip():
                published_at = date.strip()
    parts = urlsplit(page_url)
    if not published_at and parts.hostname in {"arxiv.org", "www.arxiv.org"} and (
            parts.path.startswith("/abs/")):
        history = soup.select_one(".submission-history")
        if history:
            # 版本历史中的 v1 有明确 UTC 钟点；引文日期通常只有 UTC 自然日。
            match = re.search(
                r"\[v1\]\s*(\w{3}, \d{1,2} \w{3} \d{4} \d\d:\d\d:\d\d) UTC",
                history.get_text(" ", strip=True),
            )
            if match:
                with suppress(ValueError):
                    published_at = datetime.strptime(
                        match[1], "%a, %d %b %Y %H:%M:%S"
                    ).replace(tzinfo=UTC).isoformat()
    if not published_at:
        for node in soup.select(
            'meta[name="citation_publication_date"], meta[name="citation_date"], '
            'meta[name="PubDate" i]'
        ):
            published_at = str(node.get("content") or "").strip()
            if published_at:
                break
    if not published_at:
        node = soup.select_one(".article__time")
        if node:
            # 读取文章专属发布栏；正文中的会议、事件日期不参与发布日期提取。
            text = node.get_text(" ", strip=True)
            try:
                published_at = datetime.strptime(text, "%B %d, %Y").date().isoformat()
            except ValueError:
                published_at = None
    if parts.hostname == "english.news.cn" and (
        not published_at or len(published_at) == 10
    ):
        # 英文稿页刊头显示北京时间，publishdate 元数据只保留日期。
        header = soup.select_one(".conTop .infoBox .info > p.time")
        if header:
            stamp = header.get_text(" ", strip=True)
            stamp = re.sub(r"\s+(?:UTC|GMT)$", "+00:00", stamp)
            stamp = re.sub(r"\s+Beijing Time$", "", stamp, flags=re.IGNORECASE)
            published_at = normalize_time(stamp, "Asia/Shanghai") or published_at
    if parts.hostname in {"nature.com", "www.nature.com"}:
        # Nature 的可见刊头使用日期，结构化数据可能把同日编码成 UTC 午夜。
        header = soup.select_one("header time[datetime], .c-article-identifiers time[datetime]")
        day = str(header["datetime"]) if header else ""
        if re.fullmatch(r"20\d\d-\d\d-\d\d", day) and (
            not published_at or re.fullmatch(re.escape(day) + r"T00:00:00(?:Z|\+00:00)",
                                             published_at)
        ):
            published_at = day
    if not published_at:
        published_at = publisher_dom_publication_date(soup, page_url)
    values["published_at"] = published_at[:500] if published_at else None
    values["language"] = str(soup.html.get("lang") or "")[:80] or None if soup.html else None
    values.update(basis="page_declared", independent_origin=None)
    return values


def input_fingerprint(content: bytes, kind: str, truncated: bool) -> dict[str, Any]:
    """处理：为抽取前的有界输入生成溯源指纹，不保存凭据或响应头。
    输入：实际读取的字节、HTTP 或可见 DOM 标记，以及截断观测。
    输出：明确哈希覆盖范围的输入记录；截断输入不冒充完整响应。
    """
    return {
        "kind": kind, "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content), "truncated": truncated,
    }
