"""统一来源日期与榜单观测，保留发表、更新和发现的不同含义。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .utils import canonicalize_url


def normalize_time(value: str, timezone: str | tzinfo = "UTC") -> str | None:
    """处理：来源日期归一为 ISO，纯日期保留日粒度。
    输入：来源原始日期与配置时区，未声明时区的时间采用该配置。
    输出：保留精度的日期或完整时间，无法解释时返回空值。
    """
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        try:
            return datetime.strptime(text.replace("/", "-"), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("/", "-"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (ValueError, TypeError, OverflowError):
            return None
    zone = ZoneInfo(timezone) if isinstance(timezone, str) else timezone
    return parsed.replace(tzinfo=parsed.tzinfo or zone).astimezone(
        zone
    ).isoformat(timespec="seconds")


def in_window(value: str | None, start: datetime, end: datetime) -> bool:
    """处理：完整时间按时刻比较，仅日期按日区间重叠比较。
    输入：来源声明的日期与冻结的日报窗口。
    输出：日期区间与窗口相交时为真，不改写来源发表时刻。
    """
    normalized = normalize_time(value or "", end.tzinfo or "UTC")
    if not normalized:
        return False
    parsed = datetime.fromisoformat(normalized).replace(tzinfo=end.tzinfo) if len(
        normalized
    ) == 10 else datetime.fromisoformat(normalized)
    if len(normalized) == 10:
        return parsed <= end and parsed + timedelta(days=1) > start
    return start <= parsed <= end


def observe_items(
    previous: dict, items: list[dict], observed_at: str, *, preserve_signals: bool = False,
) -> None:
    """处理：以前快照续接首次发现与榜单信号。
    输入：上次快照、本次真实观测条目和检查时间。
    输出：原地补齐稳定首次发现与变化信号，普通刷新保留旧信号日期。
    """
    old = {row["item_id"]: row for row in previous.get("items", [])}
    by_url = {}
    source_urls = {}
    for row in old.values():
        raw_url = row.get("canonical_url") or row.get("url")
        url = canonicalize_url(raw_url) if raw_url else ""
        if url:
            first = (row.get("metadata") or {}).get("first_discovered_at") or row.get(
                "discovered_at", ""
            )
            if first and (url not in by_url or datetime.fromisoformat(
                first
            ) < datetime.fromisoformat(by_url[url])):
                by_url[url] = first
            source_urls[(row.get("source_id"), url)] = row
    known_sources = {
        row.get("source_id") for row in previous.get("sources", [])
        if row.get("status") in {"success", "partial", "no_items"} and not row.get("stale")
    }
    known_sources.update(row.get("source_id") for row in old.values()
                         if not (row.get("metadata") or {}).get("feed_stale"))
    source_checks = {row.get("source_id"): row for row in previous.get("sources", [])}
    for item in items:
        raw_url = item.get("canonical_url") or item.get("url")
        url = canonicalize_url(raw_url) if raw_url else ""
        prior = old.get(item["item_id"]) or source_urls.get((item.get("source_id"), url))
        metadata = item.setdefault("metadata", {})
        before = (prior or {}).get("metadata", {})
        raw = item.get("published_at")
        item["published_at"] = normalize_time(
            raw or "", datetime.fromisoformat(observed_at).tzinfo or "UTC",
        )
        if raw:
            metadata.setdefault("published_raw", raw)
        dates = [value for value in (
            before.get("first_discovered_at"), metadata.get("first_discovered_at"),
            by_url.get(url), (prior or item).get("discovered_at"),
        ) if value]
        metadata["first_discovered_at"] = min(
            dates, key=datetime.fromisoformat,
        ) if dates else observed_at
        if item.get("published_at"):
            metadata["published_precision"] = (
                "date" if len(item["published_at"]) == 10 else "datetime"
            )
        ranked = metadata.get("role") == "discovery" and item.get("category") in {
            "papers", "open_source", "opensource", "projects",
        }
        if ranked:
            metadata["suggested_status"] = "WATCH"
        if not ranked or metadata.get("feed_stale"):
            continue
        if preserve_signals and metadata.get("discovery_signal") and metadata.get("signal_at"):
            continue
        signal = None
        if prior is None or (before.get("feed_stale") and not before.get("discovery_signal")):
            signal = "new_listing" if item.get("source_id") in known_sources else "bootstrap_watch"
        elif (before.get("retained_from_previous_snapshot")
              and source_checks.get(item.get("source_id"), {}).get("status")
              in {"success", "partial", "no_items"}
              and not source_checks[item.get("source_id")].get("stale")):
            signal = "reappeared"
        else:
            rank, old_rank = metadata.get("source_rank"), before.get("source_rank")
            if rank and old_rank and old_rank - rank >= max(3, old_rank // 2):
                signal = "rank_rise"
            for key in ("content_text_sha256", "updated_at"):
                if before.get(key) and metadata.get(key) and before[key] != metadata[key]:
                    signal = "updated"
        if signal:
            metadata.update(discovery_signal=signal, signal_at=observed_at)
        elif before.get("discovery_signal"):
            metadata.update(
                discovery_signal=before["discovery_signal"], signal_at=before["signal_at"]
            )
