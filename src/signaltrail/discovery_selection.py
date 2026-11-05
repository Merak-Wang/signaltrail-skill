"""从发现来源的近期报道中分配有限的日报补充简报名额。"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime

from .article_time import in_window
from .config import SourceConfig
from .models import ArticleItem, SourceResult
from .utils import canonicalize_url


def _content_keys(item: ArticleItem) -> set[str]:
    """处理：以同一规范地址去除重复占位，保留同标题或同事件的不同报道。
    输入：核心采集或监控复用的规范文章。
    输出：去重键集合；不为发现候选额外抓取正文或调用模型。
    """
    return {"url:" + canonicalize_url(item.canonical_url or item.url)}


def _domain(source: SourceConfig) -> str | None:
    """处理：把来源栏目映射到国际、市场和技术三个补充选材范围。
    输入：来源的正式领域与栏目配置。
    输出：共享名额分配使用的领域；国内栏目留给核心来源，不占用国际覆盖名额。
    """
    if source.module == "technology":
        return "technology"
    if source.category in {"market", "markets", "economy"}:
        return "markets"
    return "international" if source.category in {"international", "military"} else None


def select_discovery_items(
    results: dict[str, SourceResult], sources: list[SourceConfig],
    core_items: list[ArticleItem], *, limit: int, start: datetime, end: datetime,
) -> dict[str, list[ArticleItem]]:
    """处理：在冻结窗口内按领域和来源轮询选材，给发现来源分配共享名额。
    输入：新鲜监控结果、发现来源配置、核心文章与本期日报起止时间。
    输出：按来源分组的最多 limit 条补充文章；单来源最多两条，排除核心重复和旧缓存。
    """
    if limit <= 0:
        return {}
    seen = {key for item in core_items for key in _content_keys(item)}
    domains: dict[str, dict[str, deque[ArticleItem]]] = defaultdict(dict)
    priorities = {}
    for source in sources:
        domain = _domain(source)
        result = results.get(source.id)
        if (domain is None or not source.enabled or result is None
                or result.status not in {"success", "partial"}):
            continue
        eligible = []
        for item in result.items:
            metadata = item.metadata
            if (metadata.get("retained_from_previous_snapshot")
                    or metadata.get("feed_stale") or _content_keys(item) & seen):
                continue
            if in_window(item.published_at, start, end):
                date_only = metadata.get("published_precision") == "date" or len(
                    item.published_at or ""
                ) == 10
                metadata["selection_reason"] = (
                    "published_date_overlap" if date_only else "published_in_window"
                )
                if date_only:
                    metadata["suggested_status"] = "WATCH"
                eligible.append((1, item.published_at or "", item))
            elif (source.category in {"papers", "open_source"}
                  and (not item.published_at or in_window(
                      item.published_at, datetime.min.replace(tzinfo=end.tzinfo), end,
                  ))
                  and metadata.get("discovery_signal")
                  and in_window(metadata.get("signal_at"), start, end)):
                metadata["selection_reason"] = metadata["discovery_signal"]
                metadata["suggested_status"] = "WATCH"
                eligible.append((0, str(metadata["signal_at"]), item))
        eligible.sort(key=lambda row: (row[0], row[1]), reverse=True)
        if eligible:
            domains[domain][source.id] = deque(item for _, _, item in eligible)
            priorities[source.id] = (source.tier, -eligible[0][0], source.id)
    selected: dict[str, list[ArticleItem]] = defaultdict(list)

    def take(domain: str, maximum: int) -> int:
        """处理：在一个领域内先轮遍各来源，再允许同源第二条补充。
        输入：领域和本轮剩余名额。
        输出：实际新增数量，同时更新全局内容去重集合。
        """
        added = 0
        source_ids = sorted(domains[domain], key=lambda source_id: priorities[source_id])
        for _ in range(2):
            for source_id in source_ids:
                queue = domains[domain][source_id]
                if added >= maximum:
                    return added
                if len(selected[source_id]) >= 2:
                    continue
                while queue:
                    item = queue.popleft()
                    keys = _content_keys(item)
                    if not keys & seen:
                        selected[source_id].append(item)
                        seen.update(keys)
                        added += 1
                        break
        return added

    international = max(1, limit // 2)
    markets = max(1, limit // 5) if limit >= 3 else 0
    quotas = {
        "international": international, "markets": markets,
        "technology": limit - international - markets,
    }
    total = sum(take(domain, count) for domain, count in quotas.items())
    for domain in quotas:
        total += take(domain, limit - total)
    return {source_id: items for source_id, items in selected.items() if items}
