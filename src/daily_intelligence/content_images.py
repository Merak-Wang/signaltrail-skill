from __future__ import annotations

import re
from typing import Any

from bs4 import Tag

from .content_extraction import ExtractedDocument, _inline_text
from .image_policy import normalize_image_candidates, srcset_candidates


def _image_caption(node: Tag, root: Tag) -> str:
    """处理：从图片所在的单图容器读取网站图注，不借用相邻图片说明。
    输入：正文图片节点及选中的正文边界。
    输出：清理空白后的原文图注；正文范围内没有对应图注时返回空串。
    """
    for container in node.parents:
        # 单图容器内的 caption 才属于当前图片，避免借用相邻配图的说明。
        if len(container.find_all("img", limit=2)) != 1:
            break
        caption = container.select_one(
            'figcaption, .wp-caption-text, .image-caption, .photo-caption, '
            '.caption, [itemprop="caption"]'
        )
        if caption is not None:
            return re.sub(r"\s+", " ", _inline_text(caption)).strip()
        if container is root:
            break
    return ""


def _terms(text: str) -> set[str]:
    """处理：抽取标题与图注可比较的英文词和中文二元片段。
    输入：页面标题、替代文本或图注；只作为词法相关性线索。
    输出：去重词集合，不代表图片内容已完成语义核验。
    """
    terms = set(re.findall(r"[a-z0-9]{3,}", text.casefold()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.update(run[index:index + 2] for index in range(len(run) - 1))
    return terms - {"the", "and", "for", "with", "from", "that", "this"}


def article_image_candidates(
    document: ExtractedDocument, title: str, base_url: str,
) -> list[dict[str, Any]]:
    """处理：仅从选中的具体正文区域收集配图，保留图注及相邻文本依据。
    输入：正文抽取结果、当前条目标题与页面最终 URL。
    输出：按图注、词法关联和原始顺序排列的候选；宽泛页面不提供配图证据。
    """
    root = document.node
    if root is None or document.quality.get("region") != "specific":
        return []
    candidates = []
    title_terms = _terms(title)
    for position, node in enumerate(root.select("img")[:24]):
        alt = str(node.get("alt") or "").strip()
        if node.get("role") == "presentation" or re.search(
            r"\b(?:logo|avatar|icon)\b|头像|图标", alt, re.I,
        ):
            continue
        caption = _image_caption(node, root)
        adjacent = node.find_next("p")
        surrounding = (
            adjacent.get_text(" ", strip=True)[:1000]
            if adjacent is not None and root in adjacent.parents else ""
        )
        overlap = len(title_terms & _terms(f"{alt} {caption}"))
        urls = normalize_image_candidates([
            *srcset_candidates(node.get("srcset") or node.get("data-srcset")),
            node.get("data-original"), node.get("data-src"), node.get("data-lazy-src"),
            node.get("src"),
        ], base_url)
        for variant, url in enumerate(urls):
            candidates.append({
                "url": url, "provenance": "article_body", "purpose": "article_illustration",
                "alt": alt[:1000], "caption": caption, "surrounding_text": surrounding,
                "relevance_score": overlap, "relevance_basis": "title_caption_lexical_overlap",
                "semantic_verification": "not_performed",
                "declared_width": str(node.get("width") or ""),
                "declared_height": str(node.get("height") or ""),
                "position": position, "variant": variant,
            })
    return sorted(candidates, key=lambda entry: (
        -entry["relevance_score"], -bool(entry["caption"]), entry["position"], entry["variant"],
    ))
