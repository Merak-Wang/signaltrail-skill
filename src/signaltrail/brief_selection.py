"""逐来源选择最新的合格原文。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit

from .article_time import normalize_time, original_publication_time, publication_on_date
from .utils import canonicalize_url


def without_cbc_tracking(parts: SplitResult, *, include_radio: bool = True) -> SplitResult:
    """处理：去除 CBC 文章链接的 cmp 跟踪参数。
    输入：已解析的链接，旧审核回放可限于新闻文章。
    输出：用于选题身份比较的链接组成，保留其他查询参数。
    """
    path_prefix = r"/(?:news|radio)/" if include_radio else r"/news/"
    if (parts.hostname not in {"cbc.ca", "www.cbc.ca"} or not parts.query
            or not re.fullmatch(path_prefix + r".+-\d+\.\d+/?", parts.path)):
        return parts
    query = parse_qsl(parts.query, keep_blank_values=True)
    return parts._replace(query=urlencode([(key, value) for key, value in query if key != "cmp"]))


def dw_article_identity(url: str) -> str | None:
    """处理：按 DW 语言与文章编号识别原文。
    输入：来源链接，标题路径和跟踪参数可变化。
    输出：用于去重的稳定键，未知地址返回空。
    """
    parts = urlsplit(url)
    if (parts.scheme not in {"http", "https"}
            or parts.netloc.lower().removeprefix("www.") != "dw.com"):
        return None
    match = re.fullmatch(r"/([a-z]{2}(?:-[a-z]{2})?)/[^/]+/((?:a|live)-\d+)/?", parts.path)
    return f"dw:{match[1]}:{match[2]}" if match else None


def select_brief_items(
    candidates: list[dict[str, Any]], source_configs: dict[str, Any],
    *, date_value: str | None = None, cutoff: str | None = None,
    collapse_dw_aliases: bool = True,
) -> list[dict[str, Any]]:
    """处理：筛选当日原文并按每源发布时间倒序去重、截取。
    输入：采集候选、来源配置以及可选的版本日期和截止时间。
    输出：每源最新最多 15 篇，保留各条目的原始来源信息。
    """
    end = normalize_time(cutoff or "", "Asia/Shanghai") if date_value else None
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for item in candidates:
        stamp = original_publication_time(item)
        if date_value and not publication_on_date(stamp, date_value, end):
            continue
        source_id = str(item.get("source_id") or "item:" + str(item["item_id"]))
        grouped.setdefault(source_id, []).append((stamp or "", item))
    selected = []
    for items in grouped.values():
        seen: set[str] = set()
        for _, item in sorted(items, key=lambda row: row[0], reverse=True):
            raw_url = item.get("canonical_url") or item.get("url")
            identity = canonicalize_url(raw_url) if raw_url else "item:" + str(item["item_id"])
            parts = urlsplit(identity)
            if (parts.hostname in {"bbc.com", "bbc.co.uk"}
                    and parts.path.startswith("/news/articles/")):
                identity = "bbc:" + parts.path.rstrip("/")
            elif parts.netloc == "cbc.ca":
                identity = without_cbc_tracking(parts, include_radio=collapse_dw_aliases).geturl()
            elif collapse_dw_aliases:
                identity = dw_article_identity(identity) or identity
            if identity in seen:
                continue
            selected.append(item)
            seen.add(identity)
            if len(seen) == 15:
                break
    return selected
