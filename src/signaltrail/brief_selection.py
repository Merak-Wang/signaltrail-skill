"""逐来源选择最新的合格原文。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .article_time import original_publication_time, published_on_date
from .utils import canonicalize_url


def select_brief_items(
    candidates: list[dict[str, Any]], source_configs: dict[str, Any],
    *, date_value: str | None = None, cutoff: str | None = None,
) -> list[dict[str, Any]]:
    """处理：筛选当日原文并按每源发布时间倒序去重、截取。
    输入：采集候选、来源配置以及可选的版本日期和截止时间。
    输出：每源最新最多 15 篇，保留各条目的原始来源信息。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        if date_value and not published_on_date(item, date_value, cutoff):
            continue
        source_id = str(item.get("source_id") or "item:" + str(item["item_id"]))
        grouped.setdefault(source_id, []).append(item)
    selected = []
    for items in grouped.values():
        seen: set[str] = set()
        ordered = sorted(items, key=lambda row: original_publication_time(row) or "", reverse=True)
        for item in ordered:
            raw_url = item.get("canonical_url") or item.get("url")
            identity = canonicalize_url(raw_url) if raw_url else "item:" + str(item["item_id"])
            parts = urlsplit(identity)
            if (parts.hostname in {"bbc.com", "bbc.co.uk"}
                    and parts.path.startswith("/news/articles/")):
                identity = "bbc:" + parts.path.rstrip("/")
            if identity in seen:
                continue
            selected.append(item)
            seen.add(identity)
            if len(seen) == 15:
                break
    return selected
