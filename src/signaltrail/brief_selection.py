"""逐来源收录当日原文并保留来源Top顺序。"""

from __future__ import annotations

from typing import Any

from .article_time import published_on_date
from .utils import canonicalize_url


def select_brief_items(
    candidates: list[dict[str, Any]], source_configs: dict[str, Any],
    *, date_value: str | None = None, cutoff: str | None = None,
) -> list[dict[str, Any]]:
    """处理：逐来源扫描全部当日原文，保留各源Top并在本源内去重。
    输入：规范候选、来源配置及可选的本版自然日和冻结时刻。
    输出：不受抽样名额限制的候选；跨源保留各自展示位置。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        if date_value and not published_on_date(item, date_value, cutoff):
            continue
        if item.get("source_id"):
            grouped.setdefault(str(item["source_id"]), []).append(item)
    seen: set[str] = set()
    selected = []
    for source_id, items in grouped.items():
        for item in sorted(items, key=lambda row: row.get("source_rank") or (
                row.get("metadata") or {}).get("source_rank", float("inf"))):
            raw_url = item.get("canonical_url") or item.get("url")
            url = canonicalize_url(raw_url) if raw_url else ""
            identity = source_id + ":" + (url or "item:" + str(item["item_id"]))
            if identity in seen:
                continue
            selected.append(item)
            seen.add(identity)
    return selected
