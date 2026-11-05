"""按来源名额分配不重复的简报文章，保留原始索引证据。"""

from __future__ import annotations

from typing import Any

from .utils import canonicalize_url


def select_brief_items(
    candidates: list[dict[str, Any]], source_configs: dict[str, Any],
) -> list[dict[str, Any]]:
    """处理：逐来源扫描原排序，同篇文章仅占一个位置，重复后从本源尾部补位。
    输入：规范索引或情境候选，以及来源原有目标和上限。
    输出：全局地址唯一的实际简报候选；不同地址的同事件报道保持独立。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        if item.get("source_id"):
            grouped.setdefault(str(item["source_id"]), []).append(item)
    seen: set[str] = set()
    selected = []
    for source_id, items in grouped.items():
        source = source_configs.get(source_id)
        target = min(int(getattr(source, "report_target", 15)),
                     int(getattr(source, "report_max", 15)), 15)
        count = 0
        for item in items:
            if count >= target:
                break
            raw_url = item.get("canonical_url") or item.get("url")
            url = canonicalize_url(raw_url) if raw_url else ""
            identity = url or "item:" + str(item["item_id"])
            if identity in seen:
                continue
            selected.append(item)
            seen.add(identity)
            count += 1
    return selected
