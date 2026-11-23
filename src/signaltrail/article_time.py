"""统一来源日期与榜单观测，保留发表、更新和发现的不同含义。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .utils import canonicalize_url

PLATFORM_PUBLICATION_SOURCES = frozenset({
    "weibo_hot", "hacker_news", "lobsters", "huggingface_papers",
    "papers_with_code", "github_trending", "google_news_china",
})


def abc_live_entry_id(url: str) -> str | None:
    """处理：识别 ABC 直播更新的独立地址。
    输入：原文地址，常规报道与直播母页无 entryId。
    输出：独立更新的数字编号或空值。
    """
    parts = urlsplit(url)
    if parts.hostname not in {"abcnews.com", "www.abcnews.com"}:
        return None
    if "/live-updates/" not in parts.path.lower():
        return None
    entry, *ambiguous = parse_qs(parts.query).get("entryId", [""])
    return entry if entry.isascii() and entry.isdigit() and not ambiguous else None


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
    if re.fullmatch(r"(?:\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2}, \d{4})", text):
        for date_format in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(text, date_format).date().isoformat()
            except ValueError:
                continue
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


def _declared_datetime(value: str) -> datetime | None:
    """处理：解析来源明确日期，保留是否携带时区的区别。
    输入：原网页或Feed原始日期字符串。
    输出：未附加默认时区的时间，无法解析时为空。
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("/", "-"))
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            day = normalize_time(value)
            return datetime.fromisoformat(day) if day and len(day) == 10 else None


def uses_platform_publication_time(item: dict) -> bool:
    """处理：区分平台提交时间与发布者原文时间。
    输入：规范条目的来源身份与已有时间语义标记。
    输出：仅真正聚合排名平台为真，不用discovery角色代替时间语义。
    """
    return (item.get("source_id") in PLATFORM_PUBLICATION_SOURCES
            or (item.get("metadata") or {}).get("publication_time_kind") == "platform")


def paper_publication_evidence(item: dict) -> tuple[str, str] | None:
    """处理：为论文原文和收录页复用同编号 arXiv 的首次提交时刻。
    输入：索引条目及日期探测、正文来源记录；输出：原始时刻及其发布者地址。
    """
    source_id = item.get("source_id")
    if source_id not in {"arxiv_ai", "huggingface_papers", "papers_with_code"}:
        return None
    link = urlsplit(item.get("canonical_url") or item.get("url") or "")
    if source_id == "arxiv_ai" and link.hostname in {"arxiv.org", "www.arxiv.org"}:
        paper = re.fullmatch(r"/abs/(\d{4}\.\d{4,6})(?:v\d+)?/?", link.path)
    elif source_id != "arxiv_ai" and link.hostname == "huggingface.co":
        paper = re.fullmatch(r"/papers/(\d{4}\.\d{4,6})/?", link.path)
    else:
        return None
    if not paper:
        return None
    metadata = item.get("metadata") or {}
    probe = metadata.get("publication_time_probe") or {}
    source = metadata.get("content_source") or {}
    evidence = [(source.get("published_at"), source.get("url"))]
    if probe.get("status") == "success":
        evidence.insert(0, (probe.get("published_at"), probe.get("final_url")))
    for stamp, url in evidence:
        publisher = urlsplit(url or "")
        if (publisher.hostname in {"arxiv.org", "www.arxiv.org"}
                and publisher.path.rstrip("/") in {
                    f"/abs/{paper[1]}", f"/abs/{paper[1]}v1",
                }):
            parsed = _declared_datetime(stamp or "")
            if parsed and parsed.tzinfo is not None:
                return stamp, url
    return None


def original_publication_time(item: dict, timezone: str = "Asia/Shanghai") -> str | None:
    """处理：取得原文时间并保留日精度，发现平台时间不替代原文。
    输入：规范条目与目标时区，原文日期来自已有来源元数据。
    输出：规范发表时间或日期，原文日期未知时为空。
    """
    metadata = item.get("metadata") or {}
    paper = paper_publication_evidence(item)
    if paper:
        return normalize_time(paper[0], timezone)
    original = str((metadata.get("content_source") or {}).get("published_at") or "")
    if item.get("source_id") == "bbc_world" and metadata.get("publication_time_missing"):
        return normalize_time(original, timezone)
    if metadata.get("publication_time_basis") == "relative" and not original:
        return None
    if uses_platform_publication_time(item):
        return normalize_time(original, timezone)
    feed_raw = str(metadata.get("published_raw") or "")
    feed_time = _declared_datetime(feed_raw)
    feed = (normalize_time(feed_raw, timezone) if feed_time and feed_time.tzinfo else
            normalize_time(str(item.get("published_at") or ""), timezone))
    page_time = _declared_datetime(original)
    if (item.get("source_id") == "nature_news" and metadata.get("published_precision") == "date"
            and page_time and page_time.utcoffset() == timedelta(0)
            and page_time.time().isoformat() == "00:00:00"
            and page_time.date().isoformat() == feed_raw):
        # Nature 原文的 UTC 午夜与官方 RSS 的同一日一致时，沿用明确的日精度。
        return feed_raw
    if item.get("source_id") == "un_press":
        # 联合国稿页以纽约午夜占位；官方 RSS 的逐稿 pubDate 保留实际发布时分秒。
        if (metadata.get("feed_url") == "https://press.un.org/en/rss.xml"
                and feed_time and feed_time.tzinfo):
            return feed
        if (page_time is None or page_time.tzinfo is None
                or not any((page_time.hour, page_time.minute, page_time.second))):
            return None
    if page_time is None:
        return feed
    page_date = normalize_time(original, timezone)
    if (page_date and len(page_date) == 10) or page_time.tzinfo:
        return page_date
    if feed_time and feed_time.tzinfo:
        # 同一发布者同一文章的Feed原始偏移可解释网页未标时区的本地钟面时间。
        return normalize_time(page_time.replace(tzinfo=feed_time.tzinfo).isoformat(), timezone)
    current = _declared_datetime(str(item.get("published_at") or ""))
    if current and current.tzinfo:
        return feed
    return normalize_time(original, timezone)


def published_on_date(item: dict, day: str, cutoff: str | None = None) -> bool:
    """处理：按上海自然日和冻结上界筛选原文。
    输入：规范文章、本版日期及可选截止时间。
    输出：原文属于当日且未晚于冻结时刻时为真，未知日期排除。
    """
    return publication_on_date(
        original_publication_time(item), day, normalize_time(cutoff or "", "Asia/Shanghai")
    )


def publication_on_date(stamp: str | None, day: str, cutoff: str | None) -> bool:
    """处理：判断来源声明的原发时间是否属于本版。
    输入：上海时区的原发时间、本版日期与冻结截止时间。
    输出：按来源的日或时刻精度判断是否入选。
    """
    return bool(stamp and stamp[:10] == day and (
        len(stamp) == 10 or not cutoff or len(cutoff) == 10
        or datetime.fromisoformat(stamp) <= datetime.fromisoformat(cutoff)
    ))


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
