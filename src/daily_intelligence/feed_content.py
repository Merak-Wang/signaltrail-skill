from __future__ import annotations

import copy
import hashlib
import html
import json
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .content_extraction import extract_document
from .content_images import article_image_candidates
from .image_policy import srcset_candidates
from .storage import write_immutable_json

_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_ATOM = "http://www.w3.org/2005/Atom"


def xml_context(root: ET.Element) -> dict[ET.Element, tuple[str, str]]:
    """处理：沿 XML 树继承并合成相对 base 与语言。
    输入：已解析的 RSS/Atom 根节点。
    输出：每个节点的地址基准与语言，供条目链接和嵌套 XHTML 共用。
    """
    contexts = {}

    def visit(node: ET.Element, base: str, language: str) -> None:
        """处理：把父级地址和语言传给子节点，局部声明在此覆盖。
        输入：当前节点、父级基准和语言。
        输出：填充外层上下文表，保持 XML 本身不变。
        """
        base = urljoin(base, node.get(_XML_BASE, ""))
        language = node.get(_XML_LANG, language)
        contexts[node] = (base, language)
        for child in node:
            visit(child, base, language)

    visit(root, "", "")
    return contexts


def entry_content(
    node: ET.Element,
    contexts: dict[ET.Element, tuple[str, str]],
    article_url: str,
    feed_url: str,
) -> dict[str, Any] | None:
    """处理：区分纯文本、HTML 和嵌套 XHTML，保留最长文本字段的结构。
    输入：Feed 条目、XML 上下文以及文章和订阅地址。
    输出：独立长内容记录；媒体附件不冒充正文，短摘要由此另行派生。
    """
    candidates = []
    atom = node.tag == f"{{{_ATOM}}}entry"
    for child in node:
        name = child.tag.rsplit("}", 1)[-1].lower()
        namespace = child.tag[1:].split("}", 1)[0] if child.tag.startswith("{") else ""
        if name not in {"content", "description", "encoded", "summary"}:
            continue
        if name == "content" and namespace not in {"", _ATOM}:
            continue
        kind = child.get("type", "text" if atom else "html").lower()
        if kind not in {
            "text",
            "html",
            "xhtml",
            "text/plain",
            "text/html",
            "application/xhtml+xml",
        }:
            continue
        raw_base, language = contexts[child]
        base_url = urljoin(feed_url, raw_base) if raw_base else article_url
        if kind in {"xhtml", "application/xhtml+xml"}:
            clone = copy.deepcopy(child)
            # 清除 XHTML 名称前缀前先按原节点继承 base，避免图片属性在 itertext 中丢失。
            for original, copied in zip(child.iter(), clone.iter(), strict=True):
                copied.tag = copied.tag.rsplit("}", 1)[-1]
                local_base = (
                    urljoin(feed_url, contexts[original][0]) if contexts[original][0] else base_url
                )
                for attribute in ("href", "src", "data-src", "data-original", "data-lazy-src"):
                    if copied.get(attribute):
                        copied.set(attribute, urljoin(local_base, copied.get(attribute)))
                for attribute in ("srcset", "data-srcset"):
                    if copied.get(attribute):
                        copied.set(
                            attribute,
                            ", ".join(
                                urljoin(local_base, value)
                                for value in srcset_candidates(copied.get(attribute))
                            ),
                        )
            markup = "".join(ET.tostring(element, encoding="unicode") for element in clone)
            mime = "application/xhtml+xml"
        else:
            value = "".join(child.itertext()).strip()
            mime = "text/plain" if kind in {"text", "text/plain"} else "text/html"
            markup = html.escape(value) if mime == "text/plain" else value
        soup = BeautifulSoup(f"<article>{markup}</article>", "html.parser")
        document = extract_document(soup, ["article"])
        if document.node is None:
            document.node = soup.article
            document.quality["region"] = "specific"
        images = article_image_candidates(document, "", base_url)
        for image in images:
            image["provenance"] = "feed_content"
        if not document.text and not images:
            continue
        # 保存的是源提供的字段，不据其长度或 article 包装推断文章全文。
        document.quality.update(
            region="provider_candidate",
            extraction_status="partial",
            completeness_basis="feed_field_only",
            article_completeness="unknown",
        )
        document.quality.pop("candidates", None)
        candidates.append(
            {
                "format": "atom" if atom else "rss",
                "source_field": name,
                "mime_type": mime,
                "language": language,
                "base_url": base_url,
                "truncated": False,
                "text": document.text,
                "blocks": document.blocks,
                "quality": document.quality,
                "images": images,
                "links": [
                    {"url": urljoin(base_url, link["href"]),
                     "text": link.get_text(" ", strip=True)}
                    for link in soup.select("a[href]")
                ],
            }
        )
    return max(candidates, key=lambda entry: len(entry["text"]), default=None)


def save_feed_content(
    record: dict[str, Any],
    data_dir: Path,
    source_id: str,
    item_id: str,
    article_url: str,
    feed_url: str,
) -> dict[str, Any]:
    """处理：按条目和内容哈希保存 Feed 长内容，重复刷新复用同一文件。
    输入：解析后的内容、来源身份、订阅地址及数据根。
    输出：紧凑路径、哈希和字符数；索引不嵌入长文，不改变写作候选数量。
    """
    payload = {
        "schema_version": "1.0",
        "item_id": item_id,
        "source_id": source_id,
        "url": article_url,
        "feed_url": feed_url,
        **record,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    path = data_dir / "content" / source_id / item_id / f"feed-{digest}.json"
    if not path.exists():
        with suppress(FileExistsError):
            write_immutable_json(path, payload)
    return {
        "feed_content_path": str(path),
        "feed_content_sha256": digest,
        "feed_content_characters": len(record["text"]),
    }
