"""把新闻稿包渲染为单文件 HTML；远程图片需要联网，已缓存的本地图片可离线显示。"""

from __future__ import annotations

import html
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit

from .config import project_root
from .local_output import _embedded_image_sources

_ASSET_DIR = project_root() / "assets" / "news-slides"


def _text(value: object) -> str:
    """处理：把外部字段编码为 HTML 文本或属性值。

    输入：任意新闻或报告字段值。
    输出：可安全插入 HTML 的转义字符串，空值转换为空串。
    """
    return html.escape(str(value or ""), quote=True)


def _url(value: object) -> str:
    """处理：限制外链为网页协议并转义供 HTML 引用。

    输入：新闻来源或图片提供的 URL 字段。
    输出：HTTP(S) URL 的转义形式；其他协议或空值返回空串。
    """
    candidate = str(value or "")
    return _text(candidate) if urlsplit(candidate).scheme.lower() in {"http", "https"} else ""


def _local_image_uri(local_path: str, data_dir: Path | None) -> str:
    """处理：从数据根读取并嵌入受限的本地新闻图片。

    输入：媒体相对路径和可选数据根目录。
    输出：已校验图片的数据 URI；路径缺失、越界或文件不可用时返回空串。
    """
    if data_dir is None:
        return ""
    mime = mimetypes.guess_type(local_path)[0] or "image/jpeg"
    record = {
        "sections": [{"briefs": [{"image": {"local_path": local_path, "content_type": mime}}]}]
    }
    embedded = _embedded_image_sources(record, data_dir)
    return embedded.get(local_path.replace("\\", "/"), "")


def _source_markup(sources: list[dict], language: str) -> str:
    """处理：将来源排成紧凑链接，完整标题与时间放入可展开依据区。
    输入：日报原始来源及显示语言；来源名称不由模型改写。
    输出：紧邻新闻讲解的出处 HTML，避免长标题占用主视觉版面。
    """
    links, details = [], []
    for source in sources:
        name = _text(source.get("name") or source.get("title") or "Source")
        link = (f'<a href="{_url(source.get("url"))}" target="_blank" '
                f'rel="noopener noreferrer">{name}<span aria-hidden="true">↗</span></a>')
        links.append(link)
        access = {"full_text": "正文", "partial": "部分正文", "metadata_only": "摘要"}.get(
            source.get("access"), ""
        ) if language == "zh-CN" else source.get("access", "")
        details.append(f'<li>{link}<span>{_text(source.get("title"))}</span>'
                       f'<small>{_text(source.get("published_at"))} · {_text(access)}</small></li>')
    label = "来源与依据" if language == "zh-CN" else "Sources & context"
    return (f'<div class="source-chips">{"".join(links)}</div>'
            f'<details class="source-list"><summary>{label} <span>+</span></summary>'
            f'<ul>{"".join(details)}</ul></details>') if sources else ""


def _gallery_markup(images: list[dict], labels: tuple, data_dir: Path | None,
                    position: int, image_uri_cache: dict[str, str]) -> str:
    """处理：把原图与原文图注置于独立主视觉框，保留完整图片查看入口。
    输入：新闻图片记录、本地缓存目录、页面序号和本次渲染图片 URI 缓存；不改写图注。
    输出：有图时返回切换图集，无图时返回明确标注的排版示意图形。
    """
    figures = []
    for entry in images:
        local_path = str(entry.get("local_path") or "").replace("\\", "/")
        if local_path not in image_uri_cache:
            image_uri_cache[local_path] = _local_image_uri(local_path, data_dir)
        url = image_uri_cache[local_path]
        url = url or _url(entry.get("url"))
        caption = (
            f'<figcaption>{_text(entry["caption"])}</figcaption>' if entry.get("caption") else ""
        )
        source_url = _url(entry.get("source_url"))
        source = (f'<a href="{source_url}" target="_blank" rel="noopener noreferrer">'
                  f'{labels[7]} ↗</a>') if source_url else ""
        original = _url(entry.get("url") or entry.get("resolved_url"))
        original_link = (
            f'<a href="{original}" target="_blank" rel="noopener noreferrer">'
            f'{labels[13]} ↗</a>'
        ) if original else ""
        disabled = "" if url else " disabled"
        figures.append(
            f'<figure data-original="{original}"><div class="image-frame">'
            f'<img src="{url}" alt="{_text(entry.get("alt"))}" loading="lazy">'
            f'<span class="image-fallback">{labels[8]}</span>'
            f'<button class="image-open" data-open-image aria-label="{labels[12]}"{disabled}>'
            f'<span>{labels[12]} ↗</span></button></div>{caption}'
            f'<div class="image-credit">{_text(entry.get("credit"))} {source} {original_link}'
            '</div></figure>'
        )
    if not figures:
        return (f'<div class="visual-placeholder" aria-label="{labels[11]}">'
                '<div class="field-lines" aria-hidden="true"><i></i><i></i><i></i><i></i></div>'
                f'<span class="placeholder-number" aria-hidden="true">{position:02}</span>'
                f'<p>{labels[11]}<span> SIGNAL / {position:02}</span></p></div>')
    controls = (
        '<div class="gallery-controls">'
        f'<button data-image-prev aria-label="{labels[9]}">↖</button>'
        '<span class="image-count"></span>'
        f'<button data-image-next aria-label="{labels[10]}">↗</button></div>'
    ) if len(figures) > 1 else ""
    return (f'<div class="gallery" data-gallery><div class="visual-topline">'
            f'<span>SOURCE IMAGERY</span><span>FIG. {position:02}</span></div>'
            f'{"".join(figures)}{controls}'
            '<div class="gallery-thumbnails" data-thumbnails></div>'
            '<span class="visual-cross" aria-hidden="true">+</span>'
            '</div>')


