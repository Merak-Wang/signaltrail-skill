from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from importlib.metadata import version
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

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
                        "text": _inline_text(cell), "header": cell.name == "th",
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
        "article", "main", "body",
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
            usable = substantive and link_density < 0.5
            complete = usable and specific and not incomplete and not truncated and not table_gaps
            quality = {
                "extractor": "builtin", "extractor_version": "2",
                "region": "specific" if specific else "broad",
                "characters": characters, "block_count": len(blocks),
                "link_density": round(link_density, 4),
                "incomplete_marker": incomplete, "response_truncated": truncated,
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
    return round(sum(token in text.casefold() for token in tokens) / len(tokens), 4)


def extract_with_fallback(
    soup: BeautifulSoup, selectors: list[str], *, truncated: bool = False,
    expected_title: str = "", fallback: str = "none",
) -> ExtractedDocument:
    """处理：保留具体正文基线，仅在内容不足时比较可选本地抽取器。
    输入：已获准读取的 HTML、来源选择器和显式配置的候选抽取器。
    输出：带选择理由的正文；供应器失败不丢失基线，供应器输出不自动升级为全文。
    """
    source_metadata = observed_source_metadata(soup)
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
    if baseline.status != ContentStatus.METADATA_ONLY and (
        len(candidate.text) > len(baseline.text)
        or candidate.quality.get("link_density", 1) > baseline.quality.get("link_density", 0)
    ):
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


def observed_source_metadata(soup: BeautifulSoup) -> dict[str, Any]:
    """处理：记录页面自行声明的作者、发布者与语言，保留未知归属。
    输入：清洗之前的页面 DOM；元信息仅为发布者声明。
    输出：供出处审计使用的有限字段，不从域名推断作者或独立转载关系。
    """
    values: dict[str, Any] = {}
    for key, selector in (
        ("author", 'meta[name="author"], meta[property="article:author"]'),
        ("publisher", 'meta[property="og:site_name"]'),
        ("published_at", 'meta[property="article:published_time"]'),
    ):
        node = soup.select_one(selector)
        values[key] = str(node.get("content") or "").strip()[:500] or None if node else None
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
