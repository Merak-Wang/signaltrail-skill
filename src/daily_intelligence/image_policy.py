from __future__ import annotations

import math
import re
from collections.abc import Iterable
from urllib.parse import unquote, urljoin, urlsplit

_PLACEHOLDER_MARKERS = (
    "placeholder",
    "default-image",
    "default_image",
    "defaultimage",
    "image-not-found",
    "image_not_found",
    "missing-image",
    "missing_image",
    "no-image",
    "no_image",
    "noimage",
)
_PLACEHOLDER_FILENAMES = {
    "blank.gif",
    "blank.png",
    "spacer.gif",
    "spacer.png",
    "transparent.gif",
    "transparent.png",
}


def is_placeholder_image_url(value: object) -> bool:
    """处理：判断地址是否明显指向占位图而非内容图片。
    输入：
    - ``value``：待解析或规范化的单个输入值；非法值按函数契约返回空值或报错。
    输出：布尔判断；True 表示满足处理说明中的条件，False 表示不满足且不产生该结果。
    """
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlsplit(text)
    path = unquote(parsed.path).replace("\\", "/").casefold()
    filename = path.rsplit("/", 1)[-1]
    return filename in _PLACEHOLDER_FILENAMES or any(
        marker in path for marker in _PLACEHOLDER_MARKERS
    )


def normalize_image_candidates(
    values: Iterable[object],
    base_url: str = "",
) -> list[str]:
    """处理：解析、过滤并稳定去重不可信图片候选。
    输入：
    - ``values``：待规范化、匹配或渲染的一组输入值。
    - ``base_url``：解析相对链接时使用的最终页面或 Feed 基准 URL。
    输出：“解析、过滤并稳定去重不可信图片候选”得到的字符串列表；
      顺序保持确定并可供下一步骤逐项处理。
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        resolved = urljoin(base_url, raw)
        parsed = urlsplit(resolved)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or is_placeholder_image_url(resolved)
            or resolved in seen
        ):
            continue
        seen.add(resolved)
        candidates.append(resolved)
    return candidates


def srcset_candidates(value: object) -> list[str]:
    """处理：解析响应式图片描述符，在同一单位内优先返回较大图片。
    输入：页面或 Feed 中不可信的 srcset 属性；无描述符按 1x 处理。
    输出：稳定去重的地址列表；非法描述符被丢弃，混用 w/x 时保持组间声明顺序。
    """
    groups: dict[str, list[tuple[float, str]]] = {}
    # URL 本身可能含逗号；先读到空白，再解析描述符，避免拆坏 CDN 查询或 data URL。
    remaining = str(value or "")
    while remaining := remaining.lstrip(" \t\n\r\f,"):
        match = re.match(r"[^\s]+", remaining)
        assert match is not None
        token = match.group()
        remaining = remaining[match.end():]
        url = token.rstrip(",")
        descriptors: list[str] = []
        if not token.endswith(","):
            descriptor_text, _separator, remaining = remaining.partition(",")
            descriptors = descriptor_text.split()
        if not descriptors:
            unit, size = "x", 1.0
        elif len(descriptors) == 1 and re.fullmatch(r"[0-9]+w", descriptors[0]):
            unit, size = "w", float(descriptors[0][:-1])
        elif len(descriptors) == 1 and re.fullmatch(
            r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?x", descriptors[0]
        ):
            unit, size = "x", float(descriptors[0][:-1])
        else:
            continue
        if size > 0 and math.isfinite(size):
            groups.setdefault(unit, []).append((size, url))
    return list(dict.fromkeys(
        url
        for entries in groups.values()
        for _size, url in sorted(entries, key=lambda entry: -entry[0])
    ))