def render_slides_html(deck: dict, data_dir: Path | None = None) -> str:
    """处理：读取新闻稿包、装配逐条新闻页并内嵌静态资源。

    输入：``deck`` 含标题、语言、日期、报告编号和新闻页；可选 ``data_dir``
    为本地图片提供数据根。外部文字统一转义，链接仅允许 HTTP(S)。
    输出：包含内嵌模板与交互控件的单文件 HTML；本地图片可嵌入，远程图片需联网加载。
    """
    language = "zh-CN" if deck.get("language") == "zh-CN" else "en"
    labels = {
        "zh-CN": (
            "目录",
            "上一条",
            "下一条",
            "全屏",
            "来源",
            "摘要",
            "讲解",
            "图片来源",
            "图片不可用",
            "上一张图片",
            "下一张图片",
            "本条暂无配图 · 排版示意",
            "查看大图",
            "原始图片",
        ),
        "en": (
            "Contents",
            "Previous",
            "Next",
            "Fullscreen",
            "Sources",
            "Summary",
            "Story",
            "Image source",
            "Image unavailable",
            "Previous image",
            "Next image",
            "No source image · graphic illustration",
            "View larger image",
            "Original image",
        ),
    }[language]
    slides: list[str] = []
    toc: list[str] = []
    image_uri_cache: dict[str, str] = {}
    for index, slide in enumerate(deck.get("slides", [])):
        title = _text(slide.get("title"))
        toc.append(
            f'<button class="toc-item" data-go="{index}" aria-label="{index + 1}. {title}">'
            f'<span>{index + 1:02}</span><strong>{title}</strong>'
            '<i aria-hidden="true">↗</i></button>'
        )
        narration = "".join(
            f"<p>{_text(line)}</p>"
            for line in str(slide.get("narration") or "").splitlines()
            if line.strip()
        )
        gallery = _gallery_markup(
            slide.get("images", []), labels, data_dir, index + 1, image_uri_cache
        )
        sources = _source_markup(slide.get("sources", []), language)
        story_grid_class = "story-grid" if slide.get("images") else "story-grid no-gallery"
        headline_class = "headline compact" if len(slide.get("title", "")) > 28 else "headline"
        slides.append(
            f'<article class="slide" aria-labelledby="headline-{index}">'
            f'<div class="{story_grid_class}"><div class="story-copy">'
            f'<p class="eyebrow"><span class="story-badge">{index + 1:02}</span>'
            '<span>NEWS / FIELD NOTES</span><span class="eyebrow-line"></span></p>'
            f'<h2 class="{headline_class}" id="headline-{index}">{title}</h2>'
            f'<p class="summary">{_text(slide.get("summary"))}</p>'
            f'<section class="narration-section"><h3><span>↳</span> {labels[6]}</h3>'
            f'<div class="narration">{narration}</div></section>{sources}'
            f'</div><div class="story-visual">{gallery}</div></div>'
            f'<span class="story-rail" aria-hidden="true">{index + 1:02}'
            ' / NEWS &amp; CONTEXT</span>'
            '</article>'
        )

    template = (_ASSET_DIR / "template.html").read_text(encoding="utf-8")
    replacements = {
        "LANG": language,
        "TITLE": _text(deck.get("title") or "SignalTrail"),
        "AS_OF": _text(str(deck.get("as_of") or "")[:10].replace("-", " / ")),
        "REPORT_ID": _text(deck.get("report_id")),
        "CSS": (_ASSET_DIR / "slides.css").read_text(encoding="utf-8"),
        "JS": (_ASSET_DIR / "slides.js").read_text(encoding="utf-8"),
        "TOC_LABEL": labels[0],
        "PREVIOUS": labels[1],
        "NEXT": labels[2],
        "FULLSCREEN": labels[3],
        "CLOSE": "关闭目录" if language == "zh-CN" else "Close contents",
        "EDITION_LABEL": "图文新闻" if language == "zh-CN" else "VISUAL EDITION",
        "NEXT_LABEL": "接着看" if language == "zh-CN" else "UP NEXT",
        "KEYBOARD_HINT": "← → 切换新闻" if language == "zh-CN" else "← → TO NAVIGATE",
        "TOC": "".join(toc),
        "SLIDES": "".join(slides) or '<p class="empty">No stories in this edition.</p>',
        "COUNT": str(len(slides)),
        "NO_SCRIPT": "当前浏览器未启用 JavaScript；所有新闻仍可向下阅读。"
        if language == "zh-CN"
        else "JavaScript is unavailable; all stories remain readable below.",
        "IMAGE_VIEWER": labels[12],
        "ORIGINAL_IMAGE": labels[13],
        "IMAGE_PREVIOUS": labels[9],
        "IMAGE_NEXT": labels[10],
        "CLOSE_IMAGE": "关闭大图" if language == "zh-CN" else "Close image",
        "IMAGE_ZOOM": "原始尺寸" if language == "zh-CN" else "Actual size",
    }
    return re.sub(
        r"{{([A-Z_]+)}}",
        lambda match: replacements[match.group(1)],
        template,
    )
